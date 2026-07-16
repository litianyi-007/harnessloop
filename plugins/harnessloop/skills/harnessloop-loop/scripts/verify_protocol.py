#!/usr/bin/env python3
"""Verify the mechanical subset of the Harnessloop protocol.

Judgment gates (does this evidence support acceptance?) stay with the model.
This script enforces only machine-checkable rules:

- Rule A (scope-lock containment): every file under a round's evidence/ and
  reviews/ directories must fall inside a path allowed by that round's
  scope-lock.md "Allowed Changes" section.
- Rule B (citation existence): every backtick-quoted span in a round's
  review files that looks like a project-relative path must exist in the
  project. A span is exempt from this check (not treated as a citation) if
  any of the following hold:
    - it contains a regex/glob metacharacter (^ $ * ? | ( ) [ ] { } \\ +),
      e.g. a quoted pattern like `^_?\\s*(no|none)\\b` or a shell glob like
      `__pycache__/*.pyc` — these are not literal paths;
    - it opens with a bare (schemeless) domain followed by a path, e.g.
      `docs.python.org/3/library/os.html` or `github.com/org/repo` — full
      `scheme://` URLs were already exempt, this extends that to the bare
      form reviewers commonly write when citing external docs;
    - it contains an angle-bracket placeholder anywhere, e.g.
      `goals/<id>/data-contract.md` — this describes the *shape* of a path
      template, not a literal reference;
    - the citation's line, or the line immediately before it, carries an
      explicit `<!-- verify:ignore -->` HTML comment — use this to mark a
      review line whose citation is known-intentional prose (e.g. quoting
      another document's typo verbatim) rather than a real reference. This
      is the escape hatch for cases the heuristics above cannot resolve
      mechanically; it does not require a project-level opt-out.

  Existence is checked against the project root, the round's goal
  directory, the round directory itself, the project's own `.harnessloop/`
  directory (so a citation using one of the PATHISH_PREFIXES verbatim,
  e.g. `setup/data-sources.md` or `state/self-check.md`, resolves against
  where those directories actually live), and the root of every
  first-level git submodule declared in the project's .gitmodules (so a
  citation written relative to a submodule's own root, e.g. `plugins/foo/`
  when `foo` is checked out as a submodule at <project>/foo, resolves
  correctly instead of being flagged as dangling).

Exit codes: 0 = pass, 1 = violations found, 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

CODE_SPAN = re.compile(r"`([^`]+)`")
PATHISH_PREFIXES = (
    ".harnessloop/",
    "rounds/",
    "evidence/",
    "reviews/",
    "goals/",
    "state/",
    "setup/",
    "meta/",
    "evals/",
    "intake/",
)

# Explicit per-line opt-out for Rule B: a review line that carries this
# marker (or is immediately preceded by a line that does) has every
# citation on it skipped. See module docstring for when to use it.
IGNORE_MARKER = "<!-- verify:ignore -->"

# Regex/glob metacharacters. A backtick span containing any of these is a
# quoted pattern (regex alternation, anchors, glob wildcards, ...), not a
# literal path, so it is never treated as a citation.
PATH_META_CHARS = frozenset("^$*?|(){}[]\\+")

# A bare (schemeless) domain: at least two dot-separated alnum/hyphen
# labels, e.g. "docs.python.org" or "github.com". Anchored so it must
# consume the whole first path segment — this deliberately does not match
# a plain filename with an extension (e.g. "package.json" has no `/`
# after it, and is never even offered to this check; see
# _looks_like_bare_domain).
BARE_DOMAIN_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)


def norm(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def is_under(child: Path, parent: Path) -> bool:
    child_s, parent_s = norm(child), norm(parent)
    return child_s == parent_s or child_s.startswith(parent_s + os.sep)


def extract_allowed_spans(scope_lock_text: str) -> list[str]:
    """Collect allowed paths from the '## Allowed Changes' section.

    Accepts both formats in the wild: backtick path spans in prose/bullets,
    and the scope-lock-template.md table whose first column is the path.
    """
    spans: list[str] = []
    in_section = False
    for line in scope_lock_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.lower() == "## allowed changes"
            continue
        if not in_section:
            continue
        spans.extend(CODE_SPAN.findall(line))
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not cells:
                continue
            first = cells[0].strip("`").strip()
            if (
                first
                and not set(first) <= {"-", ":", " "}
                and first.lower() not in {"path/data/tool", "path", "file", "target"}
                and " " not in first
            ):
                spans.append(first)
    return sorted({s.strip().replace("\\", "/") for s in spans if s.strip()})


def _looks_like_pattern(cleaned: str) -> bool:
    """True if the span contains a regex/glob metacharacter.

    A quoted regex (e.g. ``^_?\\s*(no|none)\\b.*declared.*_?$``) or a shell
    glob (e.g. ``__pycache__/*.pyc``) is not a literal path reference, even
    though it may contain slashes and look pathish otherwise.
    """
    return any(ch in PATH_META_CHARS for ch in cleaned)


def _looks_like_bare_domain(cleaned: str) -> bool:
    """True if the span opens with a schemeless domain followed by a path.

    Matches things like ``docs.python.org/3/library/os.html`` or
    ``github.com/org/repo/blob/main/src/foo.py``. Requires a `/` after the
    domain-looking head so plain filenames with an extension (e.g.
    ``package.json``, which has no trailing path segment) are never
    considered here.
    """
    if "/" not in cleaned:
        return False
    head = cleaned.split("/", 1)[0]
    return bool(BARE_DOMAIN_RE.match(head))


def _looks_like_placeholder(cleaned: str) -> bool:
    """True if the span contains an angle-bracket placeholder anywhere.

    Templated paths such as ``goals/<id>/data-contract.md`` describe a
    *shape* of path, not a literal reference — the leading-character check
    below only catches a span that *starts* with `<`; a placeholder in the
    middle of an otherwise pathish span (e.g. after a real prefix like
    `goals/`) needs its own check.
    """
    return "<" in cleaned or ">" in cleaned


def pathish_citations(markdown_text: str) -> list[str]:
    """Extract citation spans that look like file paths.

    Beyond the protocol prefixes, any slash-containing span with a file
    extension, a trailing slash, or a `..` segment is treated as a path so
    that citations of source/test files (e.g. `src/app.py`) are verified too.
    Spans with spaces, URLs, flags, and variables are ignored, as are
    regex/glob patterns (`_looks_like_pattern`), bare-domain URLs
    (`_looks_like_bare_domain`), and templated paths containing an
    angle-bracket placeholder (`_looks_like_placeholder`, e.g.
    `goals/<id>/data-contract.md`). A line carrying (or immediately
    following a line that carries) the `<!-- verify:ignore -->` marker has
    all of its citations skipped — see module docstring.
    """
    cited: list[str] = []
    lines = markdown_text.splitlines()
    for i, line in enumerate(lines):
        if IGNORE_MARKER in line or (i > 0 and IGNORE_MARKER in lines[i - 1]):
            continue
        for span in CODE_SPAN.findall(line):
            cleaned = span.strip().replace("\\", "/")
            if not cleaned or " " in cleaned or "://" in cleaned:
                continue
            if cleaned.startswith(("-", "$", "<")):
                continue
            if _looks_like_pattern(cleaned):
                continue
            if _looks_like_bare_domain(cleaned):
                continue
            if _looks_like_placeholder(cleaned):
                continue
            if cleaned.startswith(PATHISH_PREFIXES):
                cited.append(cleaned)
                continue
            if "/" in cleaned:
                tail = cleaned.rsplit("/", 1)[-1]
                if Path(tail).suffix or cleaned.endswith("/") or ".." in cleaned:
                    cited.append(cleaned)
    return cited


def submodule_roots(project: Path) -> list[Path]:
    """First-level git submodule directories declared in .gitmodules.

    Used as extra resolution bases for Rule B citation existence (not for
    Rule A scope-lock containment). A review may cite a path relative to a
    submodule's own root (e.g. `plugins/harnessloop/` when `harnessloop` is
    checked out as a submodule at <project>/harnessloop) rather than
    relative to the outer project root; without this, such citations are
    dangling relative to every existing base even though the file exists.

    Only top-level entries (no nested path segments) are honored — this is
    a minimal fix for the common case, not full recursive submodule
    resolution. Projects without a .gitmodules file get an empty list and
    behavior is unchanged.
    """
    gitmodules = project / ".gitmodules"
    if not gitmodules.is_file():
        return []
    path_re = re.compile(r"^\s*path\s*=\s*(.+?)\s*$")
    roots: list[Path] = []
    for line in gitmodules.read_text(encoding="utf-8", errors="replace").splitlines():
        match = path_re.match(line)
        if not match:
            continue
        rel = match.group(1).strip().replace("\\", "/")
        if not rel or "/" in rel:
            continue
        candidate = project / rel
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def verify_round(project: Path, round_dir: Path) -> list[dict]:
    violations: list[dict] = []
    goal_dir = round_dir.parent.parent
    bases = [project, goal_dir, round_dir]
    # Rule B only: extra resolution bases for (1) citations that use one of
    # the PATHISH_PREFIXES verbatim (setup/, state/, goals/, ...) — those
    # directories actually live under <project>/.harnessloop/, which none of
    # `bases` covers on their own — and (2) citations written relative to a
    # submodule's own root. Kept separate from `bases` so Rule A's
    # scope-lock containment check is not loosened by either addition.
    citation_bases = bases + [project / ".harnessloop"] + submodule_roots(project)

    checked_files = [
        path
        for sub in ("evidence", "reviews")
        for path in sorted((round_dir / sub).rglob("*"))
        if path.is_file()
    ]

    scope_lock = round_dir / "scope-lock.md"
    if checked_files:
        if not scope_lock.exists():
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "missing-scope-lock",
                    "detail": f"{scope_lock} does not exist but evidence/review files do",
                }
            )
        else:
            spans = extract_allowed_spans(scope_lock.read_text(encoding="utf-8"))
            if not spans:
                violations.append(
                    {
                        "round": str(round_dir),
                        "kind": "unparseable-allowed-changes",
                        "detail": f"no backtick path spans found under '## Allowed Changes' in {scope_lock}",
                    }
                )
            else:
                for file_path in checked_files:
                    allowed = any(
                        is_under(file_path, base / span)
                        for base in bases
                        for span in spans
                    )
                    if not allowed:
                        violations.append(
                            {
                                "round": str(round_dir),
                                "kind": "scope-lock-violation",
                                "detail": f"{file_path} is outside every allowed path in {scope_lock}",
                            }
                        )

    reviews_dir = round_dir / "reviews"
    if reviews_dir.is_dir():
        for review in sorted(reviews_dir.rglob("*.md")):
            for cited in pathish_citations(review.read_text(encoding="utf-8")):
                if not any((base / cited).exists() for base in citation_bases):
                    violations.append(
                        {
                            "round": str(round_dir),
                            "kind": "dangling-citation",
                            "detail": f"{review} cites `{cited}` which does not exist",
                        }
                    )

    return violations


def verify_project(project: Path) -> list[dict]:
    goals_dir = project / ".harnessloop" / "goals"
    if not goals_dir.is_dir():
        return []
    violations: list[dict] = []
    for round_dir in sorted(goals_dir.glob("*/rounds/*")):
        if round_dir.is_dir():
            violations.extend(verify_round(project, round_dir))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify mechanical Harnessloop protocol gates (scope-lock containment "
            "and citation existence). Citation spans that are regex/glob patterns, "
            "bare-domain URLs (docs.python.org/..., github.com/...), or templated "
            "paths with an angle-bracket placeholder (goals/<id>/...) are exempt "
            "automatically; a citation known to be intentional prose rather than a "
            "real reference can be exempted explicitly by putting "
            "'<!-- verify:ignore -->' on the same line or the line before it. "
            "Citations are resolved against the project root, the round's goal and "
            "round directories, the project's own .harnessloop/ directory (for "
            "citations using a PATHISH_PREFIXES prefix verbatim, e.g. "
            "setup/data-sources.md), and the root of every first-level git "
            "submodule declared in the project's .gitmodules."
        )
    )
    parser.add_argument("--project", "-p", default=".", help="Target project directory. Defaults to current directory.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"Project directory not found: {project}", file=sys.stderr)
        return 2

    violations = verify_project(project)
    if args.json:
        print(json.dumps({"project": str(project), "violations": violations}, indent=2, ensure_ascii=False))
    else:
        print(f"Harnessloop verify: {project}")
        if violations:
            for violation in violations:
                print(f"  [{violation['kind']}] {violation['detail']}")
            print(f"{len(violations)} violation(s) found.")
        else:
            print("All mechanical protocol gates passed.")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
