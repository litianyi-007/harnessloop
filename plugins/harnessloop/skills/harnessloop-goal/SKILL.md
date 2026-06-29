---
name: harnessloop-goal
description: "Use when the user references harnessloop:goal or asks to inspect, propose, negotiate, update, split, reprioritize, archive, cancel, supersede, or assess deletion impact for Harnessloop goals, subgoals, or tasks. This skill manages goal contracts and goal breakdowns without executing business work or accepting rounds."
---

# Harnessloop Goal

Manage Harnessloop goals as contracts. This skill edits or reports goal structure, subgoals, tasks, thresholds, and goal lifecycle state; execution remains with `$harnessloop-continue` or `$harnessloop-loop`.

## Input Contract

Accept requests such as `harnessloop:goal status`, `harnessloop:goal propose`, `harnessloop:goal negotiate`, `harnessloop:goal update`, `harnessloop:goal split`, `harnessloop:goal reprioritize`, `harnessloop:goal archive`, `harnessloop:goal cancel`, `harnessloop:goal supersede`, or `harnessloop:goal deletion-impact`.

Useful input includes:

- `target-project`: defaults to the current working directory.
- `action`: `status`, `propose`, `negotiate`, `update`, `split`, `reprioritize`, `archive`, `cancel`, `supersede`, or `deletion-impact`.
- `goal-path`: existing `.harnessloop/goals/YYYYMMDD-NNN-<goal-slug>/` when applicable.
- `goal-contract`: goal, non-goals, success condition, acceptance criteria, required human decisions, and ambiguity.
- `subgoals-or-tasks`: proposed or existing subgoal/task list with dependencies, priority, risk, expected evidence, and validation method.
- `change-reason`: why the goal contract or breakdown is changing.
- `human-confirmation`: required for material goal contract changes, cancellation, supersession, deletion impact, or current-round impact.

If `.harnessloop/` is missing, stop and suggest `harnessloop:init`. If intake-created work has not passed intake review, route to `$harnessloop-intake` before goal creation or mutation.

## Processing Contract

1. Read `.harnessloop/state/current.md`, active goal files, `goal.md`, `goal-breakdown.md`, `thresholds.md`, `data-contract.md`, `feedback-policy.md`, active round `scope-lock.md`, latest `decision.md`, and `state/evidence-index.md` when present.
2. For `status`, report the current goal, subgoals/tasks, dependencies, progress, blocked items, current round impact, and evidence/threshold links.
3. For `propose`, draft a goal contract and initial breakdown without creating execution rounds.
4. For `negotiate`, identify ambiguity, missing non-goals, conflicting acceptance criteria, oversized scope, required human decisions, and options for narrowing.
5. For `update`, change only the requested goal contract fields and record reason, human confirmation, threshold impact, evidence impact, and current-round impact.
6. For `split`, create or revise subgoals/tasks with dependency order, expected evidence, validation method, and risk.
7. For `reprioritize`, reorder subgoals/tasks and record the reason; block continuation when the active round scope is affected.
8. For `archive`, `cancel`, or `supersede`, preserve the goal directory and write lifecycle state; do not hard-delete files.
9. For `deletion-impact`, report what references would break before any deletion is considered.

## Output Contract

Return a goal action record:

```text
Harnessloop goal action:
- action: status | propose | negotiate | update | split | reprioritize | archive | cancel | supersede | deletion-impact | missing-fields
- active goal:
- affected files:
- goal contract change:
- subgoal/task change:
- threshold impact:
- evidence contract impact:
- current round impact:
- lifecycle state:
- human confirmation: required | provided | not-required
- continuation effect: allow | block | needs-review
- next allowed action:
```

When files are changed, update the smallest relevant set: `goal.md`, `goal-breakdown.md`, `thresholds.md`, `data-contract.md`, `feedback-policy.md`, `state/current.md`, or a lifecycle note under the goal directory. If evidence requirements change, route to `$harnessloop-evidence`. If continuation may proceed, route to `$harnessloop-continue`.

## Safety Rules

- Do not execute business work.
- Do not accept a round or classify round feedback.
- Do not hard-delete a goal by default; prefer `archive`, `cancel`, or `supersede`.
- Require explicit human confirmation for material goal contract changes, cancellation, supersession, deletion, and changes that affect the active round.
- If the active round scope-lock, evidence contract, thresholds, or feedback policy is affected, block continuation until `$harnessloop-continue` runs the gate.
- Preserve auditability: cite source paths read and changed, and keep superseded/cancelled goals traceable.

## Examples

View current goal:

```text
harnessloop:goal status
```

Negotiate scope:

```text
harnessloop:goal negotiate this is too broad; split API migration from UI cleanup
```

Cancel a goal:

```text
harnessloop:goal cancel active goal; human confirmed because the external dependency was removed
```
