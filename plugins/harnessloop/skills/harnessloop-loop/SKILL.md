---
name: harnessloop-loop
description: "Use when running or taking over a long-running goal-driven task in an installed project: create or import Harnessloop state, run intake gates for existing agent sessions, decompose goals, define evidence and validation contracts, enforce scope-locks, manage file-system handoffs, verify with real static/dynamic/runtime/source evidence, classify feedback, self-audit for drift or dead loops, and continue only through evidence-backed control gates."
---

# Harnessloop

Use this skill as a project-local operating protocol. Do not treat it as a generic engineering checklist.

## Input Contract

Accept one of these inputs:

- A user goal for a long-running task, including target project path when it is not the current working directory.
- An explicit skill invocation such as `$harnessloop-loop`, `$harnessloop-goal`, `$harnessloop-status`, `$harnessloop-continue`, `$harnessloop-evidence`, `$harnessloop-channels`, or `$harnessloop-connectivity`.
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
For control-plane state, evidence indexing, environment self-check, and evals, use the matching templates in `references/`.
For loop self-audit and upstream evolution issues, use `references/self-audit-template.md` and `references/evolution-issue-template.md`.
For existing-session takeover, use `references/transfer-packet-template.md`, `references/intake-gate-template.md`, `references/gap-review-template.md`, and `references/intake-review-round-template.md`.
For goal and round files, use the matching `*-template.md` files in `references/`.
For deterministic project initialization, run `scripts/init_project.py`.

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
- Environment and delegation self-checks that record expected versus observed model and effort.
- Self-audit for dead loops, contradiction, drift, handoff stagnation, and cost/context runaway.

Only stop the loop when the goal is achieved or a required human decision blocks progress.

## Project Setup

If `.harnessloop/` does not exist in the target project, propose creating:

```text
.harnessloop/
  setup/
    data-sources.md
    cost-context-policy.md
  intake/
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

Prefer the bundled initializer instead of hand-creating files:

```bash
python <skill-dir>/scripts/init_project.py --project <target-project>
```

For an existing-session takeover, create the intake packet directory at initialization time:

```bash
python <skill-dir>/scripts/init_project.py --project <target-project> --intake <task-slug>
```

The initializer must not overwrite existing files unless explicitly run with `--force`. It creates protocol skeleton files only; it must not invent project data sources, accounts, credentials, goals, or validation results.

During setup, ask the user to fill in data-source connection requirements. Do not invent the data-source scope or content.

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
- If feedback is `blocked`, do not continue without a clear human unblock record.
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

If evidence depends on reading from or writing to an external system and any access condition or required parameter is missing, do not infer it or probe blindly. Ask the user for the missing system, operation, endpoint/resource, account role, permission scope, credential reference, parameters, or failure handling before attempting access.

If a task explicitly requires tool calling with a named tool and that tool is missing, not installed, not exposed in the current environment, or possibly the wrong tool, stop and ask the user for confirmation. Do not infer an alternative tool, alias, provider, command, or API from context.

`$harnessloop-channels` lists all declared external systems, channels, and tools without probing. `$harnessloop-connectivity` checks only declared connectivity methods and must ask the user before any missing condition, parameter, credential reference, permission, write target, or named tool is inferred. Treat `harnessloop:channels` and `harnessloop:connectivity` as natural-language aliases. If connectivity self-check returns `fail`, `blocked`, `skipped`, or `needs-user-confirmation` because required information is missing or invalid, ask the user for the exact missing information before continuing the loop.

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

Before relying on delegation, self-check must record:

- Whether independent tasks can be created.
- Whether read-only or write scope can be constrained.
- Whether output paths can be required.
- Whether returned results cite evidence paths.
- Expected versus observed model and effort.
- Mismatch handling.

If the expected delegation environment cannot be verified, feed that mismatch into self-audit and continue conservatively. Do not assume the intended model or effort was used.

Do not delegate:

- Final goal interpretation.
- Final goal breakdown approval.
- Changes to scope-lock.
- Human-required product or business decisions.
- Acceptance of a round after a failed adversarial review.

## Verification Phase

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

If negative or neutral feedback repeats without new evidence, scope narrowing, rollback, or contract repair, update `meta/self-audit.md` before starting another execution round.

## Evals

Maintain `.harnessloop/evals/matrix.md` for protocol robustness checks. Use it to assess whether this project's loop policy handles common task, evidence, feedback, rollback, and cost/context scenarios.

The eval matrix is not a runtime gate by itself. It informs setup hardening, template updates, and adversarial review prompts.

## Loop Continuation

After each completed round:

1. Update `round-summary.md`.
2. Write `decision.md` with positive, negative, neutral, or blocked.
3. Archive closed handoffs.
4. Update `meta/self-audit.md` when the round exposes loop-health risk.
5. If feedback is positive and the goal is not achieved, continue to the next subgoal or task.
6. If feedback is negative or neutral and no human decision is required, propose the next smallest investigation, fix, or rollback scope-lock.

Stop only when:

- The goal is achieved.
- Required human input is missing.
- The data contract cannot be satisfied.
- Verification thresholds cannot be evaluated.
