#!/usr/bin/env python3
"""Verify the mechanical subset of the Harnessloop protocol.

Judgment gates (does this evidence support acceptance?) stay with the model.
This script enforces only machine-checkable rules:

- Rule A (scope-lock containment): every file under a round's evidence/ and
  reviews/ directories must fall inside a path allowed by that round's
  scope-lock.md "Allowed Changes" section. Before either directory (or the
  round, goal, or goals directory above them) is ever listed, each is
  containment-checked in its own right: a symlink at any of those levels —
  `evidence/`, `reviews/`, the round directory itself, or a goal directory —
  is never followed to read whatever it points at (`round-container-escapes-
  project`); every entry found while walking a clean container is itself
  symlink-checked before any `is_file()` filtering, so a symlinked file, a
  symlinked directory, and a dangling symlink are all reported
  (`round-artifact-is-symlink`) rather than silently included or silently
  dropped. The per-file "is this allowed" check itself also ANDs the
  existing lexical scope-lock match with canonical project containment, so a
  file lexically inside `reviews/` whose real target escapes the project
  still fails even if some future change ever bypassed the container/entry
  checks above (G17, external-citation-base-spec-20260727.md §3.1 — see
  `_container_escape_violation` / `_scan_round_artifacts` / `_is_contained`).
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
  the citation: `:<line>`, `:<start>-<end>`, a comma-separated multi-range
  (`:<start>-<end>,<start>-<end>,...`, e.g.
  `app/kernel-client/swift/X.swift:44-46,443-507` — PR-1), or `::<anchor>`
  (see `strip_locator_suffix`). Reviewers routinely cite `path/to/file.py:123`
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
# `:start-end`, optionally repeated as a comma-separated list of ranges
# (`:44-46,443-507`) — reviewers commonly cite several disjoint spans in one
# file this way. The comma-group is optional and repeatable
# (`(?:,\d+(?:-\d+)?)*`), so a single `:123` or `:44-46` (zero repeats)
# matches exactly as before this was added — this is a strict superset of
# the prior pattern, not a replacement shape. See `strip_locator_suffix`.
ANCHOR_SUFFIX_RE = re.compile(r"::[^:]+$")
LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*$")

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

# External reference roots (PR-3, external-citation-base-spec-20260727.md
# §2.1-2.7): a project may declare named external "reference roots" (e.g. an
# upstream design wiki kept outside the project tree, cited as upstream fact
# by this project's reviews) and cite a file inside one with the double-sigil
# `@@<alias>/<relpath>` syntax. This is a *second*, structurally separate
# resolution domain from ordinary project-relative citations -- see
# `load_reference_roots` for the two-file declaration schema (a versioned,
# zero-absolute-path side plus a gitignored local side that only ever answers
# "where", never "is this the right tree"), and `resolve_external_citation`
# for how a citation resolves once its alias is declared and its root is
# bound and available. Single `@` (npm scoped packages / TS `paths` aliases)
# and `alias:` colon-prefixed forms were both measured and rejected before
# this syntax was chosen -- see the spec's §2.1 and §7 for the falsifying
# measurements; do not reintroduce either.
ALIAS_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
ALIAS_CITATION_RE = re.compile(r"^@@([a-z][a-z0-9-]{1,31})/(.*)$", re.DOTALL)

REFERENCE_ROOTS_VERSIONED_REL = ".harnessloop/setup/reference-roots.json"
REFERENCE_ROOTS_LOCAL_REL = ".harnessloop/local/reference-roots.local.json"
REFERENCE_ROOTS_MAX_BYTES = 64 * 1024
REFERENCE_ROOTS_MAX_COUNT = 8

# §2.2 schema table: a raw (pre-expanduser) local binding path string
# containing any of these is rejected outright (`reference-root-rejected`)
# before any filesystem call -- a glob or shell/env-interpolation character
# in a path meant to be used literally is itself a red flag, independent of
# what it might resolve to.
_GLOB_OR_ENV_CHARS = frozenset("*?[]$%")

# §2.2: the local (low-trust) binding side may only ever answer "where" --
# a `path` string plus a provenance note (`bound_at`, matching the worked
# example). If it also tries to answer "is this the right tree" (any of
# these four keys), that is a `reference-root-local-invalid` violation, not
# a value to trust.
_LOCAL_BINDING_ALLOWED_KEYS = frozenset({"path", "bound_at"})
_LOCAL_BINDING_FORBIDDEN_KEYS = frozenset({"identity", "available", "optional", "expect_present"})

# §2.2: the exact key set a versioned root entry may declare. `subpaths` is
# the only optional one.
_VERSIONED_ROOT_ALLOWED_KEYS = frozenset(
    {"alias", "purpose", "expect_present", "subpaths", "approved_by"}
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
    `suffix_unique_match` (the unique-hit's specific path) — and, since G17
    (external-citation-base-spec-20260727.md §3.1), a fourth call site: Rule
    A's own per-file `allowed` check in `verify_round`, which ANDs the
    existing lexical `is_under(file_path, base / span)` scope-lock test with
    `_is_contained(file_path, project)` so a file lexically inside
    `reviews/` or `evidence/` whose real target is a symlink escape out of
    the project (fixture A: `reviews/ext.md -> <outside>`) still fails
    scope-lock containment even though its *path string* never leaves
    `reviews/`. All four must share this one definition so a symlink escape
    cannot slip through whichever call site is not updated.
    """
    return is_under(_canonical(candidate), _canonical(project))


def _is_contained_pinned(candidate: Path, canonical_domain: Path) -> bool:
    """Containment check for a *pre-canonicalized, pinned* domain root (PR-3
    §2.5) -- only `candidate` is canonicalized here; `canonical_domain` never
    is.

    This is deliberately a different function from `_is_contained`, not an
    overload of it: `_is_contained` re-canonicalizes *both* sides on every
    call, which is exactly right for the project root (a project directory
    is not expected to be symlink-swapped mid-run) but is the wrong contract
    for an external reference root. A reference root's canonical form is
    computed once, at `load_reference_roots` time, specifically so that a
    `~/wiki` symlink swapped out from under a long-running verification pass
    cannot silently change what "inside the root" means partway through that
    same run -- the root is canonicalized once and then *pinned* for the
    rest of the run. Passing a non-canonical `canonical_domain` here would
    silently defeat that pinning (each call would re-resolve it, following
    whatever the symlink currently points at), so the entry assertion below
    makes that misuse fail loudly instead of silently.
    """
    assert _canonical(canonical_domain) == canonical_domain, (
        "_is_contained_pinned requires an already-canonical domain; pass "
        "_canonical(root) once at load time, never the raw declared path"
    )
    return is_under(_canonical(candidate), canonical_domain)


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
    """Strip a trailing `::<anchor>`, `:<line>`, `:<start>-<end>`, or
    comma-separated multi-range (`:<start>-<end>,<start>-<end>,...`) locator.

    Reviewers commonly cite a position *within* a file rather than just the
    file itself: `plugins/foo/scripts/check_setup.py:123` (a line number),
    `docs/x.md:10-20` (a line range), `.hopper/tasks/foo.md::root` (a named
    anchor), or `app/kernel-client/swift/X.swift:44-46,443-507` (several
    disjoint ranges in one citation — PR-1, external-citation-base-spec-
    20260727.md §5: measured against the fair proxy corpus, this comma-
    separated extension alone resolves 10 previously-dangling citations, 7
    of them in the implementation-era subset — the same implementation-era
    count the entire external-reference-base protocol surface would have
    resolved, at a cost of 3 characters instead of ~500 LOC and a new trust
    domain). The locator is not part of the path — checking the literal
    locator-suffixed string against the filesystem always fails even when
    the file plainly exists. The `::anchor` form is tried first since it is
    the more specific shape (and would otherwise be partially consumed by
    the line-number pattern if the anchor itself looked numeric). Returns
    `cleaned` unchanged if neither suffix is present.
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
    file extension, no trailing `/`, and no `..` segment — e.g. `src/pkgdir`
    — falls through the shape branch below without ever being appended to
    `cited`, and before this field existed that drop was silent. This is
    also the cheapest way to turn a real dangling citation green: delete the
    file extension from an already-red span and it vanishes from every
    coverage field, not just this one. (PR-3: an `@@<alias>/...` span no
    longer takes this exit even with an extension-less tail — e.g.
    `@@wiki/kernel` — because the alias-shape branch above matches first
    and appends it to `cited` unconditionally; only a non-`@@` span can
    still land in `shape_dropped`.)

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
            if ALIAS_CITATION_RE.match(cleaned):
                # PR-3 §2.1 branch (a): `@@<alias>/<relpath>` is
                # unconditionally a citation -- which resolution *domain* a
                # span belongs to is decided by its syntax alone, before any
                # exemption heuristic below runs and before any filesystem
                # access (§2.4: "domain is decided by text + the declared
                # alias set, before any filesystem access"). This also
                # closes the one gap explicitly called out in the spec: a
                # tail with no extension and no trailing slash (e.g.
                # `@@wiki/kernel`) would otherwise fall through to the shape
                # branch below and be silently counted as
                # `shape_dropped` rather than checked. Whether the alias
                # is actually *declared* is decided later, per citation, by
                # the caller (`verify_round`) -- this function has no
                # project/declaration context to decide that here.
                cited.append(cleaned)
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


# ---------------------------------------------------------------------------
# External reference roots (PR-3, external-citation-base-spec-20260727.md
# §2.2-2.5). Everything from here to `resolve_external_citation` implements
# the second, structurally separate resolution domain `@@<alias>/<relpath>`
# citations use. See the module docstring's top for the one-paragraph
# orientation and `verify_round` for how this is wired into Rule B.
# ---------------------------------------------------------------------------


class ReferenceRoot:
    """One declared external reference root, fully resolved (or definitively
    marked unavailable) for this run.

    Built once per `verify_project` call by `load_reference_roots` — never
    re-derived per-citation or per-round; `verify_round` receives the same
    `dict[str, ReferenceRoot]` for every round in the project (G5's "every
    run re-validates" applies at the `load_reference_roots` call granularity
    — once per `verify_project` invocation — not once per lookup within it,
    and not cached *across* separate invocations).

    `canonical` is `None` unless `available` is `True` — every caller must
    check `available` before touching `canonical`, never the reverse.
    `unavailable_reason` is one of `"unbound"`, `"unresolvable"`,
    `"rejected"`, `"identity-mismatch"`, or `None` (only when available) —
    deliberately a short enum string, never a path (G20: nothing derived
    from this object may leak an absolute path into a violation detail,
    coverage line, or default `--json` output).
    """

    __slots__ = (
        "alias",
        "purpose",
        "expect_present",
        "subpaths",
        "approved_by",
        "canonical",
        "available",
        "unavailable_reason",
    )

    def __init__(
        self,
        alias: str,
        purpose: str,
        expect_present: tuple[str, ...],
        subpaths: tuple[str, ...] | None,
        approved_by: str,
        canonical: Path | None,
        available: bool,
        unavailable_reason: str | None,
    ) -> None:
        self.alias = alias
        self.purpose = purpose
        self.expect_present = expect_present
        self.subpaths = subpaths
        self.approved_by = approved_by
        self.canonical = canonical
        self.available = available
        self.unavailable_reason = unavailable_reason


def _load_versioned_roots(path: Path) -> tuple[list[dict], str | None]:
    """Parse and fully validate `.harnessloop/setup/reference-roots.json`.

    Returns `(entries, None)` on success (`entries` is a list of plain dicts,
    one per declared root, with keys already normalized to
    `tuple[str, ...]` where the schema calls for a list) or `([], message)`
    on ANY structural problem (G1): a single bad root entry invalidates the
    *entire* file — "整份作废、加载零个 root" (§2.2) — deliberately not a
    partial load, so a project can never end up in an ambiguous "some of my
    declared roots loaded, which ones?" state.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        return [], f"{path}: cannot stat ({exc})"
    if size > REFERENCE_ROOTS_MAX_BYTES:
        return [], f"{path}: exceeds {REFERENCE_ROOTS_MAX_BYTES} bytes"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], f"{path}: cannot read ({exc})"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], f"{path}: invalid JSON ({exc})"
    if not isinstance(data, dict):
        return [], f"{path}: top level must be a JSON object"
    unknown_top = set(data) - {"version", "roots"}
    if unknown_top:
        return [], f"{path}: unknown top-level key(s) {sorted(unknown_top)}"
    if data.get("version") != 1:
        return [], f"{path}: 'version' must be 1"
    raw_roots = data.get("roots", [])
    if not isinstance(raw_roots, list):
        return [], f"{path}: 'roots' must be a list"
    if len(raw_roots) > REFERENCE_ROOTS_MAX_COUNT:
        return [], f"{path}: more than {REFERENCE_ROOTS_MAX_COUNT} roots declared"

    # G1: an alias may not collide with a protocol PATHISH_PREFIXES token
    # (e.g. an alias literally named "setup" or "state"), computed from the
    # same module-level constant Rule B's own base resolution uses so the
    # two lists can never drift apart.
    pathish_tokens = {p.strip("./").rstrip("/") for p in PATHISH_PREFIXES}

    seen_alias: set[str] = set()
    entries: list[dict] = []
    for i, raw in enumerate(raw_roots):
        if not isinstance(raw, dict):
            return [], f"{path}: roots[{i}] must be an object"
        unknown = set(raw) - _VERSIONED_ROOT_ALLOWED_KEYS
        if unknown:
            return [], f"{path}: roots[{i}] has unknown key(s) {sorted(unknown)}"

        alias = raw.get("alias")
        if not isinstance(alias, str) or not ALIAS_RE.match(alias):
            return [], f"{path}: roots[{i}].alias is missing or does not match {ALIAS_RE.pattern}"
        if alias in pathish_tokens:
            return [], f"{path}: roots[{i}].alias {alias!r} collides with a PATHISH_PREFIXES token"
        if alias in seen_alias:
            return [], f"{path}: duplicate alias {alias!r}"
        seen_alias.add(alias)

        purpose = raw.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            return [], f"{path}: roots[{i}].purpose must be a non-empty string"

        expect_present = raw.get("expect_present")
        if (
            not isinstance(expect_present, list)
            or not (1 <= len(expect_present) <= 8)
            or not all(isinstance(p, str) and p.strip() for p in expect_present)
        ):
            return [], f"{path}: roots[{i}].expect_present must be 1-8 non-empty strings"

        subpaths = raw.get("subpaths")
        if subpaths is not None and (
            not isinstance(subpaths, list)
            or not all(isinstance(p, str) and p.strip() and "/" not in p for p in subpaths)
        ):
            return [], f"{path}: roots[{i}].subpaths, if present, must be single-segment names"

        approved_by = raw.get("approved_by")
        if not isinstance(approved_by, str) or not approved_by.strip():
            return [], f"{path}: roots[{i}].approved_by must be a non-empty string"

        entries.append(
            {
                "alias": alias,
                "purpose": purpose,
                "expect_present": tuple(expect_present),
                "subpaths": tuple(subpaths) if subpaths is not None else None,
                "approved_by": approved_by,
            }
        )
    return entries, None


def _load_local_bindings(path: Path) -> tuple[dict[str, str], str | None]:
    """Parse and validate `.harnessloop/local/reference-roots.local.json`.

    Returns `(bindings, None)` where `bindings` maps alias -> raw (not yet
    expanded or resolved) declared path string, or `({}, message)` on any
    structural problem (G2/G3). A binding entry declaring any of
    `_LOCAL_BINDING_FORBIDDEN_KEYS` (`identity`/`available`/`optional`/
    `expect_present`) is rejected specifically because those keys would let
    the low-trust local side answer a high-trust question ("is this the
    right tree") that only the project-committed sentinel check
    (`expect_present`, verified server-side by `_load_one_root`) is allowed
    to answer (§2.2: "低信任半边不得影响可用性判定").

    A missing file is not an error — every declared alias is simply
    `"unbound"` (see `_load_one_root`), which is the correct default: a
    fresh clone or a new machine has bound nothing yet.
    """
    if not path.is_file():
        return {}, None
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {}, f"{path}: cannot stat ({exc})"
    if size > REFERENCE_ROOTS_MAX_BYTES:
        return {}, f"{path}: exceeds {REFERENCE_ROOTS_MAX_BYTES} bytes"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"{path}: cannot read ({exc})"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"{path}: invalid JSON ({exc})"
    if not isinstance(data, dict):
        return {}, f"{path}: top level must be a JSON object"
    unknown_top = set(data) - {"version", "bindings"}
    if unknown_top:
        return {}, f"{path}: unknown top-level key(s) {sorted(unknown_top)}"
    if data.get("version") != 1:
        return {}, f"{path}: 'version' must be 1"
    raw_bindings = data.get("bindings", {})
    if not isinstance(raw_bindings, dict):
        return {}, f"{path}: 'bindings' must be an object"

    bindings: dict[str, str] = {}
    for alias, binding in raw_bindings.items():
        if not isinstance(binding, dict):
            return {}, f"{path}: bindings[{alias!r}] must be an object"
        forbidden = _LOCAL_BINDING_FORBIDDEN_KEYS & set(binding)
        if forbidden:
            return {}, (
                f"{path}: bindings[{alias!r}] declares low-trust identity "
                f"key(s) {sorted(forbidden)} -- the local binding file may "
                "only ever answer 'where', never 'is this the right tree'"
            )
        unknown = set(binding) - _LOCAL_BINDING_ALLOWED_KEYS
        if unknown:
            return {}, f"{path}: bindings[{alias!r}] has unknown key(s) {sorted(unknown)}"
        raw_path = binding.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return {}, f"{path}: bindings[{alias!r}].path must be a non-empty string"
        bindings[alias] = raw_path
    return bindings, None


def _resolve_in_root(root: Path, rel: str) -> Path | None:
    """PR-3 §2.5's two orthogonal containment defenses, applied to an
    external reference root: `root` must already be canonical (this is the
    same "pinned domain" `_is_contained_pinned` requires — see its
    docstring).

    Defense 1 — literal traversal rejection, applied to the raw text before
    any join: an empty `rel`, or one starting with `/` or `~`, a Windows
    drive-absolute form, or containing a `..` segment, is rejected before
    ever touching the filesystem (mirrors `_looks_like_out_of_project` /
    the project-domain `..` rejection in `_resolve_in_project` — the same
    escape shapes are just as real against an external root as against the
    project).

    Defense 2 — unfolded raw join + pinned canonical containment: the
    candidate is `root / rel`, never a pre-folded
    `Path(os.path.normpath(root / rel))` copy of it (T-064 MUST-FIX C,
    reapplied to the new domain: folding `link/../escape.md` lexically
    *before* resolving would erase the very symlink hop containment exists
    to catch). `_is_contained_pinned` resolves the raw join and checks it
    against the domain pinned at load time.
    """
    if (
        not rel
        or rel.startswith(("/", "~"))
        or WINDOWS_DRIVE_ABS_RE.match(rel)
        or any(seg == ".." for seg in rel.split("/"))
    ):
        return None
    candidate = root / rel
    if not _is_contained_pinned(candidate, root):
        return None
    return candidate


def _resolve_case_exact(root: Path, rel: str) -> Path | None:
    """Walk `rel`'s segments under `root` one directory entry at a time via
    `os.scandir`, matching each segment name *exactly* (byte-for-byte
    string comparison), never through `Path.exists()`/`Path.is_dir()` --
    G10: those two delegate to the host filesystem's own comparison, which
    is case-*insensitive* (but case-preserving) on a default macOS or
    Windows filesystem, so a citation with the wrong case for a real file
    would otherwise resolve there (measured directly against this project's
    own external root: `@@wiki/KERNEL/FACTS.MD` resolves via `.exists()` on
    macOS even though the real file is `kernel/facts.md`).

    Deliberately host-independent and never delegated to `resolve()`: this
    function's whole job is to disagree with the host filesystem's own
    case-folding when they differ, so it cannot reuse anything that follows
    that folding.

    Returns the real, exact-case path if every segment matched exactly, or
    `None` the moment any segment does not (missing entry, or `root`/an
    intermediate segment is not actually a directory). A caller still owns
    the final existence/directory-semantics decision (`_exists_as`, called
    by `resolve_external_citation`) — this function only proves "an entry
    with this exact name exists at this level", not "the whole path is
    usable the way the citation implies" (e.g. a broken symlink's final
    segment is still found here; `resolve_external_citation` is what turns
    that into `not_found`, exactly as `_exists_as` does for the project
    domain).
    """
    current = root
    for seg in (s for s in rel.split("/") if s):
        if not current.is_dir():
            return None
        try:
            with os.scandir(current) as it:
                match = next((e for e in it if e.name == seg), None)
        except OSError:
            return None
        if match is None:
            return None
        current = current / seg
    return current


def resolve_external_citation(root: ReferenceRoot, rel: str) -> tuple[str, Path | None]:
    """Resolve `rel` (the text after `@@<alias>/`, one attempt — the caller
    tries the as-written form and, on failure, a locator-stripped retry, the
    same order Rule B's project-domain resolution uses) against
    `root.canonical`.

    Returns `("resolved" | "not_found" | "rejected", path-or-None)`.
    `root` must already be `available` — callers check that separately and
    report `external-citation-unverifiable` instead of ever calling this
    (G7); this function has no "unavailable" outcome of its own.

    Order: (1) `_resolve_in_root` — G8's literal-traversal defense and G9's
    unfolded-join pinned containment; a rejection here is final and never
    falls through to the existence check below (a rejected `candidate` is
    not something `_resolve_case_exact` should ever be asked about). (2)
    `_resolve_case_exact` — G10's exact-case segment walk; `None` here is
    `not_found`. (3) directory-semantics existence (G11): `is_dir()` when
    `rel` ends in `/`, `exists()` otherwise (`exists()` follows symlinks, so
    a broken symlink's dangling target is `not_found`, not `resolved`,
    exactly like the project domain's `_exists_as`). (4) `subpaths`
    whitelist (G12), checked against the *canonical* path relative to the
    canonical root, not the literal `rel` — a `kernel/link -> <root>/raw`
    symlink cited as `kernel/link/x.md` must be judged by where it actually
    lands (`raw`), not by the literal first segment it was typed with.
    """
    candidate = _resolve_in_root(root.canonical, rel)
    if candidate is None:
        return "rejected", None

    want_dir = rel.endswith("/")
    real = _resolve_case_exact(root.canonical, rel)
    if real is None:
        return "not_found", None
    if not _exists_as(real, want_dir):
        return "not_found", None

    if root.subpaths:
        canon_real = _canonical(real)
        try:
            rel_canon = canon_real.relative_to(root.canonical)
        except ValueError:
            return "rejected", None
        first_seg = rel_canon.parts[0] if rel_canon.parts else None
        if first_seg not in root.subpaths:
            return "rejected", None

    return "resolved", real


def _resolve_external_with_locator(root: ReferenceRoot, rel: str, full_cited: str) -> str:
    """Try `rel` as written; on failure, retry with `full_cited`'s own
    trailing locator suffix stripped (mirrors Rule B's project-domain
    "original, then locator-stripped" order — see `strip_locator_suffix`,
    unchanged by PR-3 and already verified to work unmodified against
    `@@alias/...` spans).

    Returns only the outcome string (`"resolved" | "not_found" |
    "rejected"`) since the specific resolved path is not needed by the
    citation-existence caller (unlike the sentinel/subpaths checks, which do
    need it). If neither attempt resolves, `"rejected"` wins over
    `"not_found"` so a genuinely malformed or escaping relpath is never
    silently downgraded to a plain "no such file" just because a
    locator-stripped retry also failed to find anything.
    """
    outcome, _ = resolve_external_citation(root, rel)
    if outcome == "resolved":
        return outcome
    stripped_full = strip_locator_suffix(full_cited)
    if stripped_full != full_cited:
        m = ALIAS_CITATION_RE.match(stripped_full)
        if m and m.group(2) != rel:
            outcome2, _ = resolve_external_citation(root, m.group(2))
            if outcome2 == "resolved":
                return outcome2
            if outcome2 == "rejected":
                outcome = "rejected"
    return outcome


def _load_one_root(
    entry: dict, raw_path: str | None, project_canonical: Path, verify_identity: bool
) -> ReferenceRoot:
    """Resolve one declared root entry to a `ReferenceRoot` (G4-G6).

    Load order is itself the safety property (§2.5): `expanduser` (`~` only,
    no env/glob interpolation) -> `resolve(strict=True)` (wrapped in
    `try/except (OSError, RuntimeError)` — a symlink loop raises
    `RuntimeError`, not `OSError`, on the interpreters this was measured
    against) -> `is_dir()` -> *only then* the forbidden-root checks, and
    every one of those checks compares **canonical** values, never the raw
    declared string (G4: resolving first is what stops a symlink like
    `fakehome/w2 -> <project's own parent directory>` — which reads as an
    innocuous relative string — from defeating every literal check that ran
    before resolution). The declared-string glob/env-character check is the
    one exception: it runs on the raw string, deliberately before
    `expanduser`/`resolve` are ever called, since a literal `*`/`$(`/`${`
    in a path meant to be used literally is suspicious independent of what
    it might canonicalize to.
    """
    common = dict(
        alias=entry["alias"],
        purpose=entry["purpose"],
        expect_present=entry["expect_present"],
        subpaths=entry["subpaths"],
        approved_by=entry["approved_by"],
    )

    if raw_path is None:
        return ReferenceRoot(canonical=None, available=False, unavailable_reason="unbound", **common)

    if any(ch in _GLOB_OR_ENV_CHARS for ch in raw_path) or "${" in raw_path or "$(" in raw_path:
        return ReferenceRoot(canonical=None, available=False, unavailable_reason="rejected", **common)

    try:
        canonical = Path(raw_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return ReferenceRoot(canonical=None, available=False, unavailable_reason="unresolvable", **common)

    if not canonical.is_dir():
        return ReferenceRoot(canonical=None, available=False, unavailable_reason="rejected", **common)

    home = Path.home().resolve()
    forbidden = (
        canonical == Path(canonical.anchor)
        or canonical == home
        or canonical == home.parent
        or is_under(project_canonical, canonical)  # root is project's ancestor or itself
        or is_under(canonical, project_canonical)  # root sits inside the project
    )
    if forbidden:
        return ReferenceRoot(canonical=None, available=False, unavailable_reason="rejected", **common)

    if verify_identity:
        for sentinel in entry["expect_present"]:
            candidate = _resolve_in_root(canonical, sentinel)
            if candidate is None or not _exists_as(candidate, sentinel.endswith("/")):
                return ReferenceRoot(
                    canonical=None, available=False, unavailable_reason="identity-mismatch", **common
                )

    return ReferenceRoot(canonical=canonical, available=True, unavailable_reason=None, **common)


def load_reference_roots(
    project: Path, verify_identity: bool = True
) -> tuple[dict[str, ReferenceRoot], list[dict]]:
    """Load, validate, and resolve every declared external reference root.

    Reads two files: the versioned, zero-absolute-path
    `.harnessloop/setup/reference-roots.json` (git-committed) and the
    gitignored, machine-local `.harnessloop/local/reference-roots.local.json`
    (§2.2). Absence of the versioned file is treated exactly like an empty
    `roots` list — today's behavior, unchanged (§2.2: "缺席 ≡ 空列表 ≡ 今天的
    行为"). This is the *only* parser for either file — `check_setup.py`
    must call this (with `verify_identity=False`, see below) rather than
    writing a second one if it ever wants to report an advisory line (§2.2:
    "不得自写第二个解析器").

    `verify_identity`: when `True` (the default, and always `True` when
    called from `verify_project`), a root whose `expect_present` sentinels
    do not all resolve is marked unavailable
    (`unavailable_reason="identity-mismatch"`) rather than available. When
    `False`, that check is skipped entirely — intended for a future
    optimistic/advisory reader (e.g. a setup wizard reporting "N reference
    roots declared") that must never let a low-cost, best-effort read
    silently disagree with what the mechanical gate would decide; skipping
    the check is the honest way to do that (reporting a wrong "available"
    would not be).

    Returns `(roots, violations)`. `roots` maps alias -> `ReferenceRoot`
    (both available and unavailable ones — callers distinguish via
    `.available`). `violations` are the G1/G2/G4/G5/G6 declaration-level
    problems found while loading — never round-scoped (a declaration is a
    project-level fact), so every violation here carries `"round":
    str(project)`. `G7`'s per-alias-per-round-independent
    `external-root-unavailable` violation is *not* added here — that is the
    caller's (`verify_project`'s) job, exactly once per unavailable alias,
    project-wide (§2.7: "external_roots_declared/available ... 项目级,在轮次
    循环之后单次赋值").
    """
    violations: list[dict] = []
    versioned_path = project / REFERENCE_ROOTS_VERSIONED_REL
    local_path = project / REFERENCE_ROOTS_LOCAL_REL

    if not versioned_path.is_file():
        return {}, violations

    entries, versioned_error = _load_versioned_roots(versioned_path)
    if versioned_error is not None:
        violations.append(
            {"round": str(project), "kind": "reference-roots-invalid", "detail": versioned_error}
        )
        return {}, violations

    bindings, local_error = _load_local_bindings(local_path)
    if local_error is not None:
        violations.append(
            {"round": str(project), "kind": "reference-root-local-invalid", "detail": local_error}
        )
        bindings = {}

    project_canonical = _canonical(project)
    roots: dict[str, ReferenceRoot] = {}
    for entry in entries:
        alias = entry["alias"]
        root = _load_one_root(entry, bindings.get(alias), project_canonical, verify_identity)
        roots[alias] = root
        if root.unavailable_reason == "rejected":
            violations.append(
                {
                    "round": str(project),
                    "kind": "reference-root-rejected",
                    "detail": (
                        f"reference root '{alias}' is rejected (forbidden location, "
                        "not a directory, or a glob/env character in its declared path)"
                    ),
                }
            )
        elif root.unavailable_reason == "unresolvable":
            violations.append(
                {
                    "round": str(project),
                    "kind": "reference-root-unresolvable",
                    "detail": f"reference root '{alias}' could not be resolved (symlink loop or OS error)",
                }
            )
        elif root.unavailable_reason == "identity-mismatch":
            violations.append(
                {
                    "round": str(project),
                    "kind": "reference-root-identity-mismatch",
                    "detail": (
                        f"reference root '{alias}' is bound but at least one of its "
                        "declared `expect_present` sentinels does not exist there"
                    ),
                }
            )
        # "unbound" produces no G1-G6 violation here -- only the G7
        # `external-root-unavailable` violation the caller adds once,
        # project-wide, for every unavailable alias regardless of reason.
    return roots, violations


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


def _container_escape_violation(
    container: Path, project: Path, round_label: Path
) -> dict | None:
    """G17 item 1 (external-citation-base-spec-20260727.md §3.1): checked on
    a round-container directory itself — `goals_dir`, a `goal_dir`, a
    `round_dir`, or that round's `evidence` / `reviews` — *before* anything
    under it is ever listed or read.

    This exists because `Path.rglob`'s per-entry `is_symlink()` guard (see
    `_scan_round_artifacts` below) only ever inspects entries *found while
    walking inside* a directory; it is structurally blind to the starting
    directory itself being a symlink, or one of its own ancestors resolving
    outside the project under canonicalization. Once such a container is
    opened at all — `rglob("*")`, `.iterdir()`, even a plain `.is_dir()`
    check follows the last symlink — the OS has already transparently
    followed the escape, and everything "inside" it from that point on is
    really inside whatever tree the symlink points to (real-repro fixtures
    B: `reviews/` itself a symlink out of the project; C: `rounds/0001`
    itself a symlink out of the project — both left every per-entry check
    downstream with nothing symlinked left to see, because the *entries*
    found after following the escape are ordinary files at the escape's
    destination, not symlinks themselves).

    Returns `None` (nothing to report) when `container` does not exist at
    all (`os.path.lexists` false) — there is nothing to enumerate, so
    nothing to check. Otherwise returns a `round-container-escapes-project`
    violation dict if `container` is itself a symlink (dangling or not) or
    its canonical resolution (`_is_contained`) lands outside `project`, or
    `None` if the container is clean. Callers must not read *anything*
    under `container` — not even to look — once this returns non-`None`;
    the whole point is that its contents were never opened, so there is
    nothing safe left to read.
    """
    if not os.path.lexists(container):
        return None
    if container.is_symlink() or not _is_contained(container, project):
        return {
            "round": str(round_label),
            "kind": "round-container-escapes-project",
            "detail": (
                f"{container} is itself a symlink, or resolves outside the project "
                "under canonical containment — its contents were never read"
            ),
        }
    return None


def _scan_round_artifacts(
    container: Path, project: Path, round_dir: Path
) -> tuple[list[Path], list[dict]]:
    """G17 item 2 (external-citation-base-spec-20260727.md §3.1): walk a
    round-container directory (`evidence/` or `reviews/`, already confirmed
    clean by `_container_escape_violation`) and split its raw `rglob("*")`
    entries into real files versus symlinks — checked *before* any
    `is_file()` filtering, and using `is_symlink()` (an `lstat`, never
    following the link) rather than `is_file()` or `.exists()`.

    This ordering matters: a dangling symlink's `is_file()` is `False` for
    exactly the same reason a genuine absence is — the target does not
    exist — so a filter built on `is_file()` alone drops a broken symlink
    silently, with zero signal that anything was ever there (T-062
    `broken_symlink`, reproduced identically on the artifact side: a
    checker built on `checked_files` after an `is_file()` filter would miss
    the single most classic escape shape). `is_symlink()` sees it either
    way, so every symlinked entry — file, directory, or dangling — is
    reported as `round-artifact-is-symlink` and excluded from the returned
    file list, never silently dropped.

    A symlinked *directory* entry is covered the same way: its own entry is
    a symlink and is flagged. As of this module's tested Python versions,
    `rglob`'s recursive descent does not open a symlinked directory node to
    yield further entries from beneath it (verified directly: see G17
    fixture B's teeth in `validate.py`, which asserts the `dlink` entry
    itself carries the kind — not merely "zero files found under it", which
    would hold trivially either way and prove nothing). This function flags
    the symlinked directory node itself regardless of that; it does not
    depend on it.
    """
    files: list[Path] = []
    violations: list[dict] = []
    for entry in sorted(container.rglob("*")):
        if os.path.lexists(entry) and entry.is_symlink():
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "round-artifact-is-symlink",
                    "detail": f"{entry} is a symlink; its target is never read",
                }
            )
            continue
        if entry.is_file():
            files.append(entry)
    return files, violations


def verify_round(
    project: Path,
    round_dir: Path,
    suffix_index: dict[str, list[tuple[str, ...]]],
    roots: dict[str, "ReferenceRoot"],
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

    coverage = _empty_coverage()
    coverage["rounds"] = 1

    # G17 item 1 (external-citation-base-spec-20260727.md §3.1): check
    # evidence/ and reviews/ containment *before* either is ever listed —
    # `goals_dir` / a `goal_dir` / this `round_dir` were already checked the
    # same way by the caller (`verify_project`) before `verify_round` was
    # even invoked, so by this point only these two remaining containers in
    # the chain are unverified. A container whose check fails here is never
    # enumerated at all (no `rglob`, no `.iterdir()`) — its files are simply
    # absent from `sub_files`/`checked_files`, not silently emptied by some
    # later filter.
    sub_files: dict[str, list[Path]] = {"evidence": [], "reviews": []}
    sub_containers: dict[str, Path | None] = {}
    for sub in ("evidence", "reviews"):
        container = round_dir / sub
        escape = _container_escape_violation(container, project, round_dir)
        if escape is not None:
            violations.append(escape)
            sub_containers[sub] = None
            continue
        sub_containers[sub] = container
        if container.is_dir():
            files, artifact_violations = _scan_round_artifacts(container, project, round_dir)
            sub_files[sub] = files
            violations.extend(artifact_violations)

    checked_files = sub_files["evidence"] + sub_files["reviews"]
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
        # PR-3 §4 OUT list ("Review: 与 scope-lock 的 Allowed Changes 永不接受
        # alias"): a reference root is never an authorization to write --
        # scope-lock's Allowed Changes must name project-versionable paths
        # only. Triggered *only* for a span whose alias is actually
        # declared (facet 1 P2's rejected all-`@`-spans filter would have
        # produced a false-red for e.g. a JS monorepo's `@scope/pkg/` span
        # that has nothing to do with reference roots); an undeclared
        # `@@foo/...` span is left to whatever the existing lexical
        # scope-lock matching already does with it (silently never
        # matching any real file — not a new failure mode). Reported
        # loudly, never silently dropped from `spans`.
        for span in spans:
            span_alias_match = ALIAS_CITATION_RE.match(span)
            if span_alias_match and span_alias_match.group(1) in roots:
                violations.append(
                    {
                        "round": str(round_dir),
                        "kind": "scope-lock-span-names-reference-root",
                        "detail": (
                            f"{scope_lock} names `{span}` in Allowed Changes, which "
                            f"targets declared reference root '{span_alias_match.group(1)}' -- "
                            "a reference root can never be authorized for writes"
                        ),
                    }
                )

    if checked_files and spans:
        coverage["rule_a_files"] = len(checked_files)
        for file_path in checked_files:
            # G17 item 3: two orthogonal conditions, both required — never
            # OR, never one standing in for the other (see `_is_contained`'s
            # docstring, "all four must share this one definition"):
            #   - `is_under(...)` is the existing *lexical* scope-lock
            #     authorization — is this path string inside a span the
            #     round's scope-lock allows?
            #   - `_is_contained(file_path, project)` is *canonical*
            #     containment — does this path's real (symlink-resolved)
            #     target still land inside the project at all?
            # A file can satisfy the first while failing the second — e.g.
            # `reviews/ext.md` is lexically under `reviews/` (scope-lock
            # authorizes it) while its real target is a symlink escape out
            # of the project (fixture A). Without the AND, that file passes
            # Rule A silently even though its content is never really
            # in-project. Both conditions stay independently load-bearing:
            # dropping either one back to OR reopens a different escape
            # (scope-lock's existing project-external-path fixtures still
            # rely on the lexical half alone).
            allowed = any(
                is_under(file_path, base / span)
                for base in bases
                for span in spans
            ) and _is_contained(file_path, project)
            if not allowed:
                violations.append(
                    {
                        "round": str(round_dir),
                        "kind": "scope-lock-violation",
                        "detail": f"{file_path} is outside every allowed path in {scope_lock}",
                    }
                )

    reviews_container = sub_containers["reviews"]
    if reviews_container is not None and reviews_container.is_dir():
        for review in [f for f in sub_files["reviews"] if f.suffix == ".md"]:
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

                # PR-3 §2.4: domain is decided by text + the declared alias
                # set, before any filesystem access. A declared alias is
                # resolved *only* within its own root -- never against
                # `citation_bases`, never through `suffix_index` (G13/G14).
                # An alias-shaped-but-undeclared span (G15) falls straight
                # through to the unchanged project-domain block below; the
                # only difference there is a display-only hint naming the
                # declared aliases, appended to the same `dangling-citation`
                # it would have produced anyway.
                alias_match = ALIAS_CITATION_RE.match(cited)
                if alias_match and alias_match.group(1) in roots:
                    alias = alias_match.group(1)
                    root = roots[alias]
                    coverage["external_citations_checked"] += 1
                    if not root.available:
                        coverage["external_citations_unverifiable"] += 1
                        violations.append(
                            {
                                "round": str(round_dir),
                                "kind": "external-citation-unverifiable",
                                "detail": (
                                    f"{review} cites `{cited}` but reference root '{alias}' "
                                    f"is unavailable ({root.unavailable_reason}); run with "
                                    "--show-root-paths for the local path"
                                ),
                            }
                        )
                        continue
                    outcome = _resolve_external_with_locator(root, alias_match.group(2), cited)
                    if outcome == "resolved":
                        coverage["external_citations_resolved"] += 1
                    elif outcome == "not_found":
                        coverage["external_citations_not_found"] += 1
                        violations.append(
                            {
                                "round": str(round_dir),
                                "kind": "external-citation-not-found",
                                "detail": (
                                    f"{review} cites `{cited}` which does not exist under "
                                    f"reference root '{alias}'"
                                ),
                            }
                        )
                    else:
                        coverage["external_citations_rejected"] += 1
                        violations.append(
                            {
                                "round": str(round_dir),
                                "kind": "external-citation-rejected",
                                "detail": (
                                    f"{review} cites `{cited}` which reference root '{alias}' "
                                    "rejects (traversal, symlink escape, or outside its "
                                    "declared subpaths)"
                                ),
                            }
                        )
                    continue

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
                    elif alias_match is not None:
                        # G15: this span was alias-*shaped* but its alias was
                        # never declared -- resolved (or not) exactly like
                        # any other project-relative string above; this is a
                        # display-only note, not a different verdict.
                        declared = ", ".join(sorted(roots)) if roots else "(none)"
                        hint = (
                            f" — `@@{alias_match.group(1)}` is not a declared "
                            f"reference-root alias; declared: {declared}"
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
        # PR-3 (external-citation-base-spec-20260727.md §2.7): the two
        # `external_roots_*` fields are project-level and assigned exactly
        # once by `verify_project`, *after* its round loop -- never
        # accumulated per round. They live in this same dict (so G18's
        # coverage-key <-> SKILL.md IN-column check still sees them, and so
        # every round's local `coverage = _empty_coverage()` has the keys
        # too) but every round leaves them at 0; `verify_project`'s
        # per-round accumulation loop therefore only ever adds 0 to them,
        # and the real values are plain-assigned once after that loop.
        "external_roots_declared": 0,
        "external_roots_available": 0,
        "external_citations_checked": 0,
        "external_citations_resolved": 0,
        "external_citations_not_found": 0,
        "external_citations_rejected": 0,
        "external_citations_unverifiable": 0,
    }


def verify_project(project: Path) -> tuple[list[dict], dict]:
    goals_dir = project / ".harnessloop" / "goals"
    coverage = _empty_coverage()
    if not goals_dir.is_dir():
        return [], coverage
    violations: list[dict] = []

    # G17 item 1 (external-citation-base-spec-20260727.md §3.1): the
    # container chain is checked top-down, level by level, *before* the
    # next level down is ever listed — `goals_dir` itself here, then each
    # `goal_dir`, then each `round_dir` below. `evidence`/`reviews` are the
    # two remaining levels, checked inside `verify_round` once a clean
    # `round_dir` reaches it. This replaces the previous single
    # `goals_dir.glob("*/rounds/*")` walk (which would transparently follow
    # a symlink at any of these levels the moment it opened the directory)
    # with explicit per-level iteration so each level can be
    # containment-checked before it is opened at all — a goal or round
    # directory that is itself a symlink escape (fixture C:
    # `rounds/0001 -> <outside>`) is reported and skipped without ever
    # calling `.iterdir()` / `.rglob()` on it, including the round's own
    # `scope-lock.md` and `decision.md` (fixture C's repro showed the whole
    # round, scope-lock included, being read from outside the project).
    # This check stays first and its early return unconditional (PR-3 must
    # not touch this G17 invariant): if the goals directory itself escapes,
    # nothing else in the project -- including reference-root declarations
    # -- is read.
    escape = _container_escape_violation(goals_dir, project, goals_dir)
    if escape is not None:
        return [escape], coverage

    # PR-3: load declared external reference roots once per run (G5: every
    # run re-validates, never "validated once and trusted"). `roots` is
    # threaded into every `verify_round` call below so each round resolves
    # its `@@alias/...` citations against the same, single load. Violations
    # from the declaration itself (G1/G2/G4/G5/G6) are project-level, added
    # once here; `external-root-unavailable` (G7) is added once per
    # unavailable alias, also project-level, immediately below.
    roots, root_violations = load_reference_roots(project, verify_identity=True)
    violations.extend(root_violations)
    for alias, root in roots.items():
        if not root.available:
            violations.append(
                {
                    "round": str(project),
                    "kind": "external-root-unavailable",
                    "detail": (
                        f"reference root '{alias}' is unavailable "
                        f"({root.unavailable_reason}); every citation using this alias "
                        "will be reported external-citation-unverifiable"
                    ),
                }
            )

    # Built once per project run (not per round/citation) — see
    # `build_suffix_index` for why this matters for performance.
    suffix_index = build_suffix_index(project)
    for goal_dir in sorted(p for p in goals_dir.iterdir() if p.is_dir()):
        escape = _container_escape_violation(goal_dir, project, goal_dir)
        if escape is not None:
            violations.append(escape)
            continue
        rounds_dir = goal_dir / "rounds"
        if not rounds_dir.is_dir():
            continue
        for round_dir in sorted(rounds_dir.iterdir()):
            escape = _container_escape_violation(round_dir, project, round_dir)
            if escape is not None:
                violations.append(escape)
                continue
            if not round_dir.is_dir():
                continue
            round_violations, round_coverage = verify_round(project, round_dir, suffix_index, roots)
            violations.extend(round_violations)
            for key in coverage:
                coverage[key] += round_coverage[key]

    # PR-3 §2.7: project-level, single assignment *after* the round loop --
    # every round's own `coverage["external_roots_*"]` stayed 0 (see
    # `_empty_coverage`'s comment), so the accumulation loop above added 0
    # to these keys regardless of round count; this plain assignment is the
    # only place they are ever set, so they are never multiplied by the
    # number of rounds.
    coverage["external_roots_declared"] = len(roots)
    coverage["external_roots_available"] = sum(1 for r in roots.values() if r.available)
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
            "treated as resolved). A trailing :<line>, :<start>-<end> (optionally repeated "
            "as a comma-separated multi-range, e.g. :44-46,443-507), or ::<anchor> "
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
    # PR-3 §2.7 safety constraint: violation detail, the coverage line, and
    # --json never print a reference root's local path (G20). This is a
    # separate, additional, human-output-only section -- deliberately not
    # a verdict-changing knob (G19: this repo's argparse must never grow an
    # allow-missing/skip-roots/no-external-style option that would let an
    # unavailable or rejected root quietly stop failing); it has no effect
    # at all under --json, so the JSON schema whitelist stays exactly what
    # it was without this flag.
    parser.add_argument(
        "--show-root-paths",
        action="store_true",
        help=(
            "Also print each declared reference-root alias's raw local path "
            "(from .harnessloop/local/reference-roots.local.json), for "
            "debugging an unavailable/rejected root. Human output only; "
            "never changes exit code, violations, or coverage, and has no "
            "effect under --json."
        ),
    )
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
            f"review_digest_declared={coverage['rounds_review_digest_declared']} "
            f"external_roots_declared={coverage['external_roots_declared']} "
            f"external_roots_available={coverage['external_roots_available']} "
            f"external_citations_checked={coverage['external_citations_checked']} "
            f"external_citations_resolved={coverage['external_citations_resolved']} "
            f"external_citations_not_found={coverage['external_citations_not_found']} "
            f"external_citations_rejected={coverage['external_citations_rejected']} "
            f"external_citations_unverifiable={coverage['external_citations_unverifiable']}"
        )
        if args.show_root_paths:
            # Deliberately the *only* place a reference root's local path is
            # ever printed (G20 pins violation detail / coverage line /
            # --json to alias-only; this flag is the documented escape
            # valve those three point at, and it prints nothing else).
            bindings, _local_error = _load_local_bindings(project / REFERENCE_ROOTS_LOCAL_REL)
            _roots, _violations = load_reference_roots(project, verify_identity=True)
            print("reference root local paths (--show-root-paths):")
            if not _roots:
                print("  (no reference roots declared)")
            for alias in sorted(_roots):
                raw = bindings.get(alias)
                print(f"  {alias}: {raw if raw else '(unbound)'}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
