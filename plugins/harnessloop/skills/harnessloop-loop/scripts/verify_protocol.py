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
  git submodule declared in the project's .gitmodules — including nested
  ones (e.g. `path = kernels/openclaw`), so a citation written relative to
  a submodule's own root, e.g. `plugins/foo/` when `foo` is checked out as
  a submodule at <project>/foo or <project>/kernels/foo, resolves
  correctly instead of being flagged as dangling).

  Before existence is checked, a trailing locator suffix is stripped from
  the citation: `:<line>`, `:<start>-<end>`, or `::<anchor>` (see
  `strip_locator_suffix`). Reviewers routinely cite `path/to/file.py:123`
  or `doc.md::some-anchor` — the locator addresses a position *within* an
  already-real file, it is not part of the file's path, and checking the
  literal locator-suffixed string against the filesystem always fails.
  Both the original and the stripped form are tried, in that order, so a
  citation that happens to end in something that is coincidentally not a
  locator is not silently mis-resolved.

  Every base resolution (project root, goal/round dirs, `.harnessloop/`,
  submodule roots) is *containment-checked* using canonical
  (symlink-resolved) paths on both sides, not merely a lexical `normpath`
  comparison: the candidate and the project root are each passed through
  `Path.resolve(strict=False)` before the containment test, and the
  candidate must land inside the resolved project root (see
  `_is_contained`). Critically, this canonicalization is applied to the
  *raw* joined candidate (`base / cited`, not a pre-folded
  `os.path.normpath` string): folding a citation like `link/../escape.md`
  with plain lexical `normpath` *before* resolving would erase the `link/..`
  round-trip entirely, silently discarding the very symlink hop the
  containment check exists to catch, and could land on a coincidentally
  named path elsewhere in the project instead of ever reasoning about where
  `link` actually points (T-064 MUST-FIX C: `symlink_dotdot_normpath_order`
  — `_resolve_in_project` and `submodule_roots` both used to normpath the
  join before containment-checking it; both now canonicalize the
  unfolded join directly, so `link`'s real target is resolved *first* and
  the trailing `..` is applied to that real target, not to the literal
  text). A citation containing `../` that would otherwise walk outside the
  project (e.g. `../outside/ghost.py`), a `.gitmodules` `path =` entry that
  points outside the project root, or a project-internal symlink (a
  submodule-root path itself or an explicit-base candidate) whose real
  target lives outside the project tree, is never treated as resolved —
  even if something of that name happens to exist on the host filesystem
  just outside the project tree, or something of the *same basename*
  happens to exist inside the project (TH-0008 REWORK:
  `submodule_parent_escape`; T-063 MUST-FIX 2: `symlink_containment_escape`
  — lexical `normpath` containment alone passes a symlink whose path is
  inside the project but whose target is not, and that held across both the
  base-resolution and submodule-root paths, not just one; T-064 MUST-FIX C:
  `symlink_dotdot_normpath_order` above). Resolving the project root too
  (not only the candidate) matters even absent any project-authored
  symlink: on macOS, e.g., `/tmp` is itself a symlink to `/private/tmp`, so
  a project rooted under `/tmp` would otherwise be compared against an
  unresolved parent and see spurious mismatches. A broken symlink's
  `resolve(strict=False)` does not raise — it normalizes past the point the
  target stops existing — so containment alone does not double as an
  existence check; the existing match-time re-verification (`_exists_as`,
  `broken_symlink` / `stale_index_after_delete`) still owns that job and is
  always applied in addition to, not instead of, containment.

  If a citation still does not resolve against any of the bases above
  (after locator-stripping), Rule B **does not** treat it as resolved just
  because it happens to match exactly one indexed file as a path *suffix*
  (see `build_suffix_index` / `suffix_unique_match`). It never did before
  T-064 without carrying a real risk: a suffix match, by construction,
  proves only "exactly one indexed file's path happens to end in these
  segments", never "this is the file the reviewer meant to cite" — and the
  "exactly one" universe it is judged against is itself a moving boundary
  (tracked-only, then tracked-plus-untracked-not-ignored, then a boundary
  that still missed gitignored and stale-tracked entries; see T-063
  MUST-FIX 1 and T-064 MUST-FIX A/B below) that a purely mechanical suffix
  match can never make watertight, because "the real, currently-existing
  files a reviewer could plausibly mean" is not a closed, mechanically
  enumerable set. **Decision (user-confirmed, T-064): suffix matching no
  longer participates in pass/fail at all.** A citation whose only
  potential resolution is a suffix hit is reported as `dangling-citation`
  exactly like a citation with zero hits. What the fallback still does is
  attach a *display-only hint* to that violation's `detail` when the
  suffix match is unique and its target still actually exists: something
  like `— a unique suffix match exists at <project-relative path>; if that
  is the intended file, cite it by a resolvable path or mark the line
  <!-- verify:ignore -->`. No hint is attached when the suffix has zero or
  multiple hits. The hint is counted in the `citations_suffix_hinted`
  coverage field (see `_empty_coverage`) so how much of the dangling
  surface is suffix-diagnosable is visible in coverage, exactly like
  `citations_exempt_external` makes the absolute-path exemption visible.
  This is a real behavior change, not a paper one: this fallback used to
  be able to turn a `dangling-citation` into a pass (a false negative
  whenever the suffix happened to be wrong); it no longer can, under any
  circumstance — **the false-negative surface this fallback can create is
  now exactly zero**, because it can no longer change any verdict, only
  annotate one. This is also the entirety of what this rework closes: it
  does *not* mean the underlying "what does 'genuinely exists' even mean"
  question (T-063 MUST-FIX 1, T-064 MUST-FIX A/B below) has been "solved" —
  that question determines only whether a hint is offered and how
  accurately, never whether the citation passes. The hint keeps the same
  conservative shape as the fallback always had: it requires at least two
  path segments (a single bare filename never qualifies), compares whole
  path *segments* rather than raw string suffixes (so `os.html` cannot
  match `macos.html`), and only fires when exactly one indexed file matches
  that suffix *and* the specific path that match names still actually
  exists (or, for a citation ending in `/`, is still actually a directory)
  at the moment of checking (see `suffix_unique_match` /
  `suffix_hint_target`).

  The index backing this hint is built from every file that genuinely
  exists in the project's worktree and is not gitignored — tracked *and*
  untracked-but-not-ignored (`git ls-files -z --cached --recurse-submodules`
  plus `git ls-files -z --others --exclude-standard`, the latter extended
  into nested submodules via `git submodule foreach --recursive` since
  `--others` itself has no `--recurse-submodules` mode — run from the
  project root, when the project root is itself a git working-tree top
  level) — falling back to walking the filesystem (pruning
  `NOISE_DIR_NAMES`) only when the project is not a git working-tree root or
  `git` is unavailable. "Unique" means unique among this real-worktree,
  non-ignored surface, not literally "git-tracked": an earlier rework
  narrowed the index to tracked files only, which closed the noise-pruning
  blind spot below but opened a new one — a round's own freshly-produced
  evidence/review files are untracked by construction, so a genuine
  same-suffix collision between a tracked file and such a fresh untracked
  one was invisible to the ambiguity check, making a hint fire as if the
  match were unique when a real same-suffix file was invisible to it
  (T-063 MUST-FIX 1: `untracked_pseudo_unique` — under the pre-T-064
  resolving fallback this was a false-negative risk; under the current
  hint-only fallback it is a hint-accuracy risk only). `git ls-files
  --cached` additionally lists a tracked path the worktree no longer has —
  deleted from disk but not yet `git rm`ed from the index — and, unlike a
  broken symlink (which still has a real dirent, just a dangling target),
  such an entry has nothing at all on disk; before T-064 it still
  participated in uniqueness, so a genuinely-unique real file could be
  wrongly reported as ambiguous by a ghost that is not "real" by any
  definition this rule uses elsewhere (T-064 MUST-FIX B:
  `stale_tracked_ghost_ambiguity`). The index build now drops any entry
  that does not `os.path.lexists` on disk (a check that, unlike
  `exists()`, still keeps a broken symlink — its dirent is real even though
  its target is not — so this does not regress `broken_symlink` /
  `stale_index_after_delete` above). A gitignored file colliding with a
  tracked/untracked file's suffix is still invisible to the index either
  way (that generated-output exclusion is the point of `--exclude-standard`)
  — a real, currently-existing, non-tracked file that a hint's "exactly
  one" count simply never sees (T-064 MUST-FIX A:
  `ignored_pseudo_unique_hint` — same shape as MUST-FIX 1, but the boundary
  moved from "untracked" to "ignored"; under the pre-T-064 resolving
  fallback this made the fallback resolve a citation that a `git add -f`
  of the very same on-disk file would immediately have turned dangling —
  a false negative that tracked the index boundary wherever it was drawn,
  not any one fixed edge case; under the current hint-only fallback it can
  only make a hint fire, or fire inaccurately, never change pass/fail). And
  — unlike the prior walk-based index — a real, non-ignored source
  directory that happens to share a name with an entry in `NOISE_DIR_NAMES`
  (e.g. a project that genuinely has a source directory named `build/`) is
  indexed and can correctly participate in an ambiguity instead of being
  silently pruned out of consideration (TH-0008 REWORK:
  `noise_pruned_ambiguity`). The walk-based fallback, when it is used, still
  prunes `NOISE_DIR_NAMES` and is subject to the same pruning blind spot it
  always was.

  A citation ending in `/` names a directory, not a file: it only resolves
  when the matched filesystem entry is actually a directory (`is_dir()`),
  never when it merely shares a path with an existing file of the same
  name (TH-0008 REWORK: `trailing_slash_file` — `pkg/real.md/` must not
  resolve against the file `pkg/real.md`). This directory semantics is
  applied uniformly to explicit-base resolution and to the suffix
  fallback.

  A citation that starts with `~/` (home-relative), `/` (POSIX filesystem
  absolute), or a Windows-style absolute path — a drive letter
  (`C:/...`, written `C:\\...` before backslashes are normalized to `/`)
  or a UNC path (`\\\\server\\share\\...`, normalized to `//server/share/...`,
  which already starts with `/` and so falls under the same check) — is
  exempt from existence checking entirely, for the same reason a
  `scheme://` URL is exempt: it names a location outside the project tree,
  and Rule B has no project-declared base to resolve it against —
  inventing one (e.g. treating `/` as the OS root, or `C:/` as a Windows
  drive root) would let the check silently walk outside the project, or
  behave differently depending on which OS the check happens to run on.
  This is a real, known gap: a review that cites a path inside an external
  design wiki kept outside this project (e.g. under a user's
  `~/.llm-wiki/...`) is never verified, because harnessloop has no way to
  know where — or whether — that external tree exists. Closing that gap
  requires a project to declare an additional resolution base for such
  external stores; that is a separate, project-level protocol decision and
  is out of scope here. Unlike before, this exemption is no longer silent:
  every span skipped for this reason is counted in the `coverage` dict's
  `citations_exempt_external` field (see `_empty_coverage`), so a run's
  coverage line makes visible how much of its citation surface was waved
  through unchecked rather than hiding that number entirely.

  Two honesty notes on what this rule cannot mechanically guarantee even
  after the above:

  - Case sensitivity of the final existence check is whatever the host
    filesystem gives it, not a Rule B decision: `Path.exists()` /
    `is_dir()` are case-sensitive on a typical Linux filesystem and
    case-insensitive (but case-preserving) by default on macOS and
    Windows. A citation with the wrong case for a real file can therefore
    pass or fail depending on which machine runs the check — this rule
    does not normalize case itself and cannot make that determinism
    project-wide.
  - The suffix-unique *hint* (T-064: no longer a resolution path, see
    above) proves only "exactly one indexed file has this suffix", never
    "this is the file the reviewer meant to cite". A reviewer who mistypes
    `mistyped/config.yaml` when they meant a different file will still get
    a hint pointing at `vendor/mistyped/config.yaml` if that happens to be
    the tree's only file ending in `mistyped/config.yaml` — the algorithm
    cannot distinguish a lucky coincidental match from the intended one.
    Before T-064 this was a pass/fail problem (a coincidental match turned
    a genuinely wrong citation green); since the downgrade it is a
    hint-accuracy problem only — the citation is `dangling-citation`
    either way, and the hint can at most point at the wrong file or fail
    to fire. This residual imprecision is inherent to any suffix-based
    matching and is not something this rework (or any purely mechanical
    suffix match) can close; it is recorded here rather than "fixed"
    because the only ways to close it further would be dropping the hint
    entirely (losing a genuinely useful diagnostic for the common case) or
    requiring citations to be written unambiguously (a review-authoring
    discipline change, not a Rule B one). The same applies, for the same
    reason, to T-064 MUST-FIX A (`ignored_pseudo_unique_hint`, a gitignored
    same-suffix file invisible to the hint's uniqueness count) and to
    whatever future boundary case resembles it: moving the index boundary
    again would change which citations get a hint and how accurate it is,
    never whether they pass.

- B2a review declaration (see `check_review_declaration`): a round's
  `decision.md`, when present, must declare `Review:` (a project-contained
  path, or `none — <non-empty reason>`), `Reviewer:`, and `Review verdict:`
  (`Review digest:` is optional). This is deliberately the "account for
  it, do not grow the tree" half of what the T-066 handoff
  (`.hopper/handoffs/T-066-output.md` §4) calls B2a: the declared review
  file's own prose is never scanned, and it is never folded into Rule A's
  `rule_a_files` or Rule B's `rule_b_files` / `citations_checked` counters
  — those stay exactly what they were before this rule existed. See
  `check_review_declaration`'s docstring for the precise checks and
  `harnessloop-loop/SKILL.md`'s Mechanical Gate Boundary for what this
  still does not decide (whether the review's content is any good, or
  whether a `none — <reason>` reason is adequate).

Exit codes: 0 = pass, 1 = violations found, 2 = usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
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

# A Windows drive-letter absolute path, e.g. `C:/Users/x` -- checked after
# `pathish_citations` has already normalized backslashes to `/`, so the
# original `C:\Users\x` form is matched by this too. See
# `_looks_like_out_of_project`.
WINDOWS_DRIVE_ABS_RE = re.compile(r"^[A-Za-z]:/")

# Trailing locator suffixes stripped before existence checking: `::anchor`
# (checked first, since it is the more specific shape) and `:line` /
# `:start-end`. See `strip_locator_suffix`.
ANCHOR_SUFFIX_RE = re.compile(r"::[^:]+$")
LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")

# B2a review-declaration gate (see `check_review_declaration`): `Review:
# none — <reason>` — the "none" token, an optional dash-like separator
# (hyphen, en dash, or em dash), and whatever remains is the reason to be
# checked for non-emptiness. `re.match` anchors at the start only, so a
# `Review:` value that merely *starts* with "none" as a path segment (there
# is no such real path shape, but be precise regardless) still requires a
# word boundary after it.
REVIEW_NONE_RE = re.compile(r"(?i)^none\b\s*(?:[-–—]+\s*)?(.*)$")

# A `Review digest:` value: exactly 64 hex characters (sha256), so a
# case-preserved comparison against a computed hexdigest is meaningful.
REVIEW_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# Noise directories excluded from the Rule B suffix-unique fallback index
# (`build_suffix_index`): build output, vendored/installed dependencies, and
# VCS internals are never what a review is citing, and including them would
# both slow the index and manufacture spurious "unique" matches inside
# generated trees that happen to mirror source filenames.
NOISE_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "dist",
        "build",
        "bin",
        "obj",
        ".venv",
        "__pycache__",
        ".artifacts",
        "coverage",
    }
)


def norm(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def is_under(child: Path, parent: Path) -> bool:
    child_s, parent_s = norm(child), norm(parent)
    return child_s == parent_s or child_s.startswith(parent_s + os.sep)


def _canonical(path: Path) -> Path:
    """Resolve `path` to its canonical (symlink-following) form.

    `strict=False` normalizes past a broken symlink or a nonexistent
    component instead of raising — existence is a separate concern, owned
    by `_exists_as` at the point a match is actually accepted, not by this
    resolution step (T-063 MUST-FIX 2: canonical containment and match-time
    existence re-verification must not be conflated with each other).
    """
    return path.resolve(strict=False)


def _is_contained(candidate: Path, project: Path) -> bool:
    """True if `candidate` lands inside `project` under *canonical*
    (symlink-resolved) comparison of both sides.

    Lexical `normpath` containment (`is_under` alone) is not enough: a
    project-internal symlink whose path is inside the project but whose
    target is not (e.g. `<project>/link -> /outside`, or a `.gitmodules`
    `path =` entry naming such a symlink) passes a lexical check while
    actually resolving outside the project entirely (T-063 MUST-FIX 2:
    `symlink_containment_escape`). `project` itself is resolved too, not
    just `candidate` — on macOS `/tmp` is a symlink to `/private/tmp`, so a
    project rooted there would otherwise be compared against an unresolved
    parent and see a spurious mismatch (or, worse, a spurious escape) for
    every candidate. Used by every containment check that guards Rule B
    citation resolution: `_resolve_in_project` (explicit-base and suffix
    resolution), `submodule_roots` (`.gitmodules` `path =` acceptance), and
    `suffix_unique_match` (the unique-hit's specific path) — all three must
    share this one definition so a symlink escape cannot slip through
    whichever path is not updated.
    """
    return is_under(_canonical(candidate), _canonical(project))


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


def _looks_like_out_of_project(cleaned: str) -> bool:
    """True if the span is home-relative (``~/...``), POSIX filesystem-
    absolute (``/...``, which also covers a UNC path once
    `pathish_citations` has normalized its backslashes to slashes, e.g.
    ``//server/share/...``), or Windows drive-absolute (``C:/...``).

    These name a location outside the project tree, not a project-relative
    citation. Rule B has no project-declared base to resolve such a path
    against, so — exactly like a `scheme://` URL — it is exempt rather than
    checked (and rather than mis-resolved: `Path(base) / "/abs/x"` silently
    discards `base` and re-checks the literal absolute path against the real
    filesystem, which is not what this rule is verifying). See the module
    docstring for the known-uncovered case this leaves (e.g. an external
    `~/.llm-wiki/...` design-doc store) and for `citations_exempt_external`,
    the coverage field that now counts how many spans this exemption
    swallowed instead of doing so silently.
    """
    return (
        cleaned.startswith("~/")
        or cleaned.startswith("/")
        or bool(WINDOWS_DRIVE_ABS_RE.match(cleaned))
    )


def strip_locator_suffix(cleaned: str) -> str:
    """Strip a trailing `::<anchor>`, `:<line>`, or `:<start>-<end>` locator.

    Reviewers commonly cite a position *within* a file rather than just the
    file itself: `plugins/foo/scripts/check_setup.py:123` (a line number),
    `docs/x.md:10-20` (a line range), or `.hopper/tasks/foo.md::root` (a
    named anchor). The locator is not part of the path — checking the
    literal locator-suffixed string against the filesystem always fails
    even when the file plainly exists. The `::anchor` form is tried first
    since it is the more specific shape (and would otherwise be partially
    consumed by the line-number pattern if the anchor itself looked
    numeric). Returns `cleaned` unchanged if neither suffix is present.
    """
    match = ANCHOR_SUFFIX_RE.search(cleaned)
    if match:
        return cleaned[: match.start()]
    match = LINE_SUFFIX_RE.search(cleaned)
    if match:
        return cleaned[: match.start()]
    return cleaned


def pathish_citations(markdown_text: str) -> tuple[list[str], int, int, int, bool]:
    """Extract citation spans that look like file paths.

    Beyond the protocol prefixes, any slash-containing span with a file
    extension, a trailing slash, or a `..` segment is treated as a path so
    that citations of source/test files (e.g. `src/app.py`) are verified too.
    Spans with spaces, URLs, flags, and variables are ignored, as are
    regex/glob patterns (`_looks_like_pattern`), bare-domain URLs
    (`_looks_like_bare_domain`), templated paths containing an
    angle-bracket placeholder (`_looks_like_placeholder`, e.g.
    `goals/<id>/data-contract.md`), and home-relative, POSIX-absolute, or
    Windows-absolute paths naming a location outside the project
    (`_looks_like_out_of_project`, e.g. `~/.llm-wiki/x.md`, `/etc/hosts`, or
    `C:/Users/x`). A line carrying (or immediately following a line that
    carries) the `<!-- verify:ignore -->` marker has all of its citations
    skipped — see module docstring.

    Two ignore-marker coverage fields close a real blind spot (T-066 §1
    judgment criterion 2, "ignore-marker misuse must not go unmonitored"):
    before this, the ignore branch below `continue`d without counting
    anything, so a review could sprinkle `<!-- verify:ignore -->` over
    genuinely dangling citations and empty Rule B out while `coverage` /
    exit code / `--json` all kept reporting clean — the exact same shape of
    silent exemption `citations_exempt_external` closed for the `~/...`
    absolute-path gap, just for a different escape hatch. `ignored_explicit`
    counts every backtick span found on a line the marker exempts (deliberately
    every span on that line, not only ones that would otherwise have looked
    pathish — the marker is documented to exempt "every citation on it", and
    a conservative over-count here is the correct bias for a misuse monitor).
    `has_ignore_marker` is a whole-file boolean (the marker occurs anywhere in
    `markdown_text`), which the caller accumulates into the file-level
    `review_files_with_ignore` coverage field rather than per-span.

    `shape_dropped` counts a third, previously-invisible exit: a span that
    contains `/` (so it is clearly meant as a path) but whose tail has no
    file extension, no trailing `/`, and no `..` segment — e.g.
    `@@wiki/kernel` or `src/pkgdir` — falls through the shape branch below
    without ever being appended to `cited`, and before this field existed
    that drop was silent. This is also the cheapest way to turn a real
    dangling citation green: delete the file extension from an already-red
    span and it vanishes from every coverage field, not just this one.

    Returns `(cited, exempt_external, ignored_explicit, shape_dropped,
    has_ignore_marker)`: `cited` is the list of spans to existence-check,
    `exempt_external` is a count of spans skipped specifically by
    `_looks_like_out_of_project` (not any other exemption) — the caller
    accumulates this into the `citations_exempt_external` coverage field —
    and the remaining three back `citations_ignored_explicit`,
    `citations_shape_dropped`, and `review_files_with_ignore` respectively
    (see `_empty_coverage`).
    """
    cited: list[str] = []
    exempt_external = 0
    ignored_explicit = 0
    shape_dropped = 0
    lines = markdown_text.splitlines()
    for i, line in enumerate(lines):
        if IGNORE_MARKER in line or (i > 0 and IGNORE_MARKER in lines[i - 1]):
            ignored_explicit += len(CODE_SPAN.findall(line))
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
            if _looks_like_out_of_project(cleaned):
                exempt_external += 1
                continue
            if cleaned.startswith(PATHISH_PREFIXES):
                cited.append(cleaned)
                continue
            if "/" in cleaned:
                tail = cleaned.rsplit("/", 1)[-1]
                if Path(tail).suffix or cleaned.endswith("/") or ".." in cleaned:
                    cited.append(cleaned)
                else:
                    shape_dropped += 1
    return cited, exempt_external, ignored_explicit, shape_dropped, IGNORE_MARKER in markdown_text


def submodule_roots(project: Path) -> list[Path]:
    """Every git submodule directory declared in .gitmodules, at any depth.

    Used as extra resolution bases for Rule B citation existence (not for
    Rule A scope-lock containment). A review may cite a path relative to a
    submodule's own root (e.g. `plugins/harnessloop/` when `harnessloop` is
    checked out as a submodule at <project>/harnessloop) rather than
    relative to the outer project root; without this, such citations are
    dangling relative to every existing base even though the file exists.

    `.gitmodules` `path =` values are honored verbatim, including nested
    ones (e.g. `path = kernels/openclaw`) — a submodule need not be
    checked out directly under the project root. Projects without a
    .gitmodules file get an empty list and behavior is unchanged.

    A `path =` value is *canonical-containment-checked* before being
    accepted: if it does not resolve inside `project` under symlink-following
    comparison (`_is_contained`), it is dropped rather than followed.
    `.gitmodules` is ordinary tracked text a review (or an adversarial one)
    could contain a `path = ../outside` entry, and without this check a
    sibling directory outside the project — reachable on the host filesystem
    but not part of it — would become a citation resolution base, letting an
    otherwise-dangling citation resolve against something outside the
    project (TH-0008 REWORK: `submodule_parent_escape`). A lexical-only
    check is not sufficient here either: `path = link` where
    `<project>/link` is itself a symlink to somewhere outside the project
    passes a lexical `normpath` containment test (the symlink's own path is
    inside the project) while its target is not (T-063 MUST-FIX 2:
    `symlink_containment_escape`) — `_is_contained` resolves the symlink
    before comparing, so this is rejected too. Containment is checked
    against the *raw*, unfolded `project / rel` join, not a
    `os.path.normpath`-collapsed copy of it: a `path = smod/../mod` entry
    where `smod` is itself a project-internal symlink to somewhere outside
    the project would have its `smod/..` lexically erased by `normpath`
    *before* the symlink is ever resolved, landing containment-checked on
    the lexical `project/mod` (which passes, since it never leaves the
    project textually) while `candidate.is_dir()` below — which does follow
    the symlink via the real filesystem — reports the actual, escaping
    `smod/../mod` target as a valid directory; the two checks would then be
    reasoning about two different paths and the escape slips through (T-064
    MUST-FIX C: `symlink_dotdot_normpath_order`). Checking containment on
    the same unfolded `candidate` that `is_dir()` below is evaluated against
    closes that gap: `Path.resolve()` follows `smod` to its real target
    first and applies the trailing `..` to *that*, so containment and
    directory-check agree on what is actually being accepted.
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
        if not rel:
            continue
        candidate = project / rel
        if not _is_contained(candidate, project):
            continue
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def _git_tracked_index(project: Path) -> dict[str, list[tuple[str, ...]]] | None:
    """Git worktree-file index for `build_suffix_index`, or `None` if
    `project` is not itself a git working-tree root (or `git` is
    unavailable).

    Only engages when `project` *is* the git top level — not merely inside
    one — so a scratch directory nested under some ancestor repository
    (e.g. a test fixture created under this repo's own working tree without
    being `git add`ed) correctly falls back to the walk-based index instead
    of silently seeing zero tracked files and treating every suffix lookup
    as absent.

    The uniqueness universe is every file that genuinely exists in the
    worktree and is not gitignored — tracked *and* untracked-but-not-ignored
    — not merely `git ls-files`'s tracked set. `git ls-files -z --cached
    --recurse-submodules` supplies the tracked half (including nested
    submodules, any depth); `git ls-files -z --others --exclude-standard`
    supplies untracked-but-not-ignored files in the top-level project (`git`
    has no `--recurse-submodules` support for `--others` — see `git
    help ls-files` — so nested submodules' own untracked files are collected
    separately via `git submodule foreach --recursive`, prefixed with each
    submodule's path). Restricting to tracked files alone (TH-0008 REWORK
    original fix) traded one false-negative for another: a round's just-produced
    evidence/review files are untracked by construction (nothing has `git
    add`ed them yet), so a genuine same-suffix collision between a tracked
    file and such a fresh untracked one was invisible to the ambiguity check
    and a citation that should have been flagged as multiply-resolvable
    instead looked uniquely resolved (T-063 MUST-FIX 1:
    `untracked_pseudo_unique`). Gitignored output (`node_modules/`, `dist/`,
    `build/` artifacts, `.venv/`, ...) is still excluded by `--exclude-standard`,
    so this keeps the benefit of not needing a hardcoded noise-directory
    denylist (see module docstring: "unique" now means unique among every
    real, non-ignored file in the worktree, not literally "git-tracked" nor
    the whole tree including ignored output).

    `git ls-files --cached` lists a tracked path exactly as the index last
    recorded it, independent of whether that path still exists on disk: a
    file deleted from the worktree (but not yet `git rm`ed, or `git rm
    --cached`ed) is still listed. Such a ghost entry is not "real" by any
    definition this module uses elsewhere in the index (it is not even a
    broken symlink — there is no dirent there at all) yet, before T-064, it
    still participated in the uniqueness count, so a genuinely unique real
    file sharing its suffix could be wrongly reported as ambiguous (T-064
    MUST-FIX B: `stale_tracked_ghost_ambiguity`). Each entry (from any of
    the three sources above) is now dropped unless `os.path.lexists` is
    true for it — `lexists` rather than `exists` deliberately, so a broken
    symlink (real dirent, dangling target) is still indexed and still
    re-verified at match time by `suffix_unique_match` / `suffix_hint_target`
    exactly as before; only an entry with *nothing at all* on disk is
    excluded here.
    """
    try:
        toplevel = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if toplevel.returncode != 0:
        return None
    top = toplevel.stdout.strip()
    if not top:
        return None
    try:
        if Path(top).resolve() != project.resolve():
            return None
    except OSError:
        return None

    try:
        tracked = subprocess.run(
            ["git", "-C", str(project), "ls-files", "-z", "--cached", "--recurse-submodules"],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if tracked.returncode != 0:
        return None

    raw_entries: list[bytes] = [seg for seg in tracked.stdout.split(b"\0") if seg]

    try:
        untracked = subprocess.run(
            ["git", "-C", str(project), "ls-files", "-z", "--others", "--exclude-standard"],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        untracked = None
    if untracked is not None and untracked.returncode == 0:
        raw_entries.extend(seg for seg in untracked.stdout.split(b"\0") if seg)

    # Nested submodules' own untracked-but-not-ignored files: `--others` has no
    # `--recurse-submodules` mode, so shell out to `submodule foreach --recursive`
    # and run the same lookup inside each, prefixing with $displaypath (the
    # submodule's path relative to `project`). A read loop keyed on NUL, not
    # newline, keeps this safe for filenames containing embedded newlines, and
    # `printf ... \0` re-delimits with NUL so the outer split below still works.
    try:
        nested = subprocess.run(
            [
                "git", "-C", str(project), "submodule", "foreach", "--recursive", "-q",
                'git ls-files -z --others --exclude-standard | '
                'while IFS= read -r -d "" f; do printf "%s/%s\\0" "$displaypath" "$f"; done',
            ],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        nested = None
    if nested is not None and nested.returncode == 0:
        raw_entries.extend(seg for seg in nested.stdout.split(b"\0") if seg)

    index: dict[str, list[tuple[str, ...]]] = {}
    seen: set[str] = set()
    for raw in raw_entries:
        try:
            rel = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if rel in seen:
            continue
        seen.add(rel)
        parts = tuple(p for p in rel.split("/") if p)
        if not parts:
            continue
        if not os.path.lexists(project.joinpath(*parts)):
            # T-064 MUST-FIX B: a tracked-but-deleted-from-worktree entry
            # (or, in principle, any source above naming a path with
            # nothing at all on disk) must not participate in the
            # uniqueness count. `lexists` (not `exists`) so a broken
            # symlink is still indexed -- see docstring.
            continue
        index.setdefault(parts[-1], []).append(parts)
    return index


def build_suffix_index(project: Path) -> dict[str, list[tuple[str, ...]]]:
    """Index files under `project` by basename, once per run.

    Backs the Rule B suffix-unique fallback (`suffix_unique_match`): after a
    citation fails to resolve against every explicit base (project root,
    goal/round dirs, `.harnessloop/`, submodule roots — with and without a
    locator suffix stripped), it is tried once more as a path *suffix*
    against this index. Building it once per `verify_project` call (rather
    than walking the tree per citation) keeps that fallback from turning an
    O(citations) check into an O(citations * tree size) one.

    Primary source is the tracked-plus-untracked-not-ignored worktree index
    (`_git_tracked_index`, see its docstring), used whenever `project` is
    itself a git working-tree root. Falls back to
    walking the filesystem directly — `os.walk` with in-place `dirnames`
    pruning of `NOISE_DIR_NAMES` (`.git`, `node_modules`, build output,
    venvs, ...), not `Path.rglob("*")`, since a project with vendored
    dependencies can have orders of magnitude more files inside those
    directories than in the rest of the tree — when `project` is not a git
    working-tree root or `git` is unavailable. Each entry maps a basename to
    the list of path-segment tuples (relative to `project`) of every
    indexed file with that basename. Note that an indexed entry is not, by
    itself, proof the file still exists: `suffix_unique_match` re-verifies
    the specific matched path against the real filesystem before accepting
    it (see its docstring).
    """
    tracked = _git_tracked_index(project)
    if tracked is not None:
        return tracked

    index: dict[str, list[tuple[str, ...]]] = {}
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = [d for d in dirnames if d not in NOISE_DIR_NAMES]
        rel_dir = Path(dirpath).relative_to(project)
        dir_parts = () if str(rel_dir) == "." else rel_dir.parts
        for filename in filenames:
            parts = dir_parts + (filename,)
            index.setdefault(filename, []).append(parts)
    return index


def _exists_as(path: Path, want_dir: bool) -> bool:
    """Existence check honoring trailing-slash directory semantics.

    A citation ending in `/` names a directory: it must resolve to an
    actual directory (`is_dir()`), not merely to any filesystem entry of
    the same name. Without this, `pkg/real.md/` would resolve against the
    *file* `pkg/real.md` via plain `exists()` (TH-0008 REWORK:
    `trailing_slash_file`).
    """
    if want_dir:
        return path.is_dir()
    return path.exists()


def suffix_hint_target(
    cleaned: str, index: dict[str, list[tuple[str, ...]]], project: Path
) -> Path | None:
    """Return the specific project-relative path `cleaned` matches as a
    unique, still-real path *suffix*, or `None` if it does not.

    T-064: this is a *display-only hint*, not a resolution path — see the
    module docstring's "Suffix hint" section. It is a fallback for a
    citation that is correct but written relative to none of the explicit
    bases — e.g. `harnessloop-setup/SKILL.md` for a file that actually
    lives at `plugins/harnessloop/skills/harnessloop-setup/SKILL.md` — but
    `verify_round` never treats finding one as a pass; it only attaches the
    returned path to the `dangling-citation` violation's `detail` as a
    hint, and only when this returns non-`None`. `suffix_unique_match`
    (below) is `suffix_hint_target(...) is not None`, kept as a separate
    boolean-returning name for callers (and existing tests) that only need
    the predicate. Deliberately conservative in four ways, each guarding a
    specific false-negative-in-what-the-hint-implies risk:

    - Comparison is by path *segment*, not raw string suffix — `os.html`
      must not match `.../macos.html` (string `endswith` would).
    - At least two path segments are required — a single bare filename
      (`agents/`-style single component citations, or a bare basename like
      `verify_protocol.py`) is the shape most likely to be a typo and least
      likely to disambiguate anything, so it never qualifies here; it is
      still checked (and can still fail) against the explicit bases above.
    - The match must be *unique* across the index — 0 hits is still
      dangling (no such file), and >=2 hits is also still dangling (an
      ambiguous suffix is not a resolved citation; picking one of several
      candidates would silently paper over which file was meant).
    - The unique match's specific path is re-checked against the real
      filesystem before being accepted — `is_dir()` if `cleaned` ends in
      `/`, otherwise `exists()` (`_exists_as`) — rather than trusted purely
      because the index once recorded it. The index can otherwise be
      stale (a file the index recorded can be deleted between
      `build_suffix_index` and this call — TH-0008 REWORK:
      `stale_index_after_delete`) or, when it was built by walking the
      filesystem, can contain a broken symlink that `os.walk` lists in
      `filenames` without ever following it (TH-0008 REWORK:
      `broken_symlink`); either way, treating the indexed entry as
      sufficient proof of existence would accept a citation to something
      that, right now, does not resolve to a real file.

    A fifth guard, added in T-063 MUST-FIX 2 (`symlink_containment_escape`):
    the unique match's specific path is also *canonical-containment-checked*
    (`_is_contained`) against `project` before being accepted, not merely
    assumed safe because it came from the index. The index is built from
    `git ls-files`, which lists a tracked symlink like any other tracked
    entry — a citation ending in, say, `pkg/external.md` where
    `<project>/deep/pkg/external.md` is itself a symlink pointing at a real
    file *outside* the project would otherwise pass the existence check
    (the symlink's target genuinely exists) while resolving to something
    the project does not control. Containment is checked first and
    existence second, deliberately not combined into one step: a broken
    symlink still passes containment (its lexical path is inside the
    project even though nothing exists at the far end) and is correctly
    caught by the existence check that follows, exactly as before.
    """
    parts = tuple(p for p in cleaned.split("/") if p)
    if len(parts) < 2:
        return None
    candidates = index.get(parts[-1], [])
    matches = [c for c in candidates if len(c) >= len(parts) and c[-len(parts) :] == parts]
    if len(matches) != 1:
        return None
    match_path = project.joinpath(*matches[0])
    if not _is_contained(match_path, project):
        return None
    if not _exists_as(match_path, cleaned.endswith("/")):
        return None
    return match_path


def suffix_unique_match(
    cleaned: str, index: dict[str, list[tuple[str, ...]]], project: Path
) -> bool:
    """True if `cleaned` matches exactly one indexed file as a path
    *suffix*, and that specific file still actually exists (see
    `suffix_hint_target`, which this delegates to). T-064: a `True` result
    means only "a hint can be offered", never "this citation resolves" —
    see the module docstring."""
    return suffix_hint_target(cleaned, index, project) is not None


def _resolve_in_project(base: Path, cited: str, project: Path) -> Path | None:
    """Join `base` and `cited` and return the result only if it stays within
    `project` under *canonical* containment — otherwise `None`.

    Guards against a citation containing `../` segments walking the join
    outside the project tree, where `Path.exists()` would silently consult
    the real host filesystem for an unrelated path that happens to share a
    name with something the review meant to cite (TH-0008 REWORK:
    `submodule_parent_escape` — the same containment discipline
    `submodule_roots` applies to `.gitmodules` entries, applied here to
    every citation resolution). Lexical `normpath` containment alone is not
    enough for a project-internal symlink whose target lives outside the
    project (e.g. `<project>/link -> /outside`, cited as `link/pkg/x.py`):
    the joined candidate's lexical *path* is inside the project even though
    what it resolves to is not (T-063 MUST-FIX 2:
    `symlink_containment_escape`) — `_is_contained` resolves both sides
    before comparing, so this is rejected too.

    The join is deliberately **not** pre-folded with `os.path.normpath`
    before that containment check (T-064 MUST-FIX C:
    `symlink_dotdot_normpath_order`): `normpath` collapses a `link/..`
    round-trip purely lexically, with no awareness that `link` might be a
    symlink — so a citation like `link/../escape.md`, where `link` is a
    project-internal symlink pointing *outside* the project, would have its
    `link/..` erased before `_is_contained` ever sees it, leaving a bare
    `escape.md` that trivially resolves inside the project (and, if a
    coincidentally same-named file exists there, silently accepts *that*
    file — not the one the citation's traversal actually names). Passing
    the raw, unfolded `base / cited` join to `_is_contained` instead means
    `Path.resolve()` follows `link` to its real target *first*, then
    applies the trailing `..` to that real target — exactly what the
    filesystem itself would do — so an escape through a symlink-then-`..`
    is caught the same way a plain escaping symlink already was. The
    returned `candidate` is still the lexical (non-canonical, unfolded)
    join, not the resolved path: callers only need it for the subsequent
    `_exists_as` check, which itself follows symlinks via `Path.exists()` /
    `is_dir()`.
    """
    candidate = base / cited
    if not _is_contained(candidate, project):
        return None
    return candidate


def _any_base_resolves(cited: str, bases: list[Path], project: Path, want_dir: bool) -> bool:
    """True if `cited` resolves (containment-checked, directory-semantics-
    aware) against any of `bases`."""
    for base in bases:
        resolved = _resolve_in_project(base, cited, project)
        if resolved is not None and _exists_as(resolved, want_dir):
            return True
    return False


def parse_review_fields(decision_text: str) -> dict[str, str | None]:
    """Extract the four B2a review-declaration fields from a decision.md.

    Same narrow convention as the existing Verdict/Residuals (E4) check:
    a case-insensitive `- <label>:` line prefix, matched against
    `.strip().lower()`, first occurrence wins, no prose parsing anywhere
    else in the file is consulted. A key's value is `None` when the field
    was never written at all — this is how `check_review_declaration`
    tells "field absent" (a `review-declaration-missing` violation) apart
    from "field present but its value turns out to be invalid" (a
    different, more specific violation kind).

    `- Review verdict:` and `- Review digest:` are checked before
    `- Review:` for readability, but the ordering does not affect
    correctness: `"- review verdict:".startswith("- review:")` and
    `"- review digest:".startswith("- review:")` are both false (the
    character right after "review" differs: a space, not a colon), so
    none of these four prefixes can ever shadow another.
    """
    fields: dict[str, str | None] = {
        "review": None,
        "reviewer": None,
        "review_verdict": None,
        "review_digest": None,
    }
    for line in decision_text.splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if fields["review_verdict"] is None and low.startswith("- review verdict:"):
            fields["review_verdict"] = stripped.split(":", 1)[1].strip()
        elif fields["review_digest"] is None and low.startswith("- review digest:"):
            fields["review_digest"] = stripped.split(":", 1)[1].strip()
        elif fields["reviewer"] is None and low.startswith("- reviewer:"):
            fields["reviewer"] = stripped.split(":", 1)[1].strip()
        elif fields["review"] is None and low.startswith("- review:"):
            fields["review"] = stripped.split(":", 1)[1].strip()
    return fields


def check_review_declaration(
    round_dir: Path, project: Path, decision_text: str
) -> tuple[list[dict], dict]:
    """B2a mechanical gate: account for review, do not grow the tree.

    Per the T-066 handoff (`.hopper/handoffs/T-066-output.md` §4, "B2a: 只
    入账、不入树"), `decision.md` must declare:

    - `Review: <project-contained path>` or `Review: none — <reason>`
    - `Reviewer: <identity>`
    - `Review verdict: <enum>` (this rule does not constrain the enum's
      vocabulary — see `decision-template.md` and `harnessloop-loop/
      SKILL.md` for the recommended values; a machine-checkable enum
      dictionary is not this rule's job)
    - `Review digest: <sha256>` (optional)

    This function checks only:

    1. That all three required fields are present at all (same-file
       enumeration, exactly like E4 above — never a violation for a round
       that predates this rule, since "absent" and "written but empty" are
       distinguished by `parse_review_fields`).
    2. When `Review:` names a path (i.e. it is not `none — ...`):
       canonical project containment — reusing `_is_contained`, the same
       symlink-safe, both-sides-resolved check `_resolve_in_project` and
       `submodule_roots` use for Rule B, so a symlink escape is caught
       exactly the same way here (T-063 MUST-FIX 2's `symlink_containment_escape`
       shape) — on-disk existence, and that the leaf is a plain file: not a
       directory, and not a symlink even when the symlink's *target*
       legitimately resolves inside the project. The spec calls for "an
       ordinary, non-symlink file", not merely "nothing that escapes the
       project" — those are different properties, and this checks the
       stricter one.
    3. When `Review:` is `none — <reason>`: only that `<reason>` is
       non-empty (or non-whitespace) after the `none` token and its
       separator are stripped. This is a presence check, not a judgment
       of the reason's quality — a machine cannot tell a genuine reason
       from a placeholder string, and this rule does not pretend to.
    4. When `Review digest:` is declared (and `Review:` names a path that
       passed check 2): the file's sha256 matches, byte for byte.

    What this deliberately never does — the "not into treesourcing"
    half of the boundary: read the review file's own prose (no citation
    extraction, no Rule B run against it), or fold this round into the
    `rule_a_files` / `rule_b_files` / `citations_checked` coverage
    counters Rule A/B own. A declared review file, however dense with its
    own dangling-looking citations, produces zero `dangling-citation`
    violations from this rule — B2b (pilot-gated, not yet built) is where
    that would happen, deliberately not here.

    Returns `(violations, review_state)`, where `review_state` has keys
    `missing_fields` (list[str], the human-readable labels of any required
    field absent from `decision_text`), `mode` (`"path"` | `"none"` |
    `None` when `Review:` itself was never written), and `digest_declared`
    (bool) — the caller (`verify_round`) folds these into the module's
    `coverage` dict; this function stays a pure, coverage-agnostic helper
    so it can be unit-tested (and mutation-tested) directly against a
    decision.md string without needing a round directory on disk for every
    case.
    """
    violations: list[dict] = []
    fields = parse_review_fields(decision_text)
    decision_path = round_dir / "decision.md"

    required = (("Review", "review"), ("Reviewer", "reviewer"), ("Review verdict", "review_verdict"))
    missing_fields = [label for label, key in required if fields[key] is None]
    review_state = {
        "missing_fields": missing_fields,
        "mode": None,
        "digest_declared": fields["review_digest"] is not None,
    }
    if missing_fields:
        violations.append(
            {
                "round": str(round_dir),
                "kind": "review-declaration-missing",
                "detail": (
                    f"{decision_path} is missing required review-declaration field(s): "
                    f"{', '.join(missing_fields)} (B2a: decision.md must declare Review, "
                    "Reviewer, and Review verdict — see harnessloop-loop/SKILL.md Mechanical "
                    "Gate Boundary)"
                ),
            }
        )
        return violations, review_state

    review_value = fields["review"].strip()
    none_match = REVIEW_NONE_RE.match(review_value)
    if none_match:
        review_state["mode"] = "none"
        reason = none_match.group(1).strip()
        if not reason:
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "review-none-reason-empty",
                    "detail": (
                        f"{decision_path} declares `Review: none` with no non-empty reason "
                        "after it — use `Review: none — <why no review was done>` "
                        "(this check only verifies the reason is non-empty, not that it is "
                        "adequate)"
                    ),
                }
            )
        return violations, review_state

    review_state["mode"] = "path"
    cleaned = review_value.strip("`").strip()
    candidate = project / cleaned
    if not _is_contained(candidate, project):
        violations.append(
            {
                "round": str(round_dir),
                "kind": "review-path-escapes-project",
                "detail": (
                    f"{decision_path} declares `Review: {review_value}`, which resolves "
                    "outside the project under canonical (symlink-resolved) containment"
                ),
            }
        )
        return violations, review_state
    if not os.path.lexists(candidate):
        violations.append(
            {
                "round": str(round_dir),
                "kind": "review-path-not-found",
                "detail": f"{decision_path} declares `Review: {review_value}`, which does not exist",
            }
        )
        return violations, review_state
    if candidate.is_symlink():
        violations.append(
            {
                "round": str(round_dir),
                "kind": "review-path-is-symlink",
                "detail": (
                    f"{decision_path} declares `Review: {review_value}`, which is a symlink — "
                    "B2a requires an ordinary file, even when the symlink's target legitimately "
                    "resolves inside the project"
                ),
            }
        )
        return violations, review_state
    if not candidate.is_file():
        violations.append(
            {
                "round": str(round_dir),
                "kind": "review-path-not-file",
                "detail": f"{decision_path} declares `Review: {review_value}`, which is not a regular file",
            }
        )
        return violations, review_state

    if fields["review_digest"] is not None:
        declared_digest = fields["review_digest"].strip()
        actual_digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if not (
            REVIEW_DIGEST_RE.match(declared_digest)
            and declared_digest.lower() == actual_digest.lower()
        ):
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "review-digest-mismatch",
                    "detail": (
                        f"{decision_path} declares `Review digest: {declared_digest}` which "
                        f"does not match the sha256 of {candidate} ({actual_digest})"
                    ),
                }
            )

    return violations, review_state


def verify_round(
    project: Path, round_dir: Path, suffix_index: dict[str, list[tuple[str, ...]]]
) -> tuple[list[dict], dict]:
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

    coverage = _empty_coverage()
    coverage["rounds"] = 1
    if not checked_files:
        coverage["rounds_zero_inspected"] = 1

    # E2(a): scope-lock existence and Allowed-Changes parseability are
    # checked unconditionally for every round, independent of whether the
    # round has any evidence/review files. Before this change both checks
    # lived behind `if checked_files:`, so a round with nothing under
    # evidence/ or reviews/ never had its scope-lock inspected at all (the
    # historical "9 rounds zero-inspected, still exit 0" gap). Containment
    # (below) still requires artifacts to check, so it stays guarded.
    scope_lock = round_dir / "scope-lock.md"
    spans: list[str] = []
    if not scope_lock.exists():
        violations.append(
            {
                "round": str(round_dir),
                "kind": "missing-scope-lock",
                "detail": f"{scope_lock} does not exist",
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

    if checked_files and spans:
        coverage["rule_a_files"] = len(checked_files)
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
            coverage["rule_b_files"] += 1
            cited_list, exempt_external, ignored_explicit, shape_dropped, has_ignore = pathish_citations(
                review.read_text(encoding="utf-8")
            )
            coverage["citations_exempt_external"] += exempt_external
            coverage["citations_ignored_explicit"] += ignored_explicit
            coverage["citations_shape_dropped"] += shape_dropped
            if has_ignore:
                coverage["review_files_with_ignore"] += 1
            for cited in cited_list:
                coverage["citations_checked"] += 1
                want_dir = cited.endswith("/")
                resolved = _any_base_resolves(cited, citation_bases, project, want_dir)
                stripped = cited
                if not resolved:
                    stripped = strip_locator_suffix(cited)
                    if stripped != cited:
                        resolved = _any_base_resolves(stripped, citation_bases, project, want_dir)
                # T-064: the suffix-unique fallback no longer resolves a
                # citation (see module docstring, "Suffix hint" section) — a
                # citation with no explicit-base resolution is
                # `dangling-citation` unconditionally. What the fallback
                # still contributes, when it finds a unique and still-real
                # suffix hit, is a display-only pointer appended to this
                # violation's `detail`, plus a `citations_suffix_hinted`
                # coverage tick — neither changes whether this branch runs.
                if not resolved:
                    hint = ""
                    hint_target = suffix_hint_target(stripped, suffix_index, project)
                    if hint_target is not None:
                        coverage["citations_suffix_hinted"] += 1
                        hint_rel = hint_target.relative_to(project).as_posix()
                        hint = (
                            f" — a unique suffix match exists at {hint_rel}; if that is "
                            "the intended file, cite it by a resolvable path or mark the "
                            f"line {IGNORE_MARKER}"
                        )
                    violations.append(
                        {
                            "round": str(round_dir),
                            "kind": "dangling-citation",
                            "detail": f"{review} cites `{cited}` which does not exist{hint}",
                        }
                    )

    # E4: same-file enum contradiction in decision.md. Deliberately the
    # narrowest possible check — two enum lines in one file, compared after
    # strip().lower(). No prose parsing, no path resolution, no cross-file
    # join, no value normalization: those are exactly what produced six of
    # this repo's ten evolution issues. Absent fields are never a violation,
    # so existing rounds need no migration.
    decision = round_dir / "decision.md"
    if decision.exists():
        verdict = residuals = None
        for line in decision.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if verdict is None and stripped.lower().startswith("- verdict:"):
                verdict = stripped.split(":", 1)[1].strip().lower()
            elif residuals is None and stripped.lower().startswith("- residuals:"):
                residuals = stripped.split(":", 1)[1].strip().lower()
        if verdict == "pass" and residuals not in (None, "", "none"):
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "verdict-residual-contradiction",
                    "detail": (
                        f"{decision} declares `Verdict: pass` while `Residuals` is "
                        f"non-none — use `pass-with-residual` when part of the claim "
                        f"is uncovered or deferred"
                    ),
                }
            )

        # B2a (T-066 §4 "只入账、不入树"): decision.md must declare
        # Review/Reviewer/Review verdict (Review digest optional). See
        # `check_review_declaration` for exactly what is and is not
        # checked; deliberately never touches rule_a_files, rule_b_files,
        # or citations_checked — a declared review file is accounted for,
        # not scanned.
        decision_text = decision.read_text(encoding="utf-8", errors="ignore")
        review_violations, review_state = check_review_declaration(round_dir, project, decision_text)
        violations.extend(review_violations)
        if review_state["missing_fields"]:
            coverage["rounds_review_missing_fields"] += 1
        elif review_state["mode"] == "none":
            coverage["rounds_review_none"] += 1
        elif review_state["mode"] == "path":
            coverage["rounds_review_declared"] += 1
        if review_state["digest_declared"]:
            coverage["rounds_review_digest_declared"] += 1

    return violations, coverage


def _empty_coverage() -> dict:
    """Zeroed coverage accumulator. Keys match the `### Mechanical Gate
    Boundary` IN column in harnessloop-loop/SKILL.md one-to-one; a rename on
    either side must update the other."""
    return {
        "rounds": 0,
        "rounds_zero_inspected": 0,
        "rule_a_files": 0,
        "rule_b_files": 0,
        "citations_checked": 0,
        "citations_exempt_external": 0,
        "citations_suffix_hinted": 0,
        "citations_ignored_explicit": 0,
        "citations_shape_dropped": 0,
        "review_files_with_ignore": 0,
        "rounds_review_declared": 0,
        "rounds_review_none": 0,
        "rounds_review_missing_fields": 0,
        "rounds_review_digest_declared": 0,
    }


def verify_project(project: Path) -> tuple[list[dict], dict]:
    goals_dir = project / ".harnessloop" / "goals"
    coverage = _empty_coverage()
    if not goals_dir.is_dir():
        return [], coverage
    violations: list[dict] = []
    # Built once per project run (not per round/citation) — see
    # `build_suffix_index` for why this matters for performance.
    suffix_index = build_suffix_index(project)
    for round_dir in sorted(goals_dir.glob("*/rounds/*")):
        if round_dir.is_dir():
            round_violations, round_coverage = verify_round(project, round_dir, suffix_index)
            violations.extend(round_violations)
            for key in coverage:
                coverage[key] += round_coverage[key]
    return violations, coverage


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify mechanical Harnessloop protocol gates (scope-lock containment "
            "and citation existence). Citation spans that are regex/glob patterns, "
            "bare-domain URLs (docs.python.org/..., github.com/...), or templated "
            "paths with an angle-bracket placeholder (goals/<id>/...) are exempt "
            "automatically; a citation known to be intentional prose rather than a "
            "real reference can be exempted explicitly by putting "
            "'<!-- verify:ignore -->' on the same line or the line before it "
            "(counted in the citations_ignored_explicit / review_files_with_ignore "
            "coverage fields, so ignore-marker use is monitorable rather than "
            "silent). A pathish span containing '/' whose tail has no extension, "
            "no trailing '/', and no '..' segment is silently dropped before "
            "existence checking; counted in citations_shape_dropped. "
            "Citations are resolved against the project root, the round's goal and "
            "round directories, the project's own .harnessloop/ directory (for "
            "citations using a PATHISH_PREFIXES prefix verbatim, e.g. "
            "setup/data-sources.md), and the root of every git submodule (any depth) "
            "declared in the project's .gitmodules (canonical-containment-checked: a path "
            "or .gitmodules entry that would resolve outside the project — including via "
            "a project-internal symlink or a symlink-then-'..' round-trip — is never "
            "treated as resolved). A trailing :<line>, :<start>-<end>, or ::<anchor> "
            "locator is stripped before checking. A citation still unresolved after all "
            "of the above is reported as dangling-citation unconditionally (T-064: a "
            "path-suffix match is no longer a resolution path); if that citation has "
            ">=2 path segments and matches exactly one file in the project's "
            "tracked-plus-untracked-not-ignored worktree index (or, outside a git "
            "working tree, the walked and noise-pruned tree) as a path suffix, and that "
            "matched path still actually exists, its detail carries a display-only hint "
            "pointing at the match (counted in the citations_suffix_hinted coverage "
            "field) — the citation still fails. A citation ending in / must resolve to "
            "a directory. Home-relative (~/...), filesystem-absolute (/...), and "
            "Windows-absolute (C:/..., \\\\server\\share...) citations are exempt (out "
            "of project scope; counted in the citations_exempt_external coverage field)."
        )
    )
    parser.add_argument("--project", "-p", default=".", help="Target project directory. Defaults to current directory.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"Project directory not found: {project}", file=sys.stderr)
        return 2

    violations, coverage = verify_project(project)
    if args.json:
        print(
            json.dumps(
                {"project": str(project), "violations": violations, "coverage": coverage},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"Harnessloop verify: {project}")
        if violations:
            for violation in violations:
                print(f"  [{violation['kind']}] {violation['detail']}")
            print(f"{len(violations)} violation(s) found.")
        elif coverage["rounds_zero_inspected"] > 0:
            # E2(b): a clean exit is not a blanket "all clear" when some
            # rounds had nothing under evidence/ or reviews/ to check in the
            # first place. Print the qualified form instead of the
            # unqualified banner below so a clean exit for those rounds
            # cannot be misread as "checked and clean".
            print(
                "passed, but not a clean sweep: "
                f"{coverage['rounds_zero_inspected']} of {coverage['rounds']} round(s) had "
                "nothing under evidence/ or reviews/ to inspect — a clean exit for those "
                'rounds means "nothing to check", not "checked and clean".'
            )
        else:
            print("All mechanical protocol gates passed.")
        # Unconditional coverage line (E2(b)): printed regardless of pass/fail
        # so "was this gate actually run over anything" is always visible,
        # not just inferable from exit code. Field names here are the short
        # print-form of the `coverage` dict keys (see `_empty_coverage`);
        # the --json output uses the full dict verbatim.
        print(
            "coverage: "
            f"rounds={coverage['rounds']} rule_a_files={coverage['rule_a_files']} "
            f"rule_b_files={coverage['rule_b_files']} citations={coverage['citations_checked']} "
            f"citations_exempt_external={coverage['citations_exempt_external']} "
            f"citations_suffix_hinted={coverage['citations_suffix_hinted']} "
            f"citations_ignored_explicit={coverage['citations_ignored_explicit']} "
            f"citations_shape_dropped={coverage['citations_shape_dropped']} "
            f"review_files_with_ignore={coverage['review_files_with_ignore']} "
            f"zero_inspected={coverage['rounds_zero_inspected']} "
            f"review_declared={coverage['rounds_review_declared']} "
            f"review_none={coverage['rounds_review_none']} "
            f"review_missing_fields={coverage['rounds_review_missing_fields']} "
            f"review_digest_declared={coverage['rounds_review_digest_declared']}"
        )
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
