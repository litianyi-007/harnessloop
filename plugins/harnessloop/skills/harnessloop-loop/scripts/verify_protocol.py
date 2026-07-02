#!/usr/bin/env python3
"""Verify the mechanical subset of the Harnessloop protocol.

Judgment gates (does this evidence support acceptance?) stay with the model.
This script enforces only machine-checkable rules:

- Rule A (scope-lock containment): every file under a round's evidence/ and
  reviews/ directories must fall inside a path allowed by that round's
  scope-lock.md "Allowed Changes" section.
- Rule B (citation existence): every path cited in a round's review files
  must exist in the project.

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


def pathish_citations(markdown_text: str) -> list[str]:
    """Extract citation spans that look like file paths.

    Beyond the protocol prefixes, any slash-containing span with a file
    extension, a trailing slash, or a `..` segment is treated as a path so
    that citations of source/test files (e.g. `src/app.py`) are verified too.
    Spans with spaces, URLs, flags, and variables are ignored.
    """
    cited: list[str] = []
    for span in CODE_SPAN.findall(markdown_text):
        cleaned = span.strip().replace("\\", "/")
        if not cleaned or " " in cleaned or "://" in cleaned:
            continue
        if cleaned.startswith(("-", "$", "<")):
            continue
        if cleaned.startswith(PATHISH_PREFIXES):
            cited.append(cleaned)
            continue
        if "/" in cleaned:
            tail = cleaned.rsplit("/", 1)[-1]
            if Path(tail).suffix or cleaned.endswith("/") or ".." in cleaned:
                cited.append(cleaned)
    return cited


def verify_round(project: Path, round_dir: Path) -> list[dict]:
    violations: list[dict] = []
    goal_dir = round_dir.parent.parent
    bases = [project, goal_dir, round_dir]

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
                if not any((base / cited).exists() for base in bases):
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
    parser = argparse.ArgumentParser(description="Verify mechanical Harnessloop protocol gates.")
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
