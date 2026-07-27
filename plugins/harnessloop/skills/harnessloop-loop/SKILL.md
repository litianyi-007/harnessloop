---
name: harnessloop-loop
description: "Use when running or taking over a long-running goal-driven task in an installed project: create or import Harnessloop state, run intake gates for existing agent sessions, decompose goals, define evidence and validation contracts, enforce scope-locks, manage file-system handoffs, verify with real static/dynamic/runtime/source evidence, classify feedback, self-audit for drift or dead loops, and continue only through evidence-backed control gates."
---

# Harnessloop

Use this skill as a project-local operating protocol. Do not treat it as a generic engineering checklist.

## Input Contract

Accept one of these inputs:

- A user goal for a long-running task, including target project path when it is not the current working directory.
- An explicit skill invocation such as `$harnessloop-loop`, `$harnessloop-goal`, `$harnessloop-status`, `$harnessloop-continue`, `$harnessloop-evidence`, `$harnessloop-channels`, `$harnessloop-connectivity`, `$harnessloop-delegation`, or `$harnessloop-secrets`.
- Natural-language aliases such as `harnessloop:goal`, `harnessloop:status`, `harnessloop:continue`, `harnessloop:evidence`, `harnessloop:channels`, `harnessloop:connectivity`, `harnessloop contract control`, or `harnessloop issue evolve`. Skill names cannot contain `:`, so `$harnessloop:...` is not valid.
- Existing `.harnessloop/` state files that define the active goal, round, evidence, handoffs, and control state.
- A takeover request only after `harnessloop-intake` has produced or accepted the intake packet, gate, and intake-review boundary.

The useful input should include goal/non-goal context, acceptance criteria, relevant file paths, available validation commands, external tool requirements, and any required human decisions. If these are missing, create the smallest setup, status, or gap request instead of inventing facts.

If the user or contract requires a specific tool call, the input must identify the tool name, intended operation, required parameters, target resource, expected read/write scope, and fallback policy. If the named tool is unavailable, uninstalled, misspelled, ambiguous, or lacks the required capability, ask the user to confirm before substituting another tool or changing the operation.

## Processing Contract

Process information through the Harnessloop control plane:

1. Read project-local `.harnessloop/` files before acting.
2. Check goal, evidence, control, environment, and self-audit state.
3. Create or update only the protocol files required by the requested action.
4. Execute business work only after scope-lock, evidence contract, and continuation rules allow it.
5. Cite file paths, commands, logs, tests, URLs, or other evidence for every accepted claim.

## Output Contract

Produce file-backed loop state, not just chat summaries. Depending on the request, write or update goal files, thresholds, data contracts, scope-locks, handoffs, evidence, reviews, decisions, state indexes, or evolution issues. End with a concise status summary that names changed files, evidence used, feedback class if known, and the next allowed action or blocking human decision.

For handoff formatting, use `references/handoff-template.md`.
For goal decomposition, feedback, and cost/context policy, use the matching templates in `references/`.
For control-plane state, evidence indexing, environment self-check, and evals, use the matching templates in `references/`. For control-contract profile presets (lite/standard/strict), see `references/control-contract-profiles.md`.
For loop self-audit and upstream evolution issues, use `references/self-audit-template.md` and `references/evolution-issue-template.md`.
For existing-session takeover, use `references/transfer-packet-template.md`, `references/intake-gate-template.md`, `references/gap-review-template.md`, and `references/intake-review-round-template.md`.
For goal and round files, use the matching `*-template.md` files in `references/`.
For deterministic project initialization, run `<skill-dir>/scripts/init_project.py`.

## Core Contract

Every loop must have:

- A clear `goal`.
- Data freshness and drift controls for real static data and dynamic generated data.
- Data thresholds and verification thresholds that can be decomposed and checked.
- A goal breakdown before the first execution round.
- An intake gate before continuing work imported from another agent session.
- A per-round `scope-lock` that minimizes change; strict mode changes one variable only.
- File-system handoffs for task transfer, review, and archival.
- Evidence from real data, dynamic data, repository source, or source-data files.
- A verification phase that assigns adversarial review before accepting the round.
- Positive, negative, and neutral feedback classification after validation.
- A control plane for status, continuation, evidence contract changes, and human intervention.
- Blocker classification that separates recoverable runtime blockers from missing access, unsafe writes, contract gaps, and required human decisions.
- Environment and delegation self-checks that record expected versus observed model and effort.
- Self-audit for dead loops, contradiction, drift, handoff stagnation, and cost/context runaway.

Only stop the loop when the goal is achieved, required human input is missing, required access/tool facts are missing, write safety is not declared, or the blocker cannot be safely investigated.

## Project Setup

If `.harnessloop/` does not exist in the target project, or `check_setup.py` reports `gate_blocking: true` for an existing `.harnessloop/`, propose creating (or completing) the following:

```text
.harnessloop/
  setup/
    data-sources.md
    cost-context-policy.md
  local/
    .gitignore
    channel-params.example.json
    channel-params.json  # local ignored file, never committed
  intake/
    .gitignore  # ignores transfer-packet.md; gate/review outputs stay tracked
    YYYYMMDD-HHMM-<task-slug>/
      transfer-packet.md
      intake-gate.md
      gap-review.md
  state/
    current.md
    environment.md
    control-contract.md
    evidence-index.md
    self-check.md
  meta/
    self-audit.md
    evolution-issues/
  evals/
    matrix.md
  goals/
```

If `.harnessloop/` already exists, do not re-run the initializer. Instead check completeness:

```bash
python3 -B <skill-dir>/scripts/check_setup.py --project <target-project> --json
```

If this reports `gate_blocking: true`, hand off to `$harnessloop-setup` to complete the blocking core file (environment.md, control-contract.md, or cost-context-policy.md) before creating a goal or entering a round. If `gate_blocking` is `false` but `complete` is `false`, proceed normally and mention the non-blocking gap (see `references/control-contract-profiles.md` for the profile options `$harnessloop-setup` uses at its control-contract step) so the user can close it later. Do not fill `data-sources.md`, `cost-context-policy.md`, `control-contract.md`, or `environment.md` by free-form conversation outside the wizard.

Prefer the bundled initializer instead of hand-creating files:

```bash
python <skill-dir>/scripts/init_project.py --project <target-project>
```

For an existing-session takeover, create the intake packet directory at initialization time:

```bash
python <skill-dir>/scripts/init_project.py --project <target-project> --intake <task-slug>
```

The initializer must not overwrite existing files unless explicitly run with `--force`. It creates protocol skeleton files only; it must not invent project data sources, accounts, credentials, goals, or validation results.

During setup, run `$harnessloop-setup` to fill in data-source connection requirements, cost/context policy, control-contract profile (see `references/control-contract-profiles.md` for the lite/standard/strict presets), and environment detection through its five-step wizard. Do not invent the data-source scope or content, and do not fill these files by ad hoc conversation outside the wizard.

`data-sources.md` should record, at minimum:

- Real static data sources.
- Dynamic/generated data sources.
- Refresh expectations.
- Drift risks.
- How each source can be validated.

`cost-context-policy.md` should record, at minimum:

- Main-session role.
- Subagent/swarm role.
- Preferred model tier by role.
- Cases that must not be delegated.
- Budget and context-preservation rules.

## Existing Session Takeover

If the user wants Harnessloop to take over a long-running task from another agent session, do not require the source session to install Harnessloop. Ask the source session to produce a `Harnessloop Transfer Packet` using `references/transfer-packet-template.md`.

Store the packet under:

```text
.harnessloop/intake/YYYYMMDD-HHMM-<task-slug>/transfer-packet.md
```

Before creating a formal goal or continuing business execution, run an intake gate with `references/intake-gate-template.md`.

The intake gate must verify:

- Goal, non-goals, success condition, acceptance criteria, and required human decisions are explicit.
- Completed work is backed by file paths, commands, test output, logs, URLs, or other evidence.
- Existing and generated documents are listed with source-of-truth status, freshness, trust level, relevance, and sensitivity.
- Process artifacts are traceable.
- External tools, accounts, permissions, failure handling, and credential requirements are described.
- No secret values are stored in Harnessloop files.
- Current changes, rollback risks, next action, and open blockers are clear.
- Drift, contradiction, dead-loop, and validation gaps are called out.

If the gate fails, write `gap-review.md` using `references/gap-review-template.md` and ask only for missing information. Do not continue business execution.

If the gate passes, the first round should normally be an `intake-review` round using `references/intake-review-round-template.md`. This round maps imported evidence into `state/evidence-index.md`, confirms the source-of-truth documents, and creates the formal goal directory. Only after this round passes may Harnessloop continue the business task.

## Control Commands

Treat these as protocol semantics. Do not assume a CLI exists unless the project provides one.

`$harnessloop-status` is the preferred read-only status entry. Treat `harnessloop:status` as a natural-language alias:

- Read `.harnessloop/state/current.md` plus source files referenced by it.
- Report active goal, active round, current feedback, open handoffs, evidence health, control state, environment state, next proposed action, and blocking reason.
- Do not create, modify, archive, or continue any task.

`$harnessloop-continue` must run a continuation gate before any execution. Treat `harnessloop:continue` as a natural-language alias:

- Read current state, control contract, environment self-check, evidence index, active goal, active round, open handoffs, and latest decision.
- Continue only through an allowed next action.
- If feedback is `positive`, continue to the next subgoal or task when the goal is not complete.
- If feedback is `negative` or `neutral`, continue only with investigation, minimal fix, rollback, or human-confirmed contract revision.
- If feedback is `blocked`, classify the blocker as `runtime-recoverable`, `access-missing`, `write-safety-required`, `human-decision-required`, `contract-insufficient`, `external-system-unsafe`, or `unknown`.
- If the blocker is `runtime-recoverable` and the next safe action is read-only investigation, evidence refresh, or cleanup-plan drafting, start the next recovery round instead of pausing for the user.
- If the blocker requires missing access facts, write cleanup, external mutation, trigger execution, business judgment, or contract revision, stop and ask the user for the missing information or decision.
- If evidence or control contract health fails, do not execute; request contract repair or missing evidence.
- If self-audit fails, do not execute unless the next action repairs the audit failure, creates an explicit human-confirmed contract revision, or writes an evolution issue.
- If the active work came from `.harnessloop/intake/`, do not execute business work until `intake-gate.md` passes and an `intake-review` round is accepted.

`$harnessloop-evidence` manages acceptable evidence during a loop. Treat `harnessloop:evidence` as a natural-language alias:

- `add`: register evidence type, path, freshness, validation method, and applicable goal or round.
- `check`: verify evidence exists, is fresh enough, and can be cited by review.
- `revise`: change acceptance criteria; require human confirmation.
- `reject`: record invalid, stale, unsupported, too-sensitive, or inapplicable evidence.
- `diff`: summarize how the evidence contract changed and whether continuation is allowed.

Do not continue execution directly after a material evidence contract change. Route back through the continuation gate and self-audit when the change affects acceptance, freshness, validation method, or continuation authority.

If evidence depends on reading from or writing to an external system and any access condition or required parameter is missing, do not infer it or probe blindly. Ask the user for the missing system, operation, endpoint/resource, account role, permission scope, credential reference, parameters, or failure handling before attempting access. Use `askuserquestion` when available; otherwise ask directly in chat.

If a task explicitly requires tool calling with a named tool and that tool is missing, not installed, not exposed in the current environment, or possibly the wrong tool, stop and ask the user for confirmation through `askuserquestion` when available. Do not infer an alternative tool, alias, provider, command, or API from context.

`$harnessloop-channels` lists all declared external systems, channels, and tools without probing. `$harnessloop-connectivity` checks only declared connectivity methods and must ask the user before any missing condition, parameter, credential reference, permission, write target, or named tool is inferred. Treat `harnessloop:channels` and `harnessloop:connectivity` as natural-language aliases. If connectivity self-check returns `fail`, `blocked`, `skipped`, or `needs-user-confirmation` because required information is missing or invalid, ask the user for the exact missing information before continuing the loop.

`$harnessloop-secrets` manages local-only channel parameters and secret references in `.harnessloop/local/channel-params.json`. Use it when evidence, channels, or connectivity need reusable external-system parameters. If channel id, parameter key, sensitivity, storage, and required-for purpose are explicit, create a local placeholder key before connectivity or evidence collection. Do not store parameter values, tokens, or credentials in setup, evidence, state, handoff, review, or decision files.

`$harnessloop-delegation` checks whether subagent, swarm, or other delegated work can be trusted for the requested task type. Run it before high-risk delegation, when expected model/effort must be verified, when observed model/effort is missing, or when delegation capability changes. If the check returns `blocked`, `fail`, or `unknown` for required conditions, do not delegate beyond conservative handoffs or human-confirmed policy.

`$harnessloop-goal` manages goal contracts, subgoals, tasks, lifecycle state, and deletion impact. Treat `harnessloop:goal` as a natural-language alias. It must not execute business work or accept rounds. If a goal change affects thresholds, evidence, active scope-lock, or continuation authority, route back through `$harnessloop-evidence` or `$harnessloop-continue`.

`harnessloop contract control` manages human intervention and continuation rules:

- Define auto-continue states.
- Define human-confirm states.
- Define stop conditions.
- Define delegation boundaries.
- Define round acceptance authority after failed review.

`$harnessloop-issue record` writes a Harnessloop evolution issue when local self-audit, the user, or an external reviewer finds a framework-level question or failure. Write the issue under `.harnessloop/meta/evolution-issues/` using the evolution issue template. Do not include secrets, credentials, raw private data, or unnecessary source dumps. Treat `harnessloop issue evolve` as a natural-language alias for this record action.

`harnessloop intake review` is a protocol action for reviewing `.harnessloop/intake/.../transfer-packet.md`. It writes `intake-gate.md`, writes `gap-review.md` when needed, and blocks business execution until the packet is evidence-backed.

## Goal Structure

Create one directory per goal:

```text
.harnessloop/goals/YYYYMMDD-NNN-<goal-slug>/
  goal.md
  goal-breakdown.md
  thresholds.md
  data-contract.md
  feedback-policy.md
  rounds/
```

`goal.md` must state the goal, non-goals, success condition, and required human decisions.

Treat each goal as long-term unless the user explicitly defines it as a single-round task.

Before creating the first execution round, create `goal-breakdown.md`:

- Use read-only discovery handoffs for background investigation, current-state analysis, constraints, and dependency mapping.
- Delegate discovery to subagents or swarm when it is independent and low-context.
- Keep the final breakdown, ordering, and priority decision in the main session.
- Split the goal into subgoals or tasks with dependencies, risk, expected evidence, and validation method.

`thresholds.md` must split the goal into:

- Data thresholds: what data must be fresh, complete, representative, and non-drifting.
- Verification thresholds: what must be true before a round can be accepted.

`data-contract.md` must state which real static data, dynamic data, source code, and source-data files are valid evidence for this goal.

`feedback-policy.md` must define how validation outcomes move the loop:

- Positive feedback: archive the round and continue to the next subgoal or task.
- Negative feedback: investigate execution fault first while reserving attention for goal or business-assumption fault.
- Neutral feedback: treat as negative until enough evidence exists.

## State Files

Keep state files as control-plane indexes. They are not the sole source of truth.

`state/current.md` is the status entry point:

- Active goal and round.
- Current feedback.
- Open handoffs.
- Last accepted round.
- Next proposed action.
- Human decision requirement.
- Blocking reason.
- Source paths used to derive this state.

`state/environment.md` records detected environment:

- `codex`, `claude-code`, `other`, or `unknown`.
- Delegation mechanism and availability.
- Expected model and effort from policy.
- Observed model and effort when verifiable.
- Verification method and mismatch action.

`state/control-contract.md` records continuation control:

- Auto-continue states.
- Human-confirm states.
- Blocked states.
- Blocker taxonomy and recovery eligibility.
- Scope-lock mutation policy.
- Evidence contract mutation policy.
- Round acceptance authority.

`state/evidence-index.md` indexes evidence without replacing the evidence itself:

- Evidence ID, type, path, applies-to, freshness requirement, observed timestamp, validation method, citation requirement, artifact health, claim support, acceptance effect, reproducibility, and sensitivity.

`state/self-check.md` records setup and continuation gate checks.

`meta/self-audit.md` records loop-health checks. It must be updated during setup, before continuation, after negative or neutral feedback, and before classifying a goal as blocked due to process limitation.

`meta/evolution-issues/` stores upstream issue reports for Harnessloop itself. Create one only after local mitigation has been attempted or ruled out.

## Self-Audit

Run self-audit as a protocol gate, not as a generic retrospective.

Check for:

- Dead loop risk: repeated feedback, repeated next action, unchanged scope, or no measurable evidence improvement.
- Self-contradiction: goal, thresholds, data contract, control contract, scope-lock, review, or decision disagree.
- Goal drift: goal interpretation changes without a main-session decision and document update.
- Evidence drift: source, freshness, schema, semantics, or validation method changes without contract revision.
- Validation drift: local tests, remote automation, CI, probes, canaries, or monitoring criteria change without threshold updates.
- Handoff stagnation: open handoffs repeat failures, lack citations, or never close.
- Cost/context runaway: raw logs, reports, or broad source context move into the main session instead of file-system evidence.

If self-audit finds a problem, choose the smallest local repair first:

- Refresh or re-index evidence.
- Narrow the next scope-lock.
- Add missing runtime validation.
- Create or repair a handoff.
- Roll back a prior execution classified as wrong.
- Request human-confirmed contract revision.

Create a Harnessloop evolution issue only when the failure points to the framework itself: missing template fields, unclear skill rules, insufficient documentation, weak sample coverage, or marketplace/package behavior that prevents correct use.

Use deterministic self-audit signals where possible: repeated feedback sequence, repeated next action count, scope-lock version, goal/threshold/data-contract version or hash, verification command changes, stale evidence count, open handoff age, context risk, and delegation model/effort verification.

## Round Structure

Create one directory per loop round:

```text
rounds/0001/
  scope-lock.md
  handoffs/
  evidence/
    static/
    dynamic/
    runtime/
    source/
  reviews/
  round-summary.md
  decision.md
  archive/
```

`scope-lock.md` must define:

- The one round objective.
- Allowed files, data, or variables to change.
- Disallowed changes.
- Verification commands or checks.
- Rollback condition.

Default to minimal change. Use one-variable strict mode when the task is autoresearch, sensitive, or drift-prone.

## Handoff Rules

Use file-system handoffs for all delegated work and review. Name files:

```text
<round>-<seq>-<role>-<task-slug>-<status>.md
```

Example:

```text
0001-01-research-static-data-open.md
0001-02-execute-one-variable-open.md
0001-03-review-adversarial-open.md
0001-03-review-adversarial-closed.md
```

Each handoff must include:

- Objective.
- Inputs and evidence paths.
- Scope boundaries.
- Required output paths.
- Verification condition.
- Closeout summary.

Archive closed handoffs under the round `archive/` directory after `round-summary.md` captures the result.

## Role And Model Rules

Keep the main session focused on orchestration and core decisions.

Delegate by handoff when the task is:

- Independent investigation.
- Low-context execution.
- Not tightly coupled to the core decision.
- Adversarial review or acceptance testing.

For Codex, prefer subagents using `gpt-5.5` with medium reasoning when available for independent investigation and adversarial review.

For Claude Code, prefer swarm or subagents using Sonnet with high or extra-high reasoning when available for the same categories.

For other agent environments, keep delegation conservative. If delegation model or effort cannot be verified, default to the main session's model and effort or require human confirmation.

Use delegation to protect the main session's context and cost. Handoffs should pass file paths, bounded questions, and output limits instead of broad conversational context.

Use this execution delegation matrix before starting or continuing a round:

| Task type | Delegation decision | Goal | Value | Preconditions | Never delegate when |
| --- | --- | --- | --- | --- | --- |
| Read-only discovery | Should delegate | Map current state, constraints, dependencies, prior failures, data availability, and validation options | Saves main-session context and parallelizes broad investigation | Clear question, bounded paths, no write access, required output path | The question changes goal interpretation or requires a human decision |
| Evidence collection | Delegate when bounded and read-only | Gather logs, file citations, source excerpts, reports, or command outputs as evidence paths | Keeps raw evidence out of the main session while preserving traceability | Evidence contract names accepted sources, sensitivity is understood, output cites paths | Secrets, private raw data, or external access conditions are unclear |
| External connectivity check | Usually keep in main gate or `$harnessloop-connectivity` | Verify declared tools, credentials references, endpoints, permissions, and write safety | Prevents blind probing and keeps access questions centralized | Channel contract is complete and the named tool is verified | Tool, endpoint, credential reference, permission, parameter, or write safety is missing |
| Low-risk local implementation | May delegate | Apply a narrow patch, generate a bounded artifact, or run a contained local check | Moves mechanical work out of the main session without losing scope control | Scope-lock allows the files, rollback is clear, verification command is declared | The change is high-risk, cross-cutting, irreversible, or changes contracts |
| High-risk or cross-cutting implementation | Main session owns; delegate only narrow subtasks | Preserve architectural intent and mutation control | Avoids uncoordinated changes across variables or contracts | Subtasks are isolated, each has a file/output boundary, main session approves integration | Scope-lock would need expansion or acceptance criteria are still unstable |
| Adversarial review | Must delegate when a verifiable mechanism exists | Challenge the round against scope-lock, evidence contract, thresholds, and source truth | Reduces self-review bias before acceptance | Reviewer has evidence paths, review template, and required output path | Delegation mechanism/model cannot be verified and the risk requires human review |
| Acceptance testing | Should delegate when independent | Reproduce validation and check acceptance evidence from a fresh context | Improves confidence and catches hidden assumptions | Test commands, environment, expected output, and evidence destination are explicit | Tests require missing external access, unsafe writes, or human-only judgment |
| Round acceptance and control decisions | Never delegate | Decide whether feedback is positive, negative, neutral, or blocked | Keeps authority with the main session and control contract | Main session has review, evidence, and decision files | Always; failed-review acceptance additionally requires explicit control contract and human decision |

Before relying on delegation, self-check must record:

- Whether independent tasks can be created.
- Whether read-only or write scope can be constrained.
- Whether output paths can be required.
- Whether returned results cite evidence paths.
- Expected versus observed model and effort.
- Mismatch handling.

If the expected delegation environment cannot be verified, run `$harnessloop-delegation`, feed that mismatch into self-audit, and continue conservatively. Do not assume the intended model or effort was used.

Do not delegate:

- Final goal interpretation.
- Final goal breakdown approval.
- Changes to scope-lock.
- Human-required product or business decisions.
- Acceptance of a round after a failed adversarial review.

## Verification Phase

Two gates operate at different layers, and both must pass before a round is accepted. `<skill-dir>/scripts/verify_protocol.py` is a mechanical gate: it enforces only machine-checkable rules (scope-lock containment, dangling evidence citations) and is run in Loop Continuation step 1. Adversarial review below is a separate model-judgment gate: it checks whether the evidence actually supports the claim. A mechanical pass is not a protocol pass — a round that exits `verify_protocol.py` clean still fails if adversarial review, thresholds, or feedback classification are not satisfied.

### Mechanical Gate Boundary

The mechanical gate's exit code decides less than it looks like it decides. What it currently checks (**IN** — field names below match `verify_protocol.py`'s `coverage` object, printed on every run and included under the `coverage` key of `--json` output, one-to-one):

- `rounds` / `rounds_zero_inspected` — scope-lock existence (`missing-scope-lock`) and Allowed Changes parseability (`unparseable-allowed-changes`), checked unconditionally for every round regardless of whether that round has any evidence/review artifacts. Before any of that: `goals_dir`, each goal directory, and each round directory are containment-checked top-down — a symlink escape at any of those levels (`round-container-escapes-project`, e.g. `rounds/0001` itself being a symlink out of the project) stops descent right there; nothing under an escaping container, scope-lock included, is ever read (PR-2, v0.20.0, BREAKING).
- `rule_a_files` — whether files under a round's `evidence/` and `reviews/` fall inside a path the round's scope-lock allows (`scope-lock-violation`), checked only when the round has at least one such file and its scope-lock parses; the allowed-check ANDs that lexical scope-lock match with canonical project containment (`_is_contained`), so a file lexically under `reviews/` whose real target escapes the project still fails. `evidence/`/`reviews/` are themselves containment-checked the same way as `rounds` above (`round-container-escapes-project`) before being listed, and every entry found while walking them — file, directory, or dangling — is symlink-checked before any `is_file()` filtering (`round-artifact-is-symlink`): a symlinked entry's content is never read, whether it points inside or outside the project (PR-2, v0.20.0, BREAKING — this also closes the case where the round/evidence/reviews directory *itself*, not just a file inside it, is a symlink).
- `rule_b_files` / `citations_checked` — whether backtick path-ish references inside that round's `reviews/*.md` resolve to files that exist (`dangling-citation`). A citation resolvable only via a suffix match against the project's file index is **not** resolved (T-064): it is reported `dangling-citation` regardless.
- `citations_exempt_external` — how many of those citation spans were home-relative (`~/...`), filesystem-absolute (`/...`), or Windows-absolute (`C:/...`, UNC) and so were exempted from existence checking entirely (a real, uncovered gap — see `verify_protocol.py`'s module docstring — made visible in coverage rather than silently disappearing).
- `citations_suffix_hinted` — how many `dangling-citation` violations carry a display-only hint because their citation uniquely (and still really) matches one file's path suffix elsewhere in the project (T-064: a hint only — it never turns a `dangling-citation` into a pass; see `verify_protocol.py`'s module docstring).
- `citations_ignored_explicit` / `review_files_with_ignore` — how many citation spans were explicitly exempted by a `<!-- verify:ignore -->` marker, and how many review files in this round carried at least one such marker. Closes a real blind spot (T-066 §1 judgment criterion 2, ignore-marker misuse monitoring): before these fields existed, the ignore branch skipped without counting anything, so a review could sprinkle `verify:ignore` over genuinely dangling citations and empty Rule B out while `coverage` / exit code / `--json` all kept reporting clean.
- `citations_shape_dropped` — how many `/`-containing citation spans were silently dropped by the shape heuristic (tail has no file extension, no trailing `/`, and no `..` segment — e.g. `src/pkgdir`) before ever reaching existence checking. Not a violation by itself; makes visible the cheapest way to turn a genuinely dangling citation green (delete its file extension).
- `rounds_review_declared` / `rounds_review_none` / `rounds_review_missing_fields` / `rounds_review_digest_declared` — B2a (`.hopper/handoffs/T-066-output.md` §4, "只入账、不入树"): whether a round's `decision.md`, when present, declares `Review:` (a project-contained, non-symlink, existing path — canonical containment reuses `_is_contained`, exactly as Rule B's citation resolution does) or `Review: none — <non-empty reason>`, plus `Reviewer:` and `Review verdict:` (`review-declaration-missing` when any of the three required fields is absent; `review-path-escapes-project` / `review-path-not-found` / `review-path-is-symlink` / `review-path-not-file` / `review-none-reason-empty` / `review-digest-mismatch` for the more specific failure shapes — see `check_review_declaration`'s docstring). A round predating this rule (no `Review:`/`Reviewer:`/`Review verdict:` lines at all) fails `review-declaration-missing`, not silently passes — unlike E4, this is not a zero-migration check, and existing rounds are expected to need one.
- `external_roots_declared` / `external_roots_available` — PR-3 (external-citation-base-spec-20260727.md §2.1-2.7): how many external reference roots this project declares in `.harnessloop/setup/reference-roots.json`, and how many of those are actually available this run (bound locally, resolvable, not a forbidden location, and — for the declared alias whose `expect_present` sentinels all exist under it — identity-confirmed). Project-level, assigned exactly once after the round loop, never accumulated per round. A declared-but-unavailable root also produces one `external-root-unavailable` violation per alias, project-wide; the specific reason (`reference-root-rejected` / `reference-root-unresolvable` / `reference-root-identity-mismatch` / `reference-root-shadow-alias` / unbound) is never silently downgraded to a pass. **One alias, one root, one direction:** two aliases that resolve to the same directory are *both* marked unavailable and reported once as `reference-root-shadow-alias` — a second name for an already-declared tree would let a citation read it under a `purpose`/`approved_by` no reviewer ever approved for it. Sameness is decided by the directory's filesystem identity (`samefile`), not by comparing resolved path strings — on a case-insensitive volume those strings differ for one and the same directory. Both declaration files must be the tracked files themselves: a symlinked `reference-roots.json` (or `.local.json`) is rejected outright, so what a reviewer sees in the diff and what the gate loads can never be two different files.
- `external_citations_checked` / `external_citations_resolved` / `external_citations_not_found` / `external_citations_rejected` / `external_citations_unverifiable` — how many `@@<alias>/<relpath>` citations (an alias declared and bound) were resolved against their own reference root, and how each one landed: resolved; `not_found` (does not exist there, or wrong case, or a broken symlink); `rejected` (literal `/`/`~`/drive-absolute/`..` traversal, a canonical containment escape, or outside the root's declared `subpaths`); or `unverifiable` (the root itself is unavailable — every citation using it is reported this way, never silently skipped). `checked == resolved + not_found + rejected + unverifiable` always. An `@@<alias>/...` span whose alias is **not** declared is not counted here at all — it falls back to the unchanged project-relative judgment above and can still produce an ordinary `dangling-citation` (with a display-only note naming the declared aliases). A scope-lock `Allowed Changes` span naming a *declared* alias is rejected outright as `scope-lock-span-names-reference-root` — a reference root can never be authorized for writes.

What it does **not** decide (**OUT** — currently not decided by the mechanical gate, not "unmechanizable forever"):

- Whether the cited evidence actually supports the round's conclusion.
- Whether a stated threshold was met.
- Whether a test genuinely asserts anything, versus asserting nothing and passing vacuously.
- Whether `pass` / `positive` wording is honest about what happened.
- Whether a business-code change stayed inside scope.
- Whether the content of a declared `Review:` file is any good, and whether its citations are real — B2a accounts for the review's existence and identity only; it never scans the file's prose, never runs Rule B against it, and never counts it toward `rule_a_files` / `rule_b_files` / `citations_checked`. That is the deliberate B2a/B2b boundary (B2b, pilot-gated and not yet built, is where a declared review's content would start being checked).
- Whether a `Review: none — <reason>` reason is adequate, true, or anything beyond non-empty — this rule can tell a blank reason from a written one, not a good excuse from a bad one.
- Whether an external reference root is actually related to this project. A bound root's `expect_present` sentinels only prove it currently contains files with those names; `approved_by` is checked for non-emptiness, never for truth. A completely unrelated tree can pass the same sentinel check. This judgment belongs to round acceptance authority, not the mechanical gate.
- Whether a declared root is "too wide". Rejecting `/`, a home directory, or a project ancestor/interior is mechanical; a legitimate-but-overbroad root such as `~/Documents` or `~/go/pkg/mod` cannot be mechanically rejected. The only constraint is alias-only resolution (G13: a wide root is only ever reachable through a citation that explicitly spells out its alias) plus a declaration that is diffable and whose alias name is printed every round.
- Whether the file an alias resolves to is the one a reviewer actually meant to cite. Resolution only proves that, on the machine running this gate, at this moment, under exact-case segment matching, the declared and approved root contains that path — never the author's intent, never that its content supports the claim.
- Whether external content is reproducible. A reference root is not part of the project's git history: no Rule A, no diff, no versioning. `expect_present` (and an optional root-commit check, not implemented here) only prove the same tree was found again, never that its content is unchanged. A citation that resolved in one round can report `external-citation-not-found` in a later round after the external tree changes, with the root's identity check still passing.
- Whether this round widened its own reference-root declaration specifically to turn its own citations green. The declaration lives under `setup/`, not scope-lock, not `state/`, not a goal file — Rule A structurally cannot see it change. `external_roots_declared` is folded into coverage and into `decision.md` verbatim every round, so a same-round swap is visible in a round-to-round diff, never blocked by the mechanical gate itself.
- Cross-round joins of any kind (e.g. comparing this round's declaration against a prior round's). Not implemented; this repo's own evolution-issue history is the reason (cross-file joins produced most of them).
- Suffix hints for alias citations. There are none, by design (see below) — absence of a hint must never be read as "checked and fine".
- Whether `Review:` or a scope-lock `Allowed Changes` entry is authorized to name a reference root as project content — it never is; see below.

Coverage fact: Rule A only inspects `evidence/` and `reviews/`; Rule B only inspects that round's `reviews/*.md`. Neither rule reads the business-code change itself, and neither reads `.harnessloop/state/`. **An exit 0 must not be read as "every artifact this round produced was inspected"** — only that the files under those two directories were. A round with nothing under `evidence/` or `reviews/` still exits 0 and is counted in `rounds_zero_inspected`, which means "nothing to check", not "checked and clean".

Discipline: when the mechanical gate fails, do not make it pass by editing the checked artifact unless that artifact is genuinely wrong — the correct fix is `$harnessloop-issue` plus an explicit, recorded exemption. If a round's `scope-lock.md` is edited after that round's `evidence/` already exists, `decision.md` must record one line explaining why.

### External Reference Roots

A project may declare a named external tree — e.g. an upstream design wiki kept outside the project, that this project's reviews cite as fact — and cite a file inside it with `@@<alias>/<relpath>` (double `@`, not single; not `alias:relpath`). Both alternatives were measured and rejected: a single `@` collides with real npm-scoped-package and TS/Vite/Angular `compilerOptions.paths` citations already in use today (`@app/services/user.service.ts` is a citation right now); `alias:relpath` silently drops a bare top-level file (`wiki:SCHEMA.md` never even reaches the citation extractor) and collides with the locator-suffix `:` separator.

Declaration is two files, never one:

- `.harnessloop/setup/reference-roots.json` — versioned, contains **zero absolute paths**. Per alias: `alias`, `purpose`, `expect_present` (1-8 root-relative sentinel paths used to confirm identity), optional `subpaths` (a **non-empty** first-segment whitelist — omit the key for no restriction; an explicit `[]` is rejected rather than read as either deny-all or unrestricted), `approved_by`. See `references/reference-roots-template.json`.
- `.harnessloop/local/reference-roots.local.json` — machine-local, **never committed** (gitignored the same way `channel-params.json` is), maps an alias to where it lives on this machine. This file may only ever answer "where" — never "is this the right tree, and is it available"; a binding that tries to claim `identity`/`available`/`optional`/`expect_present` is rejected outright. Its only optional key is `bound_at` (a provenance note), which must be a non-empty string when present. See `references/reference-roots-local-template.json`.

Absence of the versioned file is exactly today's behavior — zero declared roots, zero change to any existing citation's resolution (zero migration).

Identity is confirmed by a project-committed sentinel (`expect_present`), never a git remote (a real external wiki can be a git repo with no remote at all) and never a marker file dropped inside the external tree (a hard link defeats the symlink guard meant to protect it, and the marker's own presence check would otherwise become a read of an arbitrary local path whose hash could end up in a public `decision.md`).

The two resolution domains never overlap and there is no fallback order between them: which domain a citation belongs to is decided by its own text plus the declared alias set, before any filesystem access. `@@<alias>/...` with a **declared** alias resolves only inside that alias's root — it never tries the project, `.harnessloop/`, a submodule root, or the suffix-hint index, even for a bare, extension-less tail that a project-relative citation would otherwise have silently dropped. A malformed relpath under a declared alias (leading `/`/`~`, a drive letter, or any `..` segment) is rejected outright — it never falls back to project-relative resolution. `@@<alias>/...` with an **undeclared** alias is not a new failure mode: it resolves exactly like today's project-relative judgment always has (almost always `dangling-citation`, since no project literally has a directory named `@@foo`), with one added display-only note naming the aliases that are actually declared. Declaring one alias never changes how any other citation — aliased or not — resolves.

An external root never enters the suffix-hint index: hinting at an unversioned, possibly-other-writable tree would reproduce the exact "resolved by coincidence, not by the reviewer's intent" failure mode this protocol already closed for the project's own suffix hints, at a strictly larger and less auditable scale.

`Review:` in `decision.md` and a scope-lock's `Allowed Changes` never accept an alias. Both name project-versionable content only; a reference root is never something this project can authorize a write into. A scope-lock span naming a declared alias is reported `scope-lock-span-names-reference-root`, not silently dropped from the allowed-spans list.

Do not accept a round with a generic engineering review alone.

Assign adversarial review that checks the work against:

- Real static data freshness.
- Dynamic/generated data behavior.
- Repository source code.
- Source-data files.
- The active `scope-lock`.
- The goal's data and verification thresholds.

The review must cite evidence paths. If evidence is missing, stale, or drifting, the round fails.

Validation must also update self-audit when it detects repeated failure, contradiction, drift, stale evidence, missing runtime coverage, or unbounded context growth.

Classify validation feedback:

- `positive`: expected behavior is confirmed; archive and continue to the next subgoal or task.
- `negative`: expected behavior is not confirmed; inspect this round's execution first, then inspect whether the goal, business assumption, data contract, or validation contract is insufficient.
- `neutral`: evidence is inconclusive; continue as negative until resolved.

Negative or neutral feedback may lead to:

- More investigation.
- A minimal fix.
- Rollback of a prior execution that is now classified as wrong.
- Human-confirmed contract revision.
- A blocked state when a required decision is missing.

Blocked feedback must be classified before the loop stops:

- `runtime-recoverable`: open the next read-only investigation or recovery-planning round when evidence targets and scope boundaries are explicit.
- `access-missing`: ask for missing tool, endpoint, credential reference, local parameter, permission, or account role.
- `write-safety-required`: ask for dry-run/test-resource/rollback details and human confirmation before cleanup, trigger, rollback, or other external mutation.
- `human-decision-required`: ask for the business, product, risk, policy, acceptance, or cleanup decision.
- `contract-insufficient`: repair the goal, evidence, threshold, or control contract before execution.
- `external-system-unsafe`: stop write actions and allow only bounded observation until safety is established.
- `unknown`: ask for the missing facts needed to classify the blocker.

If negative or neutral feedback repeats without new evidence, scope narrowing, rollback, or contract repair, update `meta/self-audit.md` before starting another execution round.

## Evals

Maintain `.harnessloop/evals/matrix.md` for protocol robustness checks. Use it to assess whether this project's loop policy handles common task, evidence, feedback, rollback, and cost/context scenarios.

The eval matrix is not a runtime gate by itself. It informs setup hardening, template updates, and adversarial review prompts.

## Loop Continuation

After each completed round:

1. Run the mechanical protocol gate: `python <skill-dir>/scripts/verify_protocol.py --project <target-project>`. If it exits non-zero, this round must not be marked `positive`; record the violation in `decision.md` and classify the blocker as `contract-insufficient` until it is repaired. A clean exit here does not by itself accept the round — steps 2-8 below still apply. Record the gate's exit code and its `coverage:` line verbatim in `decision.md`'s `Mechanical gate` field. A round whose `decision.md` lacks that line has not completed step 1 — the record is what makes "was the gate actually run, and how much did it inspect" answerable later without rerunning it.
2. Update `round-summary.md`, including its `## Cost` section: in a `claude-code` environment (see `state/environment.md`), run `python <skill-dir>/scripts/round_cost.py --project <target-project>` and paste its markdown output. The script settles token usage since the last settlement from local session transcripts; never read transcript files into the session. In any other environment, record cost as `unavailable: no local transcript source` — `round_cost.py` only reads Claude Code session transcripts. If the script is run and exits non-zero, record cost as unavailable with the reason.
3. Write `decision.md` with positive, negative, neutral, or blocked. It must also declare `Review:` (a project-contained path to the review artifact, or `none — <non-empty reason>`), `Reviewer:`, and `Review verdict:` (optionally `Review digest:`) — the mechanical gate checks only that these are present and, when `Review:` names a path, that it exists as an ordinary non-symlink file inside the project (and that a declared digest matches); it never reads the review file's own content (see Mechanical Gate Boundary above and `decision-template.md`).
4. Archive closed handoffs.
5. Update `meta/self-audit.md` when the round exposes loop-health risk.
6. If feedback is positive and the goal is not achieved, continue to the next subgoal or task.
7. If feedback is negative or neutral and no human decision is required, propose or enter the next smallest investigation, fix, or rollback scope-lock.
8. If feedback is blocked, classify the blocker. Enter the next read-only recovery round when `runtime-recoverable`; otherwise ask for the exact missing user input, access fact, or write-safety decision.

Stop only when:

- The goal is achieved.
- Required human input is missing.
- Required access/tool facts are missing.
- A write action is needed but write safety or human confirmation is missing.
- The data contract cannot be satisfied.
- Verification thresholds cannot be evaluated.
