---
name: harnessloop-status
description: "Use when the user references harnessloop:status, asks for Harnessloop status, wants to inspect the active goal, round, evidence health, open handoffs, control state, environment state, self-audit state, next proposed action, or blocking reason. This skill is strictly read-only and must not mutate files or continue work."
---

# Harnessloop Status

Read Harnessloop state safely. This skill reports current loop state; it must not create files, update contracts, archive handoffs, run business execution, or continue the task.

## Input Contract

Accept an explicit skill invocation such as `$harnessloop-status`, or natural language asking for current Harnessloop state. Treat `harnessloop:status` and `harnessloop status` as natural-language aliases only; `$harnessloop:status` is not a valid skill invocation.

Useful input includes:

- `target-project`: defaults to the current working directory.
- Optional state path, usually `.harnessloop/state/current.md`.
- Optional scope: active goal, active round, evidence, handoffs, control, environment, self-audit, or next action.

If `.harnessloop/` is missing, report `not-initialized` and suggest `$harnessloop-init`. Do not initialize it from this skill.

## Processing Contract

1. Read `.harnessloop/state/current.md` first when present.
2. Follow only the source paths referenced by current state, active goal, active round, open handoffs, latest decision, evidence index, control contract, environment self-check, and self-audit.
3. Summarize evidence health without revalidating external systems unless the user explicitly asks for evidence checking; route that to `$harnessloop-evidence`.
4. Report contradictions, missing state files, stale pointers, unresolved human decisions, intake blockers, blocker type, recovery eligibility, and next action safety.
5. Do not mutate any file, run continuation gates, execute tests as business work, or change feedback classification.

## Output Contract

Return a concise status report:

```text
Harnessloop status:
- project:
- state: initialized | not-initialized | inconsistent | blocked
- active goal:
- active round:
- current feedback:
- blocker type:
- recovery eligible:
- open handoffs:
- evidence health:
- control state:
- environment state:
- self-audit state:
- intake state:
- next proposed action:
- next action safety:
- blocking reason:
- human decision required:
- recovery round:
- source paths read:
```

If the next action is execution, say that continuation must go through `$harnessloop-continue`; do not continue from this skill.

## Safety Rules

- Read-only means no file writes, no archiving, no generated state repair, no contract changes, and no business execution.
- Missing or inconsistent state should produce `blocked` or `inconsistent`, not inferred status.
- External systems and named tools are not probed from status; ask the user to use `$harnessloop-evidence` or `$harnessloop-continue` when action is required.
