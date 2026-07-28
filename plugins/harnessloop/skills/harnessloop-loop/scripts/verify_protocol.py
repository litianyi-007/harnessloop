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

- RAE (round-acceptance-eval) gate: `<goal>/evals.json` (today's registry,
  see `check_goal_eval_registry`) and a round's own
  `evidence/runtime/acceptance-evals.json` ledger (see
  `check_round_eval_ledger`) are each validated only against their own
  internal legitimacy — never against each other, and never against any
  other round or goal (deliberately no cross-time-layer join). One hard
  rule ties a round's own ledger to that same round's own `decision.md`:
  every eval_id in the ledger's `frozen_due_set` must have an
  `outcome == "pass"` entry somewhere in that same ledger, or the round's
  `Feedback` may not be `positive` (`acceptance-eval-positive-without-pass`).
  `Feedback` is read with the same `- <label>:` convention as
  `parse_review_fields`/E4, then normalized (`_normalize_feedback`)
  fail-closed: a value that does not land in the known
  positive/negative/neutral/blocked set after only whitespace/case
  normalization is `acceptance-eval-feedback-unparsable`, never silently
  treated as "not positive" (this project's own decision.md files routinely
  carry full-width punctuation, and silently waving that through was a
  measured defect). See `check_round_eval_ledger`'s docstring for the two
  upper bounds this gate does not close: a missing ledger produces zero
  violations from this rule, and `frozen_due_set` is trusted as self-reported
  by the very round being checked — this gate confirms internal
  self-consistency, never that the due set is complete.

- Acceptance-eval declaration gate (second RAE vertical slice; see
  `check_acceptance_eval_declaration`): narrows the upper bound above —
  "a round with no ledger produces zero violations from the RAE hard
  rule" — without ever joining across time layers. A round's
  `decision.md` may optionally declare `- Acceptance evals: ran` or
  `- Acceptance evals: none — <reason>`; this gate checks that
  declaration for self-consistency against that **same round's own**
  ledger presence (`check_round_eval_ledger`'s `state["present"]`) —
  never `<goal>/evals.json`'s `activation_round`, which would require
  joining today's goal-level registry against this round's evidence and
  was measured and withdrawn as infeasible (see the consuming project's
  `docs/runtime-evals-interface-contract-v5-20260728.md` §0/§6). Both
  operands — the decision.md text and the ledger-presence flag — come
  from round N only, so this stays a same-round check exactly like B2a
  above, never a cross-round or cross-goal one. The field is read with
  the same `- <label>:` convention as `parse_review_fields`/`parse_feedback`
  (case-insensitive prefix, first occurrence wins), then normalized
  fail-closed with exactly `.strip().lower()` — no punctuation stripped,
  same discipline as `_normalize_feedback` — and its `none — <reason>`
  shape is parsed with the *same* `REVIEW_NONE_RE` regex `check_review_
  declaration` already uses for `Review: none — <reason>`, not a second,
  subtly different pattern. A value landing in neither the `ran` nor the
  `none — <reason>` shape is `acceptance-eval-declaration-unparsable`,
  never silently treated as absent. See `check_acceptance_eval_declaration`'s
  docstring for the full eight-row judgment table. The one upper bound
  this narrowing deliberately leaves open, restated in
  `harnessloop-loop/SKILL.md`'s OUT column: this field is optional, and a
  round that writes **neither** the field **nor** the ledger produces
  zero violations from this gate too — it can guarantee "once you
  declare, you must be self-consistent", never "you must declare".

- Loop-predecessor gate (batch 2 of `docs/loop-stop-record-spec-20260728.md`,
  reversed per that spec's Appendix F; see `check_loop_predecessor_declaration`):
  `decision.md` may optionally declare `- Predecessor: <NNNN>`. Appendix F
  found the original forward-reference design (a round declaring
  `continued: <successor>`) structurally unwritable — the successor round
  does not exist yet when the predecessor round closes and the mechanical
  gate runs — and reversed the direction: the *successor* round names its
  own predecessor instead, a reference that is always to an already-closed,
  already-frozen round. Two constraints only (Appendix F.2's five-to-two
  collapse): the named round must exist under this same goal's `rounds/`
  (`loop-predecessor-missing`), and its number must be strictly less than
  this round's own (`loop-predecessor-not-backward` — pure arithmetic, no
  cycle check needed, since a strictly-decreasing reference cannot cycle).
  A value that is not exactly four digits is `loop-predecessor-invalid-value`.
  Absence is silent (zero-migration, exactly like `- Acceptance evals:`) —
  this gate can only guarantee "once declared, self-consistent", never
  "must be declared"; see `harnessloop-loop/SKILL.md`'s OUT column for the
  registered consequence.

- Loop-continuation record gate (batch 2 of the same spec, §3; see
  `check_loop_continuation_declaration`): `decision.md` may optionally
  declare `- Loop continuation: stopped: <reason>[ — <free-text note>]`.
  This is a record, not a judgment — the spec's §1.2/§3.2 argue at length
  that a mechanical gate cannot tell a genuine stopping reason from one an
  agent invented to look compliant, so this gate checks only that
  `<reason>` normalizes to one of a fixed enum (protocol Stop conditions,
  contract Auto-Continue/Stop-Conditions vocabulary, plus `budget-checkpoint`
  / `user-interrupt` / the honesty label `unjustified-stop`) —
  `loop-continuation-invalid-value` otherwise, fail-closed exactly like
  `_normalize_acceptance_eval_declaration` (a value that merely resembles a
  valid one, e.g. trailing full-width punctuation, is reported, never
  silently read as absent). `unjustified-stop` is a legal value, not a
  violation (the spec's point: judging it red would only punish the honest
  agent who wrote it) — it is tracked instead in its own coverage counter,
  `rounds_stop_unjustified`, so it is a visible review signal rather than an
  invisible pass. The optional free-text note after ` — ` is never content-
  checked.

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

# A CommonMark fenced-code-block delimiter line: 0-3 leading spaces (4+ is
# an indented code block, a different construct entirely -- see
# `_uncoded_lines`'s "known gap" paragraph), then a run of 3+ backticks or
# 3+ tildes, then whatever remains on the line (an opening fence's optional
# info string, e.g. "json" in "```json" -- or, for a candidate *closing*
# line, text that -- per CommonMark -- disqualifies it from closing at all;
# see `_uncoded_lines`). Group 1 is the fence run itself (its first
# character gives the fence *type*, backtick vs tilde; its length is the
# minimum a same-type closing run must meet or exceed). Group 2 is
# everything after the run. This regex only detects "is this line
# fence-marker-shaped at all" -- whether a given match opens or closes a
# fence is a stateful decision `_uncoded_lines` makes, not this regex.
FENCE_MARKER_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

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

# RAE (round-acceptance-eval) gate: `<goal>/evals.json` and
# `<round>/evidence/runtime/acceptance-evals.json` (see `check_goal_eval_registry`,
# `check_round_eval_ledger`, and the "acceptance-eval-positive-without-pass"
# hard rule wired into `verify_round`). `RAE_EVAL_ID_RE` is shared by both
# files: an eval_id in the goal-level registry and a frozen_due_set element
# in a round ledger are the same identifier shape.
RAE_EVAL_ID_RE = re.compile(r"^RAE-[0-9]{4}$")

# A ledger `attempt_id`: exactly 4 digits (the round directory name it must
# match), a literal `-a`, then 1-3 digits (the attempt number). The first
# group is captured only so the round-prefix comparison in
# `check_round_eval_ledger` does not have to re-slice the string; the regex
# match itself is what proves the shape, not the slice.
ATTEMPT_ID_RE = re.compile(r"^([0-9]{4})-a[0-9]{1,3}$")

# The closed enum a ledger entry's `outcome` field must land in. Any other
# value (including a near-miss like `"Pass"` or `"passed"`) is
# `eval-ledger-invalid-outcome` -- this rule does not normalize case or
# guess intent, unlike `_normalize_feedback` below, which exists specifically
# because `Feedback:` prose is human-authored and `outcome` is not.
LEDGER_OUTCOMES = frozenset({"pass", "fail", "error", "skipped"})

# The closed enum a decision.md `Feedback:` value must normalize to (see
# `_normalize_feedback`). Matches `decision-template.md`'s documented set.
FEEDBACK_KNOWN_VALUES = frozenset({"positive", "negative", "neutral", "blocked"})

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
    {"alias", "purpose", "expect_present", "subpaths", "approved_by", "nested_under"}
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


# TH-0026 (evolution-issues/0026-scope-lock-nonexistent-path-silent-zero-coverage.md):
# a scope-lock span that drops the `goals/<goal-slug>/` segment out of a
# round's own real path (e.g. `.harnessloop/rounds/0008/` instead of the real
# `.harnessloop/goals/<goal>/rounds/0008/`) authorizes a location Rule A never
# finds a single file under -- silent zero coverage, exit 0, nobody told (two
# real instances found in this repo's own history: rounds/0008 and
# rounds/0009). `<NNNN>` is this repo's round-directory naming convention
# (exactly four digits, zero-padded).
ROUND_SEGMENT_RE = re.compile(r"^\d{4}$")


def _span_path_segments(span: str) -> list[str]:
    """Split a scope-lock span into path segments for *segment-wise*
    comparison, never string-wise (G31d: a span prefix like `xgoals/<goal>`
    must never be treated as a match for `goals/<goal>` merely because the
    raw characters happen to line up at the end of the string -- `xgoals`
    and `goals` are different segments, not one a substring of the other by
    coincidence at a path boundary).

    Empty segments (from a leading `/`, a trailing `/`, or a doubled `//`)
    and bare `.` segments carry no positional information for the suffix
    comparison this feeds and are dropped.
    """
    return [seg for seg in span.split("/") if seg not in ("", ".")]


def scope_lock_round_path_mismatch(span: str, round_dir: Path, project: Path) -> str | None:
    """TH-0026: detect a scope-lock span that names *this* round's number
    but whose path prefix does not match this round's own real directory
    path.

    Both operands live entirely at round `round_dir.name`'s own layer: the
    span's text (from this round's own scope-lock.md) and this round's own
    directory name / its parent goal directory's own name. This function
    never touches the filesystem beyond that -- in particular it never
    checks whether the span's path actually exists on disk. That check
    would be a `(today layer, round N)` join: today's disk state (has
    anything been renamed or deleted since this round closed?) is not a
    property of round N, and joining the two would retroactively flip an
    already-closed round red the moment an unrelated future cleanup
    touches an unrelated directory -- exactly the trap this issue's own
    "陷阱" section rules out (the class of judgment two independent 2026-07-28
    reviews withdrew from the v5 runtime-evals contract; see v0.12.0's E1
    discipline for the same principle applied elsewhere in this file).

    Algorithm (the issue's worked table is the source of truth for every
    branch below):
      1. Find the first `rounds/<NNNN>` pair of *adjacent* path segments in
         `span` (`<NNNN>` exactly four digits). No such pair -> None (this
         rule has nothing to say about the span; most spans are not
         round-shaped at all, e.g. `app/kernel-client/foo.md`).
      2. `<NNNN>` must equal `round_dir.name` exactly. A span naming a
         *different* round is left alone -> None -- it may legitimately
         cite that other round's own artifacts (the issue's OUT-list item
         2); this rule cannot distinguish a deliberate cross-round
         reference from a typo, so it does not try.
      3. The span's prefix (the segments before the matched `rounds/<NNNN>`
         pair) is compared, segment by segment, against this round's real
         path prefix relative to `project`
         (`round_dir.parent.parent.relative_to(project)`, e.g.
         `.harnessloop/goals/<slug>`). An *empty* span prefix (a bare
         `rounds/0008/...` span with nothing before it) is treated as a
         suffix of anything -- under-specified, not provably wrong, and
         already covered by every base `verify_round` tries (`project`,
         `goal_dir`, `round_dir`).
      4. If the span's prefix is a path-segment suffix of the round's real
         prefix, the span is fine (whether it spells out the full real
         prefix, a `goals/<slug>`-relative form, or is empty) -> None.
         Otherwise, this is the misspelled shape the issue describes: return
         a human-readable note. The caller decides what to do with it
         (TH-0026: hint-only -- never a violation, never touches exit code).
    """
    segments = _span_path_segments(span)
    match_index = None
    for i in range(len(segments) - 1):
        if segments[i] == "rounds" and ROUND_SEGMENT_RE.match(segments[i + 1]):
            match_index = i
            break
    if match_index is None:
        return None

    round_name = round_dir.name
    if segments[match_index + 1] != round_name:
        return None

    span_prefix = segments[:match_index]
    if not span_prefix:
        return None

    goal_dir = round_dir.parent.parent
    try:
        round_prefix = list(goal_dir.relative_to(project).parts)
    except ValueError:
        # goal_dir not actually under project -- cannot judge; never crash a
        # hint-only check over this (see module discipline: hints degrade
        # to silence, never to an exception that would take the real gate
        # down with them).
        return None

    is_suffix = (
        len(span_prefix) <= len(round_prefix)
        and round_prefix[len(round_prefix) - len(span_prefix) :] == span_prefix
    )
    if is_suffix:
        return None

    return (
        f"round {round_name}: scope-lock Allowed Changes span '{span}' names this "
        f"round, but its path prefix '{'/'.join(span_prefix)}' is not this round's "
        f"real directory prefix '{'/'.join(round_prefix)}' (real path: "
        f"{(goal_dir / 'rounds' / round_name)})"
    )


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


def _carries_active_ignore(line: str) -> bool:
    """Whether `line` *uses* the ignore marker, as opposed to *mentioning* it.

    `IGNORE_MARKER in line` is a substring test, so a line that merely quotes
    the marker inside a code span -- a review documenting the exemption
    mechanism, or this protocol's own spec being scanned as a review --
    silently exempted every citation on that line. Live false green,
    reproduced: a line containing both `` `<!-- verify:ignore -->` `` and a
    dangling path reported zero citations checked and two "ignored".

    The fix is deliberately minimal: code spans are stripped before the
    substring test, so quoted text stops acting as an instruction. The
    marker's *scope* (this line and the next) is untouched -- that is a
    separate question, and the whole prose-marker mechanism is slated for
    replacement by out-of-band `citation-exemptions.json` declarations
    (docs/ignore-scoping-spec-20260728.md v4), which removes this and three
    other failure modes at once rather than patching each.

    Known residual, accepted for now: a marker inside a *fenced* code block
    still counts as active. Fence tracking is a larger change to a mechanism
    already scheduled for removal, and the corpus contains no such case
    (measured 2026-07-28). Inline code spans are the form that actually
    occurs when someone writes about the marker mid-sentence.
    """
    return IGNORE_MARKER in CODE_SPAN.sub("", line)


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
    active = [_carries_active_ignore(l) for l in lines]
    for i, line in enumerate(lines):
        if active[i] or (i > 0 and active[i - 1]):
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
    `"rejected"`, `"identity-mismatch"`, `"shadow-alias"`,
    `"undeclared-nesting"`, `"nesting-mismatch"`, or `None` (only when
    available) —
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
        "nested_under",
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
        nested_under: str | None,
        canonical: Path | None,
        available: bool,
        unavailable_reason: str | None,
    ) -> None:
        self.alias = alias
        self.purpose = purpose
        self.expect_present = expect_present
        self.subpaths = subpaths
        self.approved_by = approved_by
        self.nested_under = nested_under
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
            or not subpaths
            or not all(isinstance(p, str) and p.strip() and "/" not in p for p in subpaths)
        ):
            # An explicit empty list is rejected rather than silently read as
            # "no whitelist": `[]` reads as deny-all to a human and was
            # truthiness-collapsed into unrestricted by the loader. Omit the
            # key for unrestricted; there is no deny-all spelling (a root
            # nothing may be read from is a root that should not be declared).
            return [], (
                f"{path}: roots[{i}].subpaths, if present, must be a non-empty list of "
                "single-segment names (omit the key for no restriction; `[]` is not a "
                "deny-all spelling)"
            )

        approved_by = raw.get("approved_by")
        if not isinstance(approved_by, str) or not approved_by.strip():
            return [], f"{path}: roots[{i}].approved_by must be a non-empty string"

        nested_under = raw.get("nested_under")
        if nested_under is not None and (
            not isinstance(nested_under, str) or not ALIAS_RE.match(nested_under)
        ):
            return [], (
                f"{path}: roots[{i}].nested_under, if present, must be an alias matching "
                f"{ALIAS_RE.pattern}"
            )
        if nested_under == alias:
            return [], f"{path}: roots[{i}].nested_under names its own alias {alias!r}"

        entries.append(
            {
                "alias": alias,
                "purpose": purpose,
                "expect_present": tuple(expect_present),
                "subpaths": tuple(subpaths) if subpaths is not None else None,
                "approved_by": approved_by,
                "nested_under": nested_under,
            }
        )

    # `nested_under` is the one cross-entry reference in this schema, so it is
    # resolved after every alias is known. A dangling target, or a cycle, is a
    # whole-file schema error (all-or-nothing, like every other problem here) --
    # a half-loaded declaration is exactly the ambiguity §2.2 exists to prevent.
    declared_aliases = {e["alias"] for e in entries}
    for e in entries:
        target = e["nested_under"]
        if target is not None and target not in declared_aliases:
            return [], (
                f"{path}: roots[?].nested_under names {target!r}, which is not a declared alias"
            )
    parent_of = {e["alias"]: e["nested_under"] for e in entries}
    for start in parent_of:
        seen_chain = {start}
        cur = parent_of[start]
        while cur is not None:
            if cur in seen_chain:
                return [], f"{path}: nested_under forms a cycle involving alias {start!r}"
            seen_chain.add(cur)
            cur = parent_of.get(cur)
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
        bound_at = binding.get("bound_at")
        if bound_at is not None and (not isinstance(bound_at, str) or not bound_at.strip()):
            return {}, (
                f"{path}: bindings[{alias!r}].bound_at, if present, must be a "
                "non-empty string"
            )
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
        nested_under=entry["nested_under"],
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


def _same_dir(a: Path, b: Path, *, on_error: bool = True) -> bool:
    """Whether two canonical paths name one directory on this filesystem.

    `os.path.samefile` (st_dev, st_ino) rather than `==`: `Path.__eq__` is
    string equality and `Path.resolve()` does not case-normalize, so on a
    case-insensitive volume one directory has many unequal canonical
    spellings.

    `on_error` is what an unanswerable comparison returns, and every caller
    passes the *fail-closed* answer. An earlier version fell back to string
    equality here, reasoning it "can only under-report sameness, never
    invent it" -- but under-reporting sameness is precisely how a shadow
    pair or an undeclared nesting slips through, so that fallback was
    fail-open in a guard whose whole job is to fail closed (T-070 residual).
    "We could not establish that these are different directories" must
    never read as "they are different".
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        return on_error


def _is_strict_descendant(child: Path, ancestor: Path) -> bool:
    """Whether `child` sits strictly below `ancestor` on this filesystem.

    Walks `child`'s parent chain comparing by `_same_dir`, not by string
    prefix, for the same reason `_same_dir` exists: `/x/Wiki` is a prefix of
    neither `/x/wiki/kernel` nor its `.parents` as strings, yet it is that
    directory's parent. Strict: a directory is never its own descendant.
    """
    for parent in child.parents:
        if _same_dir(parent, ancestor):
            return True
    return False


def _cannot_compare(a: Path, b: Path) -> bool:
    """Whether `_same_dir(a, b)` had to guess rather than measure.

    Used only to word the violation honestly: a fail-closed verdict reached
    because one of the two directories could not be stat'ed this run is a
    different fact from one reached because they genuinely share an inode,
    and a reader chasing the violation deserves to know which.
    """
    try:
        os.path.samefile(a, b)
    except OSError:
        return True
    return False


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
    # The declaration must be the versioned file itself, not a pointer to
    # somewhere else. `.harnessloop/setup/reference-roots.json` is the
    # git-committed, diff-reviewable record of which external trees this
    # project may read; if it is a symlink, what git shows a reviewer and
    # what the gate actually loads are two different files -- and the
    # target need not even be inside the project. Same discipline as
    # v0.20.0's `round-artifact-is-symlink`, applied to the one artifact
    # that decides external reach. Checked on both files: a symlinked
    # local binding file is the same escape one layer down.
    for label, candidate in (("versioned", versioned_path), ("local", local_path)):
        if candidate.is_symlink():
            violations.append(
                {
                    "round": str(project),
                    "kind": "reference-roots-invalid"
                    if label == "versioned"
                    else "reference-root-local-invalid",
                    "detail": (
                        f"{candidate.relative_to(project).as_posix()} is a symlink; the "
                        "reference-root declaration must be the tracked file itself, "
                        "not a pointer to one"
                    ),
                }
            )
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

    # G21 (shadow alias, §2.4 "禁止两 alias 指向同一 canonical root"): two
    # aliases resolving to the same canonical root is an audit-bypass face,
    # not a convenience. `reference-roots.json` is the tracked, reviewable
    # record of *what external trees this project reads*; a second alias
    # bound to an already-declared tree lets a citation read that tree under
    # a name whose `purpose`/`approved_by` were never reviewed for it.
    #
    # This must run here rather than in `_load_versioned_roots`: the tracked
    # file holds no paths at all (§2.2 zero-absolute-path), so "same root"
    # is only knowable after local binding + canonical resolution. Comparing
    # the declared strings would be the string-comparison mistake G4 already
    # has teeth against -- two different literals (one a symlink to the
    # other, `.` / `..` segments, a trailing slash) can name one directory.
    #
    # Fail-closed: every alias in a colliding group is marked unavailable,
    # matching how `rejected`/`identity-mismatch` behave. Silently keeping
    # one of them (say, the first) would make which alias survives depend on
    # declaration order -- the same "shape decides the outcome at runtime"
    # anti-pattern §2.4's last paragraph forbids.
    # Collision is decided by `os.path.samefile` (st_dev, st_ino), never by
    # comparing the canonical `Path` objects -- `Path.__eq__` is string
    # equality, and `Path.resolve()` does *not* case-normalize. On a
    # case-insensitive volume (APFS/HFS+ default, NTFS) `/x/Wiki` and
    # `/x/wiki` are one directory with two unequal canonical strings, so
    # grouping by `Path` let both aliases stay available with zero
    # violations -- the exact string-comparison mistake G4 already had
    # teeth against, repeated one layer up. Hard links, bind mounts, and
    # firmlinks are the same class and are covered by the same identity.
    live = sorted(
        ((a, r) for a, r in roots.items() if r.available and r.canonical is not None),
        key=lambda pair: pair[0],
    )
    groups: list[list[str]] = []
    assigned: dict[str, int] = {}
    for i, (alias_i, root_i) in enumerate(live):
        if alias_i in assigned:
            continue
        idx = len(groups)
        groups.append([alias_i])
        assigned[alias_i] = idx
        for alias_j, root_j in live[i + 1 :]:
            if alias_j in assigned:
                continue
            if _same_dir(root_i.canonical, root_j.canonical):
                groups[idx].append(alias_j)
                assigned[alias_j] = idx
    for group in sorted(
        (sorted(g) for g in groups if len(g) > 1),
        key=lambda g: g[0],
    ):
        for alias in group:
            old = roots[alias]
            roots[alias] = ReferenceRoot(
                alias=old.alias,
                purpose=old.purpose,
                expect_present=old.expect_present,
                subpaths=old.subpaths,
                approved_by=old.approved_by,
                nested_under=old.nested_under,
                canonical=None,
                available=False,
                unavailable_reason="shadow-alias",
            )
        violations.append(
            {
                "round": str(project),
                "kind": "reference-root-shadow-alias",
                # G20: aliases only -- naming the shared directory here would
                # leak an absolute host path into a violation detail.
                "detail": (
                    f"reference roots {group} resolve to the same root "
                    "(shadow alias; forbidden by the one-alias-one-root rule); "
                    "all of them are marked unavailable"
                    + (
                        " — note: at least one pair could not be compared "
                        "(the directory could not be stat'ed this run), and an "
                        "unanswerable comparison is resolved as a collision"
                        if any(
                            _cannot_compare(roots[x].canonical, roots[y].canonical)
                            for x in group
                            for y in group
                            if x < y and roots[x].canonical and roots[y].canonical
                        )
                        else ""
                    )
                ),
            }
        )

    # Nesting is allowed, but never *silently*. §7 permits one root to sit
    # inside another; §2.4 forbids shadow aliases because a second name for
    # an already-declared tree lets a citation read it under a
    # `purpose`/`approved_by` no reviewer approved for it. Undeclared nesting
    # achieves exactly that bypass without two aliases ever naming the *same*
    # directory, so the two clauses only cohere if the overlap is a declared,
    # diff-reviewable fact: a root with a declared-root ancestor must name its
    # nearest such ancestor in `nested_under`.
    #
    # Nearest, not every ancestor: in a 3-level chain a > b > c, `c` names `b`
    # and `b` names `a`, which already makes the a-c overlap visible by
    # transitivity. Requiring `c` to name both would need a list-valued key
    # for no extra reviewable information.
    #
    # Fail-closed on the *descendant* only: the ancestor's own declaration is
    # complete and correct, and once the descendant is unavailable no two
    # aliases reach one file. Marking both would punish a correctly-declared
    # root for a neighbour's omission.
    live_after_shadow = sorted(
        ((a, r) for a, r in roots.items() if r.available and r.canonical is not None),
        key=lambda pair: pair[0],
    )
    for alias, root in live_after_shadow:
        ancestors = [
            other_alias
            for other_alias, other in live_after_shadow
            if other_alias != alias and _is_strict_descendant(root.canonical, other.canonical)
        ]
        nearest = None
        if ancestors:
            # Nearest = the ancestor that is itself below every other ancestor.
            nearest = max(
                ancestors,
                key=lambda cand: sum(
                    1
                    for other in ancestors
                    if other != cand
                    and _is_strict_descendant(roots[cand].canonical, roots[other].canonical)
                ),
            )
        declared = root.nested_under
        problem = None
        if nearest is not None and declared != nearest:
            problem = (
                "reference-root-undeclared-nesting",
                (
                    f"reference root '{alias}' resolves inside declared root '{nearest}' but "
                    f"declares nested_under={declared!r}; nesting is allowed only when it is "
                    "declared in the versioned file, naming the nearest declared ancestor"
                ),
            )
        elif nearest is None and declared is not None:
            problem = (
                "reference-root-nesting-mismatch",
                (
                    f"reference root '{alias}' declares nested_under={declared!r} but does not "
                    "resolve inside that root on this machine"
                ),
            )
        if problem is not None:
            kind, detail = problem
            old_root = roots[alias]
            roots[alias] = ReferenceRoot(
                alias=old_root.alias,
                purpose=old_root.purpose,
                expect_present=old_root.expect_present,
                subpaths=old_root.subpaths,
                approved_by=old_root.approved_by,
                nested_under=old_root.nested_under,
                canonical=None,
                available=False,
                unavailable_reason="undeclared-nesting"
                if kind == "reference-root-undeclared-nesting"
                else "nesting-mismatch",
            )
            # G20: alias names only, never the host path either root lives at.
            violations.append({"round": str(project), "kind": kind, "detail": detail})
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


# ---------------------------------------------------------------------------
# RAE (round-acceptance-eval) gate. Three shapes, one hard rule, all
# operands from the same round -- deliberately no cross-time-layer join:
# `<goal>/evals.json` (today's registry, validated only against itself),
# `<round>/evidence/runtime/acceptance-evals.json` (this round's own
# ledger, validated only against itself), and the rule tying a round's own
# `decision.md` Feedback to that same round's own ledger. See
# `check_goal_eval_registry`, `check_round_eval_ledger`, and the
# `acceptance-eval-positive-without-pass` / `acceptance-eval-feedback-unparsable`
# wiring in `verify_round` below.
# ---------------------------------------------------------------------------


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """`object_pairs_hook` for `json.load`/`json.loads`: raises `ValueError`
    on the first duplicate key found in *any* JSON object in the document
    (nested objects included -- this hook runs once per `{...}` the parser
    encounters, at every nesting depth, not just the top level).

    Plain `json.loads` (no hook) silently keeps the *last* value for a
    repeated key and drops the rest without a trace -- exactly backwards for
    a gate whose entire job is to disagree with a human skimming the file:
    a reviewer reading `"outcome": "pass", ... "outcome": "fail"` in a diff
    sees both lines, but `json.loads` hands the gate only `"fail"` (or only
    `"pass"`, depending on which the parser happens to keep), so the value
    a human argues about in review and the value the gate actually checks
    can be one and the same key resolving to two different literal strings.
    This is the hook that closes that gap for both RAE JSON files (see
    `_load_strict_json`); it is not wired into any pre-existing JSON reader
    in this module (`_load_versioned_roots`, `_load_local_bindings`) --
    "只新增，不改任何已有检查的行为" means those keep their current,
    unmodified `json.loads` behavior.
    """
    seen: set[str] = set()
    result: dict = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r} in JSON object")
        seen.add(key)
        result[key] = value
    return result


def _load_strict_json(path: Path) -> tuple[object | None, str | None]:
    """Read and parse `path` as JSON, rejecting any object with a duplicate
    key at any nesting level (`_no_duplicate_keys`).

    Returns `(data, None)` on success -- `data` is whatever `json.loads`
    would have produced (a `dict`, `list`, or scalar; callers here always
    expect a top-level `dict` and check that themselves) -- or `(None,
    message)` on any failure: the file cannot be read, is not valid JSON at
    all, or contains a duplicate key. This function never raises and never
    returns partial data; it is the shared strict loader for both
    `check_goal_eval_registry` and `check_round_eval_ledger`, so a
    duplicate-key document is rejected identically by both (X1: "JSON
    语法错误 ... 必须产出违规，绝不能 except: return []" -- the caller
    turns this `(None, message)` into a violation, it is never swallowed).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read {path} ({exc})"
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"{path} is not valid JSON ({exc})"
    return data, None


def _uncoded_lines(text: str) -> list[str]:
    """Return `text`'s lines with every CommonMark fenced code block removed.

    Exists so the three `- <label>:` line-prefix parsers below
    (`parse_feedback`, `parse_review_fields`,
    `parse_acceptance_eval_declaration`) only ever see lines a human reading
    the *rendered* markdown would see as live prose -- never a line quoted
    inside a fenced code block, e.g. a decision.md embedding a literal
    example of what a `- Feedback:` line looks like. Reproduced live: a
    fenced block containing `` - Feedback: negative `` followed, outside the
    fence, by the round's actual `` - Feedback: positive `` was read by the
    "first occurrence wins" convention these parsers share as `negative`,
    silently defeating the `acceptance-eval-positive-without-pass` hard rule
    for a decision.md whose real (rendered) claim was `positive`. This is
    the *second* time this shape of bug has been fixed here -- v0.26.0 fixed
    it for the `<!-- verify:ignore -->` marker (`_carries_active_ignore`),
    but that fix strips only *inline* single-backtick spans (`CODE_SPAN`)
    and never touched this `- <label>:` family, which is why the same class
    of bug reappeared for it two versions later.

    Relationship to `CODE_SPAN` (module top): different mechanism, different
    granularity. `CODE_SPAN` strips inline, single-backtick spans
    (`` `like this` ``) that appear mid-line, and is used by
    `pathish_citations`/`_carries_active_ignore` for Rule B and the ignore
    marker. This function instead tracks *fenced* (block) code, delimited by
    dedicated marker lines, and works at line granularity: a line is either
    entirely inside a fence or entirely outside one, never partially. Inline
    spans do not open a block, and a fence marker line is not inline code --
    conflating the two mechanisms would be wrong in both directions.

    CommonMark fence rules implemented (`FENCE_MARKER_RE`, module top):

    - Both delimiter characters: a run of 3+ backticks or 3+ tildes opens a
      fence; the two are independent fence *types* -- a `~~~`-opened fence
      is not closed by any run of backticks, and a `` ``` ``-opened fence is
      not closed by any run of tildes.
    - Longer fences: the opening run's length is remembered, and a
      candidate closing run must be at least that long. A run shorter than
      the opening (e.g. a 3-backtick line inside a 4-backtick-opened fence)
      does not close it -- that line is just fenced *content*, most
      commonly itself a documentation example of a shorter fence.
    - Info strings: an opening fence may carry trailing text on the same
      line (e.g. an opening line of "```json") -- accepted and ignored. A
      *closing* fence must not carry any such trailing text: if a candidate
      closing line has anything other than whitespace after its run of
      fence characters, it does not close the fence and is instead treated
      as ordinary fenced content.
    - Indentation: a marker line (open or close) may be preceded by 0-3
      spaces, matching CommonMark's allowance for fenced code blocks.
      `FENCE_MARKER_RE` is anchored so that 4 or more leading spaces never
      match it at all -- see the "known gap" paragraph below for what that
      implies.
    - Unclosed fence at end of file: if `text` ends while still inside a
      fence, every remaining line -- there being no closing marker left to
      find -- is treated as fenced and dropped. This is a deliberate
      fail-closed choice, not an oversight: a `- <label>:` line swallowed
      this way becomes a field its caller sees as *absent*, and absence
      either trips `review-declaration-missing` (a reported violation) or,
      for the two fields that are allowed to be genuinely absent
      (`- Feedback:`, `- Acceptance evals:`), is a silent no-op that
      produces no false *positive* judgment either way. The alternative --
      treating an unclosed fence as if it had closed at EOF -- would risk
      exposing a label line the author never intended as live prose, which
      is the wrong side of "fail open vs. fail closed" for a mechanical
      gate whose entire job is to disagree with a human skimming the file.

    Known gap, deliberately not handled here (registered as a remaining
    upper bound in `harnessloop-loop/SKILL.md`'s OUT column, not silently
    left out): a 4-space-indented code block -- CommonMark's *other*
    code-block syntax, with no fence markers at all -- is invisible to this
    function. A `- <label>:` line written inside one is still read as live
    prose by every caller. Recognizing indented code blocks correctly
    requires tracking the *list-item and blockquote indentation context*
    an indented block's "4 spaces" is relative to (not the document's left
    margin) -- a materially larger change than a fence state machine, and
    out of scope for this fix.

    Returns the surviving lines in original order, with both the fence
    marker lines themselves and everything between them removed --
    `"\\n".join(_uncoded_lines(text))` is not a round-trippable
    reconstruction of the non-fenced parts of `text`, only a list of lines
    safe to feed to a `- <label>:` prefix scan.
    """
    out: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    for line in text.splitlines():
        match = FENCE_MARKER_RE.match(line)
        if fence_char is None:
            if match:
                run = match.group(1)
                fence_char = run[0]
                fence_len = len(run)
                continue
            out.append(line)
            continue
        # Inside a fence: only a same-type run at least as long as the
        # opening run, with nothing but whitespace after it, closes it.
        # Anything else -- including a shorter or differently-typed
        # marker-shaped line, or a same-type/long-enough run that still
        # carries trailing text -- is fenced content, dropped either way.
        if (
            match
            and match.group(1)[0] == fence_char
            and len(match.group(1)) >= fence_len
            and not match.group(2).strip()
        ):
            fence_char = None
            fence_len = 0
    return out


def parse_feedback(decision_text: str) -> str | None:
    """Extract the raw (not yet normalized) `- Feedback:` value from a
    decision.md.

    Same narrow convention as `parse_review_fields` and the E4 inline
    Verdict/Residuals parse: a case-insensitive `- <label>:` line prefix,
    matched against `.strip().lower()`, first occurrence wins, no prose
    parsing anywhere else in the file. Lines inside a fenced code block are
    never considered (`_uncoded_lines`) -- a decision.md quoting a `` -
    Feedback: `` line as a literal example inside a ``` ``` ``` block must
    not have that quoted value outrank the round's real, unfenced
    declaration. Returns `None` when the field was never written at all
    (outside any fence) -- the caller must not conflate this with
    `_normalize_feedback` returning `None` for a value that *was* written
    but could not be recognized; "absent" and "unparsable" are different
    facts with different consequences (absent: this rule is silent, exactly
    like a decision.md predating the field; unparsable:
    `acceptance-eval-feedback-unparsable`, a reported violation, never a
    silent skip).
    """
    for line in _uncoded_lines(decision_text):
        stripped = line.strip()
        if stripped.lower().startswith("- feedback:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _normalize_feedback(raw: str) -> str | None:
    """Normalize a raw `Feedback:` value to one of the four known tokens in
    `FEEDBACK_KNOWN_VALUES`, or `None` if it cannot be confidently
    normalized.

    Deliberately narrow: only `str.strip()` (which already treats the
    full-width ideographic space U+3000 as whitespace, verified directly --
    `"　".isspace()` is `True` on CPython) and ASCII case-folding
    (`.lower()`) are applied. No punctuation is stripped. This project's
    own decision.md files routinely carry full-width punctuation (、。－ and
    friends) around a value, and a naive normalizer that strips trailing
    punctuation to force a match would silently turn `positive。` into
    `positive` -- exactly the fail-open shape this function exists to
    refuse. Instead, a value that does not land in the known set *as-is*
    (after only whitespace/case normalization) returns `None`, and the
    caller (`verify_round`) treats that `None` as "could not determine",
    reporting `acceptance-eval-feedback-unparsable` -- never as "not
    positive, so the rule does not apply". Conflating those two would let
    a decision.md silently escape the positive-without-pass rule merely by
    having a Feedback value the parser could not read, which is the
    opposite of fail-closed.
    """
    normalized = raw.strip().lower()
    return normalized if normalized in FEEDBACK_KNOWN_VALUES else None


def check_goal_eval_registry(goal_dir: Path) -> tuple[list[dict], bool]:
    """Validate `<goal>/evals.json` against only its own internal
    legitimacy -- never against any round's data, and never against any
    other goal (T-taxonomy: this is "today's layer", not a cross-time-layer
    join; see the module-level RAE section comment above).

    Schema: `{"evals": [{"eval_id": "RAE-0001", "activation_round": 1}]}`.

    All-or-nothing, single `rae-invalid` violation, for anything that makes
    the document's *shape* untrustworthy (mirrors `_load_versioned_roots`'s
    "a single bad entry invalidates the entire file" philosophy): the file
    is not readable JSON at all, contains a duplicate key at any nesting
    level (`_load_strict_json`), the top level is not a JSON object, the top
    level declares any key other than `evals` (explicitly required by this
    gate's own spec: an unknown top-level key invalidates the whole file,
    not just that key), `evals` is not a list, or any element of `evals` is
    not itself an object. In every one of these cases exactly one
    `rae-invalid` violation is returned and no further checks run --
    reporting also `rae-duplicate-eval-id` for a document whose shape is
    already untrustworthy would be checking a document this function does
    not trust to mean anything.

    Once the shape is trustworthy, each entry is checked independently
    (itemized, not all-or-nothing -- one malformed entry does not stop the
    others from being checked, unlike the shape failures above):

    - `eval_id` must be a string matching `RAE_EVAL_ID_RE`
      (`rae-invalid-eval-id` if not -- this also catches a missing
      `eval_id`, since `dict.get` returns `None`, which is not a string).
    - `eval_id` must be unique within the file (`rae-duplicate-eval-id`).
    - `activation_round` must be an `int` and `>= 1`, with `bool` explicitly
      excluded even though `isinstance(True, int)` is `True` in Python
      (`rae-invalid-activation-round`).

    A file that does not exist produces zero violations (`文件不存在 → 不报
    违规` -- this vertical slice does not make the registry mandatory; see
    the OUT-list entry in harnessloop-loop/SKILL.md).

    Returns `(violations, present)`: `present` is whether the file exists at
    all (used by the caller, `verify_project`, to accumulate the
    `goals_eval_registry_present` coverage field -- once per goal, never
    once per round, since this file lives at the goal level and
    `verify_round` is called once per round under that goal).
    """
    path = goal_dir / "evals.json"
    if not path.is_file():
        return [], False

    data, err = _load_strict_json(path)
    if err is not None:
        return [{"round": str(goal_dir), "kind": "rae-invalid", "detail": err}], True
    if not isinstance(data, dict):
        return (
            [{"round": str(goal_dir), "kind": "rae-invalid", "detail": f"{path}: top level must be a JSON object"}],
            True,
        )
    unknown_top = set(data) - {"evals"}
    if unknown_top:
        return (
            [
                {
                    "round": str(goal_dir),
                    "kind": "rae-invalid",
                    "detail": f"{path}: unknown top-level key(s) {sorted(unknown_top)} -- only 'evals' is allowed",
                }
            ],
            True,
        )
    evals_list = data.get("evals", [])
    if not isinstance(evals_list, list):
        return (
            [{"round": str(goal_dir), "kind": "rae-invalid", "detail": f"{path}: 'evals' must be a list"}],
            True,
        )
    for i, entry in enumerate(evals_list):
        if not isinstance(entry, dict):
            return (
                [{"round": str(goal_dir), "kind": "rae-invalid", "detail": f"{path}: evals[{i}] must be an object"}],
                True,
            )

    violations: list[dict] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(evals_list):
        eval_id = entry.get("eval_id")
        if not isinstance(eval_id, str) or not RAE_EVAL_ID_RE.match(eval_id):
            violations.append(
                {
                    "round": str(goal_dir),
                    "kind": "rae-invalid-eval-id",
                    "detail": f"{path}: evals[{i}].eval_id {eval_id!r} does not match {RAE_EVAL_ID_RE.pattern}",
                }
            )
        elif eval_id in seen_ids:
            violations.append(
                {
                    "round": str(goal_dir),
                    "kind": "rae-duplicate-eval-id",
                    "detail": f"{path}: eval_id {eval_id!r} is declared more than once",
                }
            )
        else:
            seen_ids.add(eval_id)

        activation_round = entry.get("activation_round")
        if (
            isinstance(activation_round, bool)
            or not isinstance(activation_round, int)
            or activation_round < 1
        ):
            violations.append(
                {
                    "round": str(goal_dir),
                    "kind": "rae-invalid-activation-round",
                    "detail": (
                        f"{path}: evals[{i}].activation_round {activation_round!r} must be an "
                        "int >= 1 (a bool is not accepted even though isinstance(True, int) is True)"
                    ),
                }
            )
    return violations, True


def check_round_eval_ledger(round_dir: Path) -> tuple[list[dict], dict]:
    """Validate `<round>/evidence/runtime/acceptance-evals.json` against
    only this round's own internal self-consistency.

    Schema: `{"entries": [{"eval_id": "RAE-0001", "attempt_id": "0003-a1",
    "outcome": "pass", "frozen_due_set": ["RAE-0001"]}]}`.

    All-or-nothing, single `eval-ledger-invalid` violation (same philosophy
    as `check_goal_eval_registry`'s `rae-invalid`), when the document's
    shape itself is untrustworthy: unreadable/invalid JSON or a duplicate
    key at any nesting level (`_load_strict_json`), top level not an
    object, top level declares any key other than `entries`, `entries` not
    a list, or any element of `entries` not itself an object.

    Once the shape is trustworthy, each entry is checked independently and
    itemized:

    - `attempt_id` must be a string matching `ATTEMPT_ID_RE`
      (`eval-ledger-invalid-attempt-id`), and its leading 4-digit group must
      equal `round_dir.name` (`eval-ledger-attempt-id-round-mismatch`) --
      this is a purely lexical, round-local comparison (the ledger's own
      attempt IDs against the directory name it lives in), never a
      cross-round join.
    - `outcome` must be one of `LEDGER_OUTCOMES`
      (`eval-ledger-invalid-outcome`).
    - `frozen_due_set` must be present as a key at all -- **always
      required**, even if the value is `[]` -- (`eval-ledger-frozen-due-set-missing`
      when the key itself is absent); when present it must be a list of
      strings (`eval-ledger-frozen-due-set-invalid-type`), each matching
      `RAE_EVAL_ID_RE` (`eval-ledger-frozen-due-set-invalid-element`).
    - Every entry's `frozen_due_set` must be identical to every other
      entry's in this same ledger, compared as sets (order-insensitive --
      "到期集合" is a set, not a sequence) -- `eval-ledger-frozen-due-set-inconsistent`
      when two entries disagree. Only checked across entries whose own
      `frozen_due_set` was itself well-shaped; an entry already flagged
      `-missing` or `-invalid-type`/`-invalid-element` does not also
      contribute a second, redundant inconsistency violation.

    A file that does not exist produces zero violations from this
    function -- deliberately: "账本文件缺席 ⇒ 本规则零违规" is one of the
    two upper bounds this vertical slice registers in
    harnessloop-loop/SKILL.md's OUT column, not a gap this function closes.

    Returns `(violations, state)`. `state` keys: `present` (bool, whether
    the file exists at all -- backs the `rounds_eval_ledger_present`
    coverage field), `entries_checked` (int, the number of entries this
    ledger declared, once its shape was trustworthy enough to count --
    backs `eval_entries_checked`), `due_set` (`frozenset[str] | None`: the
    single canonical `frozen_due_set` shared by every entry -- an empty
    frozenset when the ledger declares zero entries, which is vacuously
    consistent, not undetermined -- or `None` when it genuinely could not
    be determined: the ledger is absent, shape-invalid, or its entries
    disagree with each other), and `entries` (the raw,
    already-validated-as-objects list of entry dicts, or `None`).
    `verify_round`'s positive-without-pass rule reads
    `due_set`/`entries` and does nothing when `due_set` is `None` -- it does
    not re-derive a due set some other way, and it never reports a second,
    speculative violation on top of whatever `-invalid`/`-inconsistent`
    violation this function already reported for the same root cause.

    What this function does **not** decide, restated at the one place a
    reader is most likely to look for it: whether `frozen_due_set` is
    *complete* -- i.e., whether some eval that *should* have come due this
    round is missing from it entirely. `frozen_due_set` is written by the
    same round this function is checking; this function only proves the
    ledger agrees with itself about what it claims is due, never that the
    claim is honest (second OUT-list upper bound).
    """
    path = round_dir / "evidence" / "runtime" / "acceptance-evals.json"
    state: dict = {"present": False, "entries_checked": 0, "due_set": None, "entries": None}
    if not path.is_file():
        return [], state
    state["present"] = True

    data, err = _load_strict_json(path)
    if err is not None:
        return [{"round": str(round_dir), "kind": "eval-ledger-invalid", "detail": err}], state
    if not isinstance(data, dict):
        return (
            [{"round": str(round_dir), "kind": "eval-ledger-invalid", "detail": f"{path}: top level must be a JSON object"}],
            state,
        )
    unknown_top = set(data) - {"entries"}
    if unknown_top:
        return (
            [
                {
                    "round": str(round_dir),
                    "kind": "eval-ledger-invalid",
                    "detail": f"{path}: unknown top-level key(s) {sorted(unknown_top)} -- only 'entries' is allowed",
                }
            ],
            state,
        )
    entries_list = data.get("entries", [])
    if not isinstance(entries_list, list):
        return (
            [{"round": str(round_dir), "kind": "eval-ledger-invalid", "detail": f"{path}: 'entries' must be a list"}],
            state,
        )
    for i, entry in enumerate(entries_list):
        if not isinstance(entry, dict):
            return (
                [{"round": str(round_dir), "kind": "eval-ledger-invalid", "detail": f"{path}: entries[{i}] must be an object"}],
                state,
            )

    state["entries_checked"] = len(entries_list)
    state["entries"] = entries_list
    round_label = round_dir.name

    violations: list[dict] = []
    clean_due_sets: list[frozenset] = []
    for i, entry in enumerate(entries_list):
        attempt_id = entry.get("attempt_id")
        if not isinstance(attempt_id, str) or not ATTEMPT_ID_RE.match(attempt_id):
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "eval-ledger-invalid-attempt-id",
                    "detail": f"{path}: entries[{i}].attempt_id {attempt_id!r} does not match {ATTEMPT_ID_RE.pattern}",
                }
            )
        else:
            prefix = attempt_id.split("-", 1)[0]
            if prefix != round_label:
                violations.append(
                    {
                        "round": str(round_dir),
                        "kind": "eval-ledger-attempt-id-round-mismatch",
                        "detail": (
                            f"{path}: entries[{i}].attempt_id {attempt_id!r} does not belong to "
                            f"round {round_label!r} (leading 4 digits must equal the round directory name)"
                        ),
                    }
                )

        outcome = entry.get("outcome")
        if outcome not in LEDGER_OUTCOMES:
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "eval-ledger-invalid-outcome",
                    "detail": f"{path}: entries[{i}].outcome {outcome!r} is not one of {sorted(LEDGER_OUTCOMES)}",
                }
            )

        if "frozen_due_set" not in entry:
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "eval-ledger-frozen-due-set-missing",
                    "detail": f"{path}: entries[{i}] is missing required field 'frozen_due_set' (always required, even as [])",
                }
            )
            continue
        due = entry["frozen_due_set"]
        if not isinstance(due, list) or not all(isinstance(d, str) for d in due):
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "eval-ledger-frozen-due-set-invalid-type",
                    "detail": f"{path}: entries[{i}].frozen_due_set must be a list of strings",
                }
            )
            continue
        bad_elements = [d for d in due if not RAE_EVAL_ID_RE.match(d)]
        if bad_elements:
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "eval-ledger-frozen-due-set-invalid-element",
                    "detail": f"{path}: entries[{i}].frozen_due_set contains invalid eval_id(s) {bad_elements}",
                }
            )
            continue
        clean_due_sets.append(frozenset(due))

    if entries_list and len(clean_due_sets) == len(entries_list):
        distinct = {frozenset(s) for s in clean_due_sets}
        if len(distinct) > 1:
            violations.append(
                {
                    "round": str(round_dir),
                    "kind": "eval-ledger-frozen-due-set-inconsistent",
                    "detail": f"{path}: entries disagree on frozen_due_set -- this ledger's due set must be one single set",
                }
            )
        else:
            state["due_set"] = next(iter(distinct))
    elif not entries_list:
        # A ledger declaring zero entries has no frozen_due_set to disagree
        # about -- vacuously a single, empty canonical due set, not "cannot
        # determine". `entries_checked` is already 0 (see above), so this
        # is honestly reported as "0 entries, 0 due" rather than "unknown".
        state["due_set"] = frozenset()

    return violations, state


def parse_review_fields(decision_text: str) -> dict[str, str | None]:
    """Extract the four B2a review-declaration fields from a decision.md.

    Same narrow convention as the existing Verdict/Residuals (E4) check:
    a case-insensitive `- <label>:` line prefix, matched against
    `.strip().lower()`, first occurrence wins, no prose parsing anywhere
    else in the file is consulted. Lines inside a fenced code block are
    never considered either (`_uncoded_lines`) — a decision.md quoting one
    of these four fields as a literal example inside a fenced block must
    not have that quoted value outrank a real, unfenced declaration
    elsewhere in the file. A key's value is `None` when the field was never
    written at all (outside any fence) — this is how
    `check_review_declaration` tells "field absent" (a
    `review-declaration-missing` violation) apart from "field present but
    its value turns out to be invalid" (a different, more specific
    violation kind).

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
    for line in _uncoded_lines(decision_text):
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


# Acceptance-eval declaration gate (second RAE vertical slice; see the module
# docstring's "Acceptance-eval declaration gate" section and
# `check_acceptance_eval_declaration` below). `ACCEPTANCE_EVAL_RAN_TOKEN` is
# the exact (post `.strip().lower()`) value that means "this round ran its
# acceptance evals" -- a module-level constant so the one literal string is
# never duplicated between the normalizer and anything that tests it.
ACCEPTANCE_EVAL_RAN_TOKEN = "ran"


def parse_acceptance_eval_declaration(decision_text: str) -> str | None:
    """Extract the raw (not yet normalized) `- Acceptance evals:` value from
    a decision.md.

    Same narrow convention as `parse_feedback` and `parse_review_fields`/E4:
    a case-insensitive `- <label>:` line prefix, matched against
    `.strip().lower()`, first occurrence wins, no prose parsing anywhere
    else in the file. Lines inside a fenced code block are never considered
    (`_uncoded_lines`) -- a decision.md quoting `` - Acceptance evals: ``
    as a literal example inside a fenced block must not have that quoted
    value outrank a real, unfenced declaration. Returns `None` when the
    field was never written at all (outside any fence) -- the caller
    (`check_acceptance_eval_declaration`) must not conflate this with
    `_normalize_acceptance_eval_declaration` returning `"unparsable"` for a
    value that *was* written but could not be recognized: "absent" and
    "unparsable" are different facts with different consequences (absent:
    this field is optional, so this gate stays silent unless this same
    round's own ledger exists -- see `check_acceptance_eval_declaration`;
    unparsable: `acceptance-eval-declaration-unparsable`, a reported
    violation, never a silent skip -- fail-closed, exactly like
    `parse_feedback` / `_normalize_feedback`'s equivalent distinction).
    """
    for line in _uncoded_lines(decision_text):
        stripped = line.strip()
        if stripped.lower().startswith("- acceptance evals:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _normalize_acceptance_eval_declaration(raw: str) -> tuple[str, str | None]:
    """Classify a raw `- Acceptance evals:` value into exactly one of three
    shapes: `("ran", None)`, `("none", reason)`, or `("unparsable", None)`.

    Deliberately narrow, mirroring `_normalize_feedback`: only
    `str.strip()` (which already treats the full-width ideographic space
    U+3000 as whitespace) and ASCII case-folding (`.lower()`) are applied --
    no punctuation is stripped. A value that is exactly `ran`
    (`ACCEPTANCE_EVAL_RAN_TOKEN`) after that normalization is the `"ran"`
    shape. A value matching `REVIEW_NONE_RE` -- the *same* regex
    `check_review_declaration` already uses for `Review: none — <reason>`,
    reused verbatim rather than hand-rolling a second, subtly different
    pattern, per the second-vertical-slice spec's explicit instruction -- is
    the `"none"` shape, with `reason` set to whatever text follows the
    `none` token and its separator (stripped, but not yet checked for
    emptiness -- the caller, `check_acceptance_eval_declaration`, owns that
    check). Anything else -- including a value that merely *resembles* one
    of the two shapes but for a stray character a naive normalizer would
    silently swallow (e.g. a trailing full-width period, `ran。`, or `none。`
    with nothing recognizable as the `none` token) -- is `"unparsable"`:
    fail-closed, exactly like `_normalize_feedback`'s `None` return. The
    caller reports `acceptance-eval-declaration-unparsable` rather than
    ever treating an unrecognized value as if the field had never been
    written, or as if it meant `none`.
    """
    normalized = raw.strip().lower()
    if normalized == ACCEPTANCE_EVAL_RAN_TOKEN:
        return "ran", None
    none_match = REVIEW_NONE_RE.match(normalized)
    if none_match:
        return "none", none_match.group(1).strip()
    return "unparsable", None


def check_acceptance_eval_declaration(
    round_dir: Path, decision_text: str, ledger_present: bool
) -> tuple[list[dict], dict]:
    """Second RAE vertical slice: narrow decision.md's optional
    `- Acceptance evals:` field against this **same round's own** ledger
    presence (`check_round_eval_ledger`'s `state["present"]`, passed in by
    the caller -- never re-read here, never re-derived any other way, and
    never joined against `<goal>/evals.json` -- that cross-time-layer join
    was measured and withdrawn; see the module docstring's "Acceptance-eval
    declaration gate" section).

    Judgment table (all eight rows this function's callers rely on):

    | field                              | ledger  | verdict                                          |
    |------------------------------------|---------|---------------------------------------------------|
    | absent                             | absent  | green (migration-silent, like E4/`Feedback`)       |
    | absent                             | present | `acceptance-eval-declaration-missing`              |
    | `ran`                               | present | green                                              |
    | `ran`                               | absent  | `acceptance-eval-declared-ran-without-ledger`      |
    | `none — <non-empty reason>`        | absent  | green                                              |
    | `none — <non-empty reason>`        | present | `acceptance-eval-declaration-contradicts-ledger`   |
    | `none —` (reason empty/whitespace) | either  | `acceptance-eval-none-reason-empty`                |
    | anything else (unparsable)         | either  | `acceptance-eval-declaration-unparsable` (fail-closed) |

    Row 1 is the deliberate upper bound this gate registers in
    `harnessloop-loop/SKILL.md`'s OUT column: this field is optional, and a
    round that never writes it -- and never writes a ledger either --
    produces zero violations from this function, exactly like a round that
    predates this field entirely. This is not a hole this function tries to
    close; the gate can only enforce "once you declare, you must be
    self-consistent", never "you must declare".

    Returns `(violations, state)` where `state` has keys `declared` (bool,
    whether the field was written at all -- `raw is not None`) and `mode`
    (`"ran"` | `"none"` | `"unparsable"` | `None` when never declared). The
    caller (`verify_round`) folds `mode`/`declared` into the
    `rounds_eval_declaration_ran` / `_none` / `_absent` coverage fields,
    mirroring how `rounds_review_declared`/`_none`/`_missing_fields`
    already works for B2a. `"unparsable"` intentionally backs no coverage
    field of its own -- same as `acceptance-eval-feedback-unparsable` above,
    which has none either; the violation list is where an unparsable value
    is visible, not a dedicated counter.
    """
    decision_path = round_dir / "decision.md"
    ledger_path = round_dir / "evidence" / "runtime" / "acceptance-evals.json"
    raw = parse_acceptance_eval_declaration(decision_text)
    state: dict = {"declared": raw is not None, "mode": None}

    if raw is None:
        if ledger_present:
            return (
                [
                    {
                        "round": str(round_dir),
                        "kind": "acceptance-eval-declaration-missing",
                        "detail": (
                            f"{decision_path} has no `- Acceptance evals:` declaration, "
                            f"but {ledger_path} exists -- a round that writes an "
                            "acceptance-eval ledger must declare `Acceptance evals: ran` "
                            "(or `none — <reason>` if the ledger is unrelated to this "
                            "round's own claim)"
                        ),
                    }
                ],
                state,
            )
        return [], state

    mode, reason = _normalize_acceptance_eval_declaration(raw)
    state["mode"] = mode

    if mode == "unparsable":
        return (
            [
                {
                    "round": str(round_dir),
                    "kind": "acceptance-eval-declaration-unparsable",
                    "detail": (
                        f"{decision_path} declares `Acceptance evals: {raw}`, which does "
                        "not normalize (strip + lowercase only, no punctuation stripped) "
                        "to `ran` or `none — <reason>` -- fail-closed, never silently "
                        "treated as absent or as `none`"
                    ),
                }
            ],
            state,
        )

    if mode == "ran":
        if not ledger_present:
            return (
                [
                    {
                        "round": str(round_dir),
                        "kind": "acceptance-eval-declared-ran-without-ledger",
                        "detail": (
                            f"{decision_path} declares `Acceptance evals: ran` but "
                            f"{ledger_path} does not exist"
                        ),
                    }
                ],
                state,
            )
        return [], state

    # mode == "none"
    if not reason:
        return (
            [
                {
                    "round": str(round_dir),
                    "kind": "acceptance-eval-none-reason-empty",
                    "detail": (
                        f"{decision_path} declares `Acceptance evals: none` with no "
                        "non-empty reason after it -- use `Acceptance evals: none — <why "
                        "no acceptance evals were run this round>` (this check only "
                        "verifies the reason is non-empty, not that it is adequate)"
                    ),
                }
            ],
            state,
        )
    if ledger_present:
        return (
            [
                {
                    "round": str(round_dir),
                    "kind": "acceptance-eval-declaration-contradicts-ledger",
                    "detail": (
                        f"{decision_path} declares `Acceptance evals: none — {reason}` but "
                        f"{ledger_path} exists -- a round that has a ledger cannot also "
                        "claim none were run"
                    ),
                }
            ],
            state,
        )
    return [], state


# Loop-predecessor gate (batch 2 of docs/loop-stop-record-spec-20260728.md,
# reversed direction per that spec's Appendix F -- see the module docstring's
# "Loop-predecessor gate" section and `check_loop_predecessor_declaration`
# below). `PREDECESSOR_VALUE_RE` reuses this project's round-directory naming
# convention exactly (`ROUND_SEGMENT_RE` above): a `- Predecessor:` value is
# only ever a bare four-digit round id, never a path, never a description --
# unlike `Review:`/`Acceptance evals:`, there is no `none — <reason>` shape
# for this field at all (Appendix F.2's two constraints are pure existence +
# arithmetic, nothing else to declare).
PREDECESSOR_VALUE_RE = re.compile(r"^\d{4}$")


def parse_loop_predecessor_declaration(decision_text: str) -> str | None:
    """Extract the raw `- Predecessor:` value from a decision.md.

    Same narrow convention as `parse_feedback` / `parse_review_fields` /
    `parse_acceptance_eval_declaration`: a case-insensitive `- <label>:` line
    prefix, matched against `.strip().lower()`, first occurrence wins, lines
    inside a fenced code block never considered (`_uncoded_lines`) -- a
    decision.md quoting `` - Predecessor: `` as a literal example inside a
    fence must not have that quoted value outrank a real, unfenced
    declaration elsewhere in the file. Returns `None` when the field was
    never written at all (outside any fence); this is the field's OUT-list
    upper bound (`harnessloop-loop/SKILL.md`) -- a round that never writes it
    is invisible to this gate, exactly like `- Acceptance evals:`.
    """
    for line in _uncoded_lines(decision_text):
        stripped = line.strip()
        if stripped.lower().startswith("- predecessor:"):
            return stripped.split(":", 1)[1].strip()
    return None


def check_loop_predecessor_declaration(
    round_dir: Path, decision_text: str
) -> tuple[list[dict], dict]:
    """Loop-predecessor gate: Appendix F.2's two structural constraints on an
    optional `- Predecessor: <NNNN>` declaration in `decision.md`.

    Checked in this order -- pure arithmetic before any filesystem access,
    filesystem last:

    1. `<NNNN>` must be exactly four digits (`PREDECESSOR_VALUE_RE`) --
       otherwise `loop-predecessor-invalid-value`. Fail-closed: an
       unrecognizable value is never silently treated as absent.
    2. `<NNNN>`'s integer value must be strictly less than this round's own
       (`int(round_dir.name)`) -- otherwise `loop-predecessor-not-backward`.
       This is checked with no filesystem access at all (both operands are
       already in hand: the parsed value and this round's own directory
       name), which is why a forward or self reference is caught here even
       when no round with that number happens to exist on disk yet --
       constraint 2 does not depend on constraint 3 having passed.
    3. The named round must actually exist as a directory under this same
       goal's `rounds/` -- otherwise `loop-predecessor-missing`. This is the
       one constraint that reads today's disk state rather than this
       round's own two fields; see `harnessloop-loop/SKILL.md`'s OUT column
       for what that implies (a predecessor round deleted after the fact
       retroactively reddens whichever later round cites it -- unlike the
       old forward-reference design this replaces, this can only ever
       affect a round that has *not yet* been judged as of today, never
       flip an already-recorded judgment about a different round).

    A round whose own directory name does not parse as an integer (a
    naming-convention violation this check was never designed to police --
    every real round in this project is named `ROUND_SEGMENT_RE`-shaped)
    is left unvalidated rather than crashing the gate over it.

    Returns `(violations, state)` where `state` has key `declared` (bool,
    `raw is not None`) -- the caller (`verify_round`) folds this into the
    `rounds_predecessor_declared` coverage field, counting every round that
    wrote the field at all, valid or not (an ordinary utilization signal,
    not a partition of outcomes the way B2a's `rounds_review_*` triad is).
    """
    decision_path = round_dir / "decision.md"
    raw = parse_loop_predecessor_declaration(decision_text)
    state: dict = {"declared": raw is not None}
    if raw is None:
        return [], state

    if not PREDECESSOR_VALUE_RE.match(raw):
        return (
            [
                {
                    "round": str(round_dir),
                    "kind": "loop-predecessor-invalid-value",
                    "detail": (
                        f"{decision_path} declares `Predecessor: {raw}`, which is not "
                        "exactly four digits (this project's round-directory naming "
                        "convention, e.g. `0003`) -- fail-closed, never silently "
                        "treated as absent"
                    ),
                }
            ],
            state,
        )

    try:
        current_round_num = int(round_dir.name)
    except ValueError:
        return [], state

    if int(raw) >= current_round_num:
        return (
            [
                {
                    "round": str(round_dir),
                    "kind": "loop-predecessor-not-backward",
                    "detail": (
                        f"{decision_path} declares `Predecessor: {raw}`, which is not "
                        f"strictly before this round ({round_dir.name}) -- Appendix F's "
                        "reversed direction requires the predecessor round's number to "
                        "be less than this round's own (strict `<`, not `<=`: a "
                        "self-reference is not backward either)"
                    ),
                }
            ],
            state,
        )

    goal_dir = round_dir.parent.parent
    predecessor_dir = goal_dir / "rounds" / raw
    if not predecessor_dir.is_dir():
        return (
            [
                {
                    "round": str(round_dir),
                    "kind": "loop-predecessor-missing",
                    "detail": (
                        f"{decision_path} declares `Predecessor: {raw}` but "
                        f"{predecessor_dir} does not exist under this same goal's "
                        "rounds/"
                    ),
                }
            ],
            state,
        )

    return [], state


# Loop-continuation record gate (batch 2 of the same spec, §3 -- see the
# module docstring's "Loop-continuation record gate" section and
# `check_loop_continuation_declaration` below). This gate records why a
# round stopped; it never judges whether the reason was the real one (the
# spec's §1.2/§3.2 argue at length that a mechanical gate structurally
# cannot tell). `LOOP_STOP_REASON_ENUM` is transcribed verbatim from the
# spec's §3.1 (protocol Stop six, contract Auto-Continue-unmet five,
# contract Stop-Conditions four, two previously-unnamed, one honesty
# label) -- eighteen values total.
LOOP_STOP_REASON_ENUM = frozenset(
    {
        # Protocol Stop (loop/SKILL.md:560-567 per the spec) -- six.
        "goal-achieved",
        "missing-human-input",
        "missing-access-facts",
        "write-safety-unconfirmed",
        "data-contract-unsatisfiable",
        "threshold-unevaluable",
        # Contract Auto-Continue unmet (control-contract-profiles.md:15-19
        # per the spec) -- five.
        "feedback-not-auto-continuable",
        "evidence-health-failed",
        "open-handoff-blocking",
        "environment-selfcheck-failed",
        "profile-requires-confirmation",
        # Contract Stop Conditions (control-contract-profiles.md:34-43 per
        # the spec) -- four.
        "model-effort-mismatch",
        "external-system-unsafe",
        "contract-unevaluable",
        "evidence-missing-for-acceptance",
        # Previously no vocabulary -- two.
        "budget-checkpoint",
        "user-interrupt",
        # Honesty label -- one. Legal, not a violation (see
        # `check_loop_continuation_declaration`'s docstring); tracked in its
        # own coverage counter instead.
        "unjustified-stop",
    }
)

# `- Loop continuation: stopped: <reason>[ — <free text>]` -- the label's
# own value nests a second `<label>: <value>` pair. The outer `- <label>:`
# scan (`parse_loop_continuation_declaration`, shared convention with every
# other field parser in this file) already splits on the line's *first*
# colon, which is the one right after "Loop continuation" (that label has
# no colon of its own), leaving `stopped: <reason>...` as the raw value this
# regex further decomposes. Case-insensitive, matching the outer convention.
LOOP_STOP_PREFIX_RE = re.compile(r"(?i)^stopped\s*:\s*(.*)$")

# The reason token is a single whitespace-free run (every enum value above
# is a kebab-case identifier with internal hyphens but no internal spaces,
# e.g. `feedback-not-auto-continuable`) -- so it is safe to greedily match
# `\S+` up to the first whitespace, which cannot occur inside a real enum
# token but does occur before the optional ` — <free text>` separator.
# Reusing a naive split on the first "-" character would be wrong: it would
# sever `goal-achieved` at its own internal hyphen. The separator itself
# reuses `REVIEW_NONE_RE`'s dash-class (plain hyphen, en dash, em dash),
# required to be surrounded by whitespace here so it is never confused with
# a token's internal hyphen (which never has adjacent whitespace).
LOOP_STOP_REASON_RE = re.compile(r"^(\S+)(?:\s+[-–—]+\s*(.*))?$")


def parse_loop_continuation_declaration(decision_text: str) -> str | None:
    """Extract the raw `- Loop continuation:` value from a decision.md.

    Same narrow convention as every other field parser in this file: a
    case-insensitive `- <label>:` line prefix, `.strip().lower()`, first
    occurrence wins, fenced lines never considered (`_uncoded_lines`).
    Returns `None` when the field was never written at all -- absence is
    silent (this field is optional, exactly like `- Acceptance evals:`);
    see `check_loop_continuation_declaration` for how "absent" is kept
    distinct from "present but unparsable".
    """
    for line in _uncoded_lines(decision_text):
        stripped = line.strip()
        if stripped.lower().startswith("- loop continuation:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _normalize_loop_continuation_declaration(raw: str) -> tuple[str, str | None]:
    """Classify a raw `- Loop continuation:` value.

    Returns `("unparsable", None)` when the value does not normalize to
    `stopped: <reason>[ — <free text>]` for a `<reason>` actually in
    `LOOP_STOP_REASON_ENUM` -- fail-closed, exactly like
    `_normalize_acceptance_eval_declaration`'s equivalent branch: a value
    that merely resembles a valid one (e.g. `stopped: goal-achieved` with a
    trailing full-width period, or a reason spelled correctly but not in the
    enum) is reported, never silently read as absent or coerced to the
    nearest known value.

    Otherwise returns `(reason, description)` where `reason` is the
    enum member (already `.strip().lower()`-folded) and `description` is
    the optional free text after the ` — ` separator, or `None` when there
    was none -- `description` is never itself validated; the caller does
    not even look at it beyond storing it in `state` for callers that may
    want it for display.
    """
    stop_match = LOOP_STOP_PREFIX_RE.match(raw.strip())
    if not stop_match:
        return "unparsable", None
    reason_part = stop_match.group(1).strip()
    reason_match = LOOP_STOP_REASON_RE.match(reason_part)
    if not reason_match:
        return "unparsable", None
    reason_token = reason_match.group(1).strip().lower()
    if reason_token not in LOOP_STOP_REASON_ENUM:
        return "unparsable", None
    description = reason_match.group(2).strip() if reason_match.group(2) else None
    return reason_token, (description or None)


def check_loop_continuation_declaration(
    round_dir: Path, decision_text: str
) -> tuple[list[dict], dict]:
    """Loop-continuation record gate (spec §3): validate only that a
    declared stop reason normalizes to a member of `LOOP_STOP_REASON_ENUM`.
    Never judges whether the reason is honest, adequate, or the real one --
    the spec's §1.2/§3.2 (`docs/loop-stop-record-spec-20260728.md`) argue
    that distinction is structurally unavailable to a mechanical gate: the
    same agent that would fabricate a stop also controls every input this
    gate could check.

    `unjustified-stop` is a legal enum member, not a violation -- judging it
    red would only punish the round that told the truth about not having a
    good reason (the spec's central argument against the predecessor design
    this batch replaces). It is instead surfaced via `state["reason"] ==
    "unjustified-stop"`, which the caller (`verify_round`) folds into the
    independent `rounds_stop_unjustified` coverage counter -- non-zero is a
    review signal, not a gate failure.

    Returns `(violations, state)` where `state` has keys `declared` (bool)
    and `reason` (the normalized enum member on success, `None` when the
    field was absent or its value did not normalize). The caller increments
    `rounds_stop_recorded` only when `reason` is not `None` -- an
    unparsable declaration is reported via the violation list (like
    `acceptance-eval-declaration-unparsable`), not double-counted in a
    coverage field of its own.
    """
    decision_path = round_dir / "decision.md"
    raw = parse_loop_continuation_declaration(decision_text)
    state: dict = {"declared": raw is not None, "reason": None}
    if raw is None:
        return [], state

    reason, _description = _normalize_loop_continuation_declaration(raw)
    if reason == "unparsable":
        return (
            [
                {
                    "round": str(round_dir),
                    "kind": "loop-continuation-invalid-value",
                    "detail": (
                        f"{decision_path} declares `Loop continuation: {raw}`, which "
                        "does not normalize to `stopped: <reason>` for a <reason> in "
                        "the recognized enum (see harnessloop-loop/SKILL.md's "
                        "Mechanical Gate Boundary) -- fail-closed, never silently "
                        "treated as absent"
                    ),
                }
            ],
            state,
        )

    state["reason"] = reason
    return [], state


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

    # TH-0026: hint layer, not a violation (E1/fixed-by-demotion precedent,
    # TH-0008) -- a span like `.harnessloop/rounds/0008/` names *this*
    # round's number but drops the `goals/<slug>/` segment that this
    # round's real directory path actually has, so Rule A silently finds
    # zero files under it (the bug this issue exists to make visible; two
    # real, already-closed instances found in this repo's own rounds/0008
    # and rounds/0009). Deliberately unconditional on `checked_files` --
    # unlike Rule A above, this is exactly the check that must still run
    # when a round has nothing under evidence/ or reviews/, since that is
    # the scenario the issue describes (a zero_inspected round whose
    # scope-lock span points at nothing). Deliberately never promoted to a
    # violation: doing so would retroactively fail already-closed rounds
    # 0008/0009 with no way to clear red short of editing closed history
    # (the E1 trap this file's module discipline exists to avoid).
    if any(scope_lock_round_path_mismatch(span, round_dir, project) is not None for span in spans):
        coverage["rounds_scope_lock_round_path_mismatch"] = 1

    # RAE gate, part 1: this round's own ledger
    # (`evidence/runtime/acceptance-evals.json`), checked unconditionally --
    # like scope-lock above, independent of whether the round has any other
    # evidence/review artifacts, and independent of whether decision.md
    # exists at all. `ledger_state` is threaded into the decision.md block
    # below so the positive-without-pass rule never re-reads or re-parses
    # the ledger a second time.
    ledger_violations, ledger_state = check_round_eval_ledger(round_dir)
    violations.extend(ledger_violations)
    if ledger_state["present"]:
        coverage["rounds_eval_ledger_present"] = 1
    coverage["eval_entries_checked"] = ledger_state["entries_checked"]

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
                    elif alias_match is not None and roots:
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

        # RAE gate, part 2: the hard rule. Every operand here comes from
        # this same round -- `decision_text` (already read above) and
        # `ledger_state` (already computed, unconditionally, earlier in
        # this function) -- never a prior round's ledger, never the goal's
        # `evals.json` (that file is validated only against itself by
        # `check_goal_eval_registry`, called once per goal by
        # `verify_project`; it is never read here).
        #
        # Feedback is read with the same narrow convention as
        # `parse_review_fields`/E4: absent means this rule stays silent
        # (zero-migration, exactly like E4) -- it is only a *written but
        # unrecognized* value that is fail-closed
        # (`acceptance-eval-feedback-unparsable`), never a silent skip.
        raw_feedback = parse_feedback(decision_text)
        if raw_feedback is not None:
            normalized_feedback = _normalize_feedback(raw_feedback)
            if normalized_feedback is None:
                violations.append(
                    {
                        "round": str(round_dir),
                        "kind": "acceptance-eval-feedback-unparsable",
                        "detail": (
                            f"{decision} declares `Feedback: {raw_feedback}`, which does not "
                            "normalize to one of positive/negative/neutral/blocked -- the "
                            "acceptance-eval positive-without-pass rule cannot be evaluated for "
                            "this round and is not silently skipped (fail-closed: full-width "
                            "punctuation or other unrecognized spelling must be reported, not "
                            "quietly treated as 'not positive')"
                        ),
                    }
                )
            elif normalized_feedback == "positive" and ledger_state["due_set"] is not None:
                # Only evaluated when this round's own ledger produced a
                # single, self-consistent frozen_due_set (see
                # `check_round_eval_ledger`'s docstring) -- when the ledger
                # is absent, shape-invalid, or internally inconsistent,
                # `due_set` is `None` and this rule stays silent for this
                # round: the ledger's own problem (or its plain absence,
                # the first OUT-list upper bound) is not compounded with a
                # second, speculative violation about a due set this
                # function cannot actually determine.
                pass_ids = {
                    entry.get("eval_id")
                    for entry in (ledger_state["entries"] or [])
                    if entry.get("outcome") == "pass" and isinstance(entry.get("eval_id"), str)
                }
                unsatisfied = sorted(ledger_state["due_set"] - pass_ids)
                if unsatisfied:
                    ledger_path = round_dir / "evidence" / "runtime" / "acceptance-evals.json"
                    violations.append(
                        {
                            "round": str(round_dir),
                            "kind": "acceptance-eval-positive-without-pass",
                            "detail": (
                                f"{decision} declares `Feedback: positive` but "
                                f"{ledger_path} has no outcome==\"pass\" entry for "
                                f"frozen_due_set eval_id(s) {unsatisfied}"
                            ),
                        }
                    )

        # Second RAE vertical slice (`check_acceptance_eval_declaration`):
        # decision.md's optional `- Acceptance evals:` field against this
        # SAME round's own ledger presence (`ledger_state["present"]`,
        # already computed unconditionally earlier in this function --
        # never re-read, never re-derived, never joined against the goal's
        # `evals.json`). See that function's docstring for the full
        # eight-row judgment table and `harnessloop-loop/SKILL.md`'s OUT
        # column for the one upper bound it deliberately leaves open (a
        # round that writes neither the field nor the ledger stays silent).
        accept_violations, accept_state = check_acceptance_eval_declaration(
            round_dir, decision_text, ledger_state["present"]
        )
        violations.extend(accept_violations)
        if accept_state["mode"] == "ran":
            coverage["rounds_eval_declaration_ran"] += 1
        elif accept_state["mode"] == "none":
            coverage["rounds_eval_declaration_none"] += 1
        elif not accept_state["declared"]:
            coverage["rounds_eval_declaration_absent"] += 1

        # Loop-predecessor gate (batch 2,
        # docs/loop-stop-record-spec-20260728.md Appendix F): decision.md's
        # optional `- Predecessor: <NNNN>`. See
        # `check_loop_predecessor_declaration`'s docstring for the two
        # structural constraints and the deliberate order they are checked
        # in (arithmetic before filesystem).
        predecessor_violations, predecessor_state = check_loop_predecessor_declaration(
            round_dir, decision_text
        )
        violations.extend(predecessor_violations)
        if predecessor_state["declared"]:
            coverage["rounds_predecessor_declared"] += 1

        # Loop-continuation record gate (batch 2, same spec §3): decision.md's
        # optional `- Loop continuation: stopped: <reason>[ — <note>]`. See
        # `check_loop_continuation_declaration`'s docstring -- this never
        # judges the reason, only that it normalizes to a member of
        # `LOOP_STOP_REASON_ENUM`; `unjustified-stop` is legal and tracked
        # separately, not treated as a violation.
        continuation_violations, continuation_state = check_loop_continuation_declaration(
            round_dir, decision_text
        )
        violations.extend(continuation_violations)
        if continuation_state["reason"] is not None:
            coverage["rounds_stop_recorded"] += 1
            if continuation_state["reason"] == "unjustified-stop":
                coverage["rounds_stop_unjustified"] += 1

    return violations, coverage


def _empty_coverage() -> dict:
    """Zeroed coverage accumulator. Keys match the `### Mechanical Gate
    Boundary` IN column in harnessloop-loop/SKILL.md one-to-one; a rename on
    either side must update the other."""
    return {
        "rounds": 0,
        "rounds_zero_inspected": 0,
        # TH-0026: round-level (0 or 1, like `rounds_zero_inspected` above),
        # set when at least one of this round's own scope-lock spans names
        # this round's number but not this round's real path prefix (see
        # `scope_lock_round_path_mismatch`). Hint-only -- never a violation,
        # never affects exit code; accumulated across rounds by the same
        # `coverage[key] += round_coverage[key]` loop every other per-round
        # field uses.
        "rounds_scope_lock_round_path_mismatch": 0,
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
        # RAE gate (`check_round_eval_ledger`, wired into `verify_round`):
        # ordinary per-round fields, accumulated by the same
        # `coverage[key] += round_coverage[key]` loop `verify_project` already
        # runs over every other per-round field.
        "rounds_eval_ledger_present": 0,
        "eval_entries_checked": 0,
        # Second RAE vertical slice (`check_acceptance_eval_declaration`,
        # wired into `verify_round` right after the fields above): ordinary
        # per-round fields, accumulated the same way. `mode` partitions a
        # round with a `decision.md` into exactly one of `ran` / `none` /
        # (declared but) unparsable (no counter of its own, mirroring
        # `acceptance-eval-feedback-unparsable`'s lack of one) / never
        # declared at all (`_absent`).
        "rounds_eval_declaration_ran": 0,
        "rounds_eval_declaration_none": 0,
        "rounds_eval_declaration_absent": 0,
        # Loop-predecessor gate (`check_loop_predecessor_declaration`, batch 2
        # of docs/loop-stop-record-spec-20260728.md, Appendix F direction):
        # ordinary per-round field, accumulated the same way as the RAE
        # fields above. Counts every round that wrote `- Predecessor:` at
        # all, valid or not -- an unparsable/missing/not-backward value still
        # counts here (it is reported separately via the violations list,
        # like `acceptance-eval-declaration-unparsable` has no coverage
        # field of its own).
        "rounds_predecessor_declared": 0,
        # Loop-continuation record gate (`check_loop_continuation_declaration`,
        # same spec §3): `rounds_stop_recorded` counts a round only when its
        # `- Loop continuation: stopped: <reason>` normalized successfully
        # (an unparsable value is reported via the violations list, not
        # counted here). `rounds_stop_unjustified` is a strict subset of
        # `rounds_stop_recorded` -- rounds whose reason was specifically the
        # honesty label `unjustified-stop`, which is legal (never a
        # violation) but is meant to be a visible, non-zero review signal.
        "rounds_stop_recorded": 0,
        "rounds_stop_unjustified": 0,
        # RAE gate (`check_goal_eval_registry`): goal-level, not round-level --
        # `<goal>/evals.json` lives once per goal, not once per round, so this
        # field is incremented directly by `verify_project`'s goal loop (once
        # per goal whose registry file exists), never by the per-round
        # accumulation loop below. Every round's own local `coverage =
        # _empty_coverage()` leaves this at 0 (mirrors how `external_roots_*`
        # stays 0 through that same per-round loop -- see the comment on
        # those fields immediately below).
        "goals_eval_registry_present": 0,
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


def _unavailable_root_violations(project: Path, roots: dict) -> list[dict]:
    """G7, once per unavailable alias, project-wide.

    A single implementation deliberately shared by both of `verify_project`'s
    exits (the normal round-walking path and the no-`goals/` early return) so
    the two can never drift into disagreeing about whether an unavailable
    root is reportable -- the exact drift T-070 found.
    """
    return [
        {
            "round": str(project),
            "kind": "external-root-unavailable",
            "detail": (
                f"reference root '{alias}' is unavailable "
                f"({root.unavailable_reason}); every citation using this alias "
                "will be reported external-citation-unverifiable"
            ),
        }
        for alias, root in roots.items()
        if not root.available
    ]


def collect_scope_lock_round_path_mismatch_notes(project: Path) -> list[str]:
    """TH-0026: human-readable notes for `main()`'s CLI display only.

    A light, standalone walk of `goals/*/rounds/*/scope-lock.md`, deliberately
    kept separate from `verify_project`'s `(violations, coverage)` return
    value -- that tuple already has 70+ call sites across this repo (this
    module's own `main()` plus every fixture in `scripts/validate.py`) that
    unpack it as exactly two values; growing it would mean touching every
    one of them for a hint that must never affect exit code, violations, or
    the `--json` coverage schema in the first place. This mirrors the
    existing `--show-root-paths` precedent: a second, independent pass run
    only for an additional human-mode-only print section, computed fresh
    rather than threaded through the main verification return value.

    Never raises on a malformed tree -- worst case is a missed note, never a
    crash of the real gate.
    """
    notes: list[str] = []
    goals_dir = project / ".harnessloop" / "goals"
    if not goals_dir.is_dir():
        return notes
    for goal_dir in sorted(p for p in goals_dir.iterdir() if p.is_dir()):
        rounds_dir = goal_dir / "rounds"
        if not rounds_dir.is_dir():
            continue
        for round_dir in sorted(p for p in rounds_dir.iterdir() if p.is_dir()):
            scope_lock = round_dir / "scope-lock.md"
            if not scope_lock.is_file():
                continue
            try:
                spans = extract_allowed_spans(scope_lock.read_text(encoding="utf-8"))
            except OSError:
                continue
            for span in spans:
                note = scope_lock_round_path_mismatch(span, round_dir, project)
                if note is not None:
                    notes.append(note)
    return notes


def verify_project(project: Path) -> tuple[list[dict], dict]:
    goals_dir = project / ".harnessloop" / "goals"
    coverage = _empty_coverage()
    if not goals_dir.is_dir():
        # A project with no rounds yet still has a *declaration*, and the
        # declaration is a project-level fact -- reporting
        # `external_roots_declared=0` here would be the coverage lying about
        # what this project is configured to reach, and would let a
        # declaration land (or be swapped) unseen for as long as no round
        # exists. Load it and report it; its G1-G6 violations are equally
        # real without a single round on disk.
        roots, root_violations = load_reference_roots(project)
        coverage["external_roots_declared"] = len(roots)
        coverage["external_roots_available"] = sum(1 for r in roots.values() if r.available)
        # G7 too, on exactly the same terms as the round-walking path below.
        # Emitting the declaration's own G1-G6 problems here but not its
        # unavailable-root problems made the same project with the same
        # declaration exit 0 or 1 depending only on whether a `goals/`
        # directory happened to exist -- an unbound root passed silently in
        # a fresh project, which is when it is most likely to be wrong
        # (T-070 residual).
        root_violations.extend(_unavailable_root_violations(project, roots))
        return root_violations, coverage
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
    violations.extend(_unavailable_root_violations(project, roots))

    # Built once per project run (not per round/citation) — see
    # `build_suffix_index` for why this matters for performance.
    suffix_index = build_suffix_index(project)
    for goal_dir in sorted(p for p in goals_dir.iterdir() if p.is_dir()):
        escape = _container_escape_violation(goal_dir, project, goal_dir)
        if escape is not None:
            violations.append(escape)
            continue

        # RAE gate: `<goal>/evals.json` lives once per goal, not once per
        # round -- checked here, once per goal_dir, rather than inside
        # `verify_round` (which runs once per round under this same goal
        # and would otherwise re-validate, and re-count, the identical file
        # once per round). See `check_goal_eval_registry`'s docstring for
        # exactly what "only its own internal legitimacy" means here.
        eval_registry_violations, eval_registry_present = check_goal_eval_registry(goal_dir)
        violations.extend(eval_registry_violations)
        if eval_registry_present:
            coverage["goals_eval_registry_present"] += 1

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
            f"scope_lock_round_path_mismatch={coverage['rounds_scope_lock_round_path_mismatch']} "
            f"review_declared={coverage['rounds_review_declared']} "
            f"review_none={coverage['rounds_review_none']} "
            f"review_missing_fields={coverage['rounds_review_missing_fields']} "
            f"review_digest_declared={coverage['rounds_review_digest_declared']} "
            f"goals_eval_registry_present={coverage['goals_eval_registry_present']} "
            f"rounds_eval_ledger_present={coverage['rounds_eval_ledger_present']} "
            f"eval_entries_checked={coverage['eval_entries_checked']} "
            f"eval_declaration_ran={coverage['rounds_eval_declaration_ran']} "
            f"eval_declaration_none={coverage['rounds_eval_declaration_none']} "
            f"eval_declaration_absent={coverage['rounds_eval_declaration_absent']} "
            f"predecessor_declared={coverage['rounds_predecessor_declared']} "
            f"stop_recorded={coverage['rounds_stop_recorded']} "
            f"stop_unjustified={coverage['rounds_stop_unjustified']} "
            f"external_roots_declared={coverage['external_roots_declared']} "
            f"external_roots_available={coverage['external_roots_available']} "
            f"external_citations_checked={coverage['external_citations_checked']} "
            f"external_citations_resolved={coverage['external_citations_resolved']} "
            f"external_citations_not_found={coverage['external_citations_not_found']} "
            f"external_citations_rejected={coverage['external_citations_rejected']} "
            f"external_citations_unverifiable={coverage['external_citations_unverifiable']}"
        )
        # TH-0026: non-blocking hint lines, human mode only -- never affects
        # exit code, violations, or the `--json` coverage schema (the same
        # boundary `--show-root-paths` already keeps below). Printed
        # whenever `rounds_scope_lock_round_path_mismatch` is nonzero so the
        # count above is not just a number nobody can act on; each note
        # names the round, what its scope-lock actually wrote, and what
        # this round's real directory path is.
        if coverage["rounds_scope_lock_round_path_mismatch"] > 0:
            for note in collect_scope_lock_round_path_mismatch_notes(project):
                print(f"  note (non-blocking, TH-0026): {note}")
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
