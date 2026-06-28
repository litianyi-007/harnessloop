---
name: harness-loop
description: "Use when running a goal-driven harness loop in an installed project: define goals, data freshness rules, decomposition thresholds, verification thresholds, file-system handoffs, minimal-change scope locks, subagent/swarm delegation, and adversarial review based on real static data, dynamic generated data, source code, and source-data evidence."
---

# Harness Loop

Use this skill as a project-local operating protocol. Do not treat it as a generic engineering checklist.

For handoff formatting, use `references/handoff-template.md`.

## Core Contract

Every loop must have:

- A clear `goal`.
- Data freshness and drift controls for real static data and dynamic generated data.
- Data thresholds and verification thresholds that can be decomposed and checked.
- A per-round `scope-lock` that minimizes change; strict mode changes one variable only.
- File-system handoffs for task transfer, review, and archival.
- Evidence from real data, dynamic data, repository source, or source-data files.
- A verification phase that assigns adversarial review before accepting the round.

Only stop the loop when the goal is achieved or a required human decision blocks progress.

## Project Setup

If `.harnessloop/` does not exist in the target project, propose creating:

```text
.harnessloop/
  setup/
    data-sources.md
    model-rules.md
  goals/
```

During setup, ask the user to fill in data-source connection requirements. Do not invent the data-source scope or content.

`data-sources.md` should record, at minimum:

- Real static data sources.
- Dynamic/generated data sources.
- Refresh expectations.
- Drift risks.
- How each source can be validated.

`model-rules.md` should record, at minimum:

- Main-session role.
- Subagent/swarm role.
- Preferred model tier by role.
- Cases that must not be delegated.

## Goal Structure

Create one directory per goal:

```text
.harnessloop/goals/YYYYMMDD-NNN-<goal-slug>/
  goal.md
  thresholds.md
  data-contract.md
  rounds/
```

`goal.md` must state the goal, non-goals, success condition, and required human decisions.

`thresholds.md` must split the goal into:

- Data thresholds: what data must be fresh, complete, representative, and non-drifting.
- Verification thresholds: what must be true before a round can be accepted.

`data-contract.md` must state which real static data, dynamic data, source code, and source-data files are valid evidence for this goal.

## Round Structure

Create one directory per loop round:

```text
rounds/0001/
  scope-lock.md
  handoffs/
  evidence/
    static/
    dynamic/
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

For Codex, prefer subagents using `gpt-5.5-medium` when available for independent investigation and adversarial review.

For Claude Code, prefer swarm or subagents using Sonnet with high/extra-high reasoning when available for the same categories.

Do not delegate:

- Final goal interpretation.
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

## Loop Continuation

After each completed round:

1. Update `round-summary.md`.
2. Write `decision.md` with accepted, rejected, or blocked.
3. Archive closed handoffs.
4. If the goal is not achieved and no human decision is required, propose the next smallest scope-lock and continue the loop.

Stop only when:

- The goal is achieved.
- Required human input is missing.
- The data contract cannot be satisfied.
- Verification thresholds cannot be evaluated.
