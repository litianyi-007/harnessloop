---
name: harnessloop-continue
description: "Use when the user references harnessloop:continue, asks Harnessloop to continue, resume, advance, or proceed through the control gate. This skill reads current Harnessloop state, runs the continuation gate, and allows only the next action permitted by evidence, control, environment, intake, and self-audit state."
---

# Harnessloop Continue

Run the Harnessloop continuation gate before any execution. This skill may continue only through an allowed next action; it must not bypass evidence, intake, control, self-audit, or human-confirmation requirements.

## Input Contract

Accept an explicit skill invocation such as `$harnessloop-continue`, or natural language asking to resume/advance a Harnessloop task. Treat `harnessloop:continue` and `harnessloop continue` as natural-language aliases only; `$harnessloop:continue` is not a valid skill invocation.

Useful input includes:

- `target-project`: defaults to the current working directory.
- Optional requested next action.
- Optional human decision or unblock record.
- Optional evidence, tool, or external-system confirmation needed by the current control gate.

If `.harnessloop/` is missing, stop and suggest `$harnessloop-init`. If imported intake work is pending, route to `$harnessloop-intake`.

## Processing Contract

1. Read `.harnessloop/state/current.md`, `state/control-contract.md`, `state/environment.md`, `state/evidence-index.md`, `state/self-check.md`, `meta/self-audit.md`, the active goal, active round, open handoffs, and latest decision.
2. Confirm the requested next action matches the control contract and latest feedback.
3. If feedback is `positive`, continue only to the next subgoal/task or goal completion path.
4. If feedback is `negative` or `neutral`, continue only with investigation, minimal fix, rollback, missing evidence repair, or human-confirmed contract revision.
5. If feedback is `blocked`, stop unless a clear human unblock record is present.
6. If evidence contract changes are needed, route to `$harnessloop-evidence` before execution.
7. If active work came from `.harnessloop/intake/`, require passed intake gate and accepted intake-review round before business execution.
8. If self-audit, environment, named-tool, external-system, or access requirements are missing or ambiguous, ask the user for confirmation before tool use or execution.

## Output Contract

Return a continuation decision before action:

```text
Harnessloop continuation:
- project:
- decision: allowed | blocked | needs-evidence | needs-intake | needs-human | needs-self-audit | complete
- active goal:
- active round:
- current feedback:
- requested next action:
- allowed next action:
- evidence gate:
- control gate:
- environment gate:
- self-audit gate:
- human decision:
- files read:
- files changed:
- next status command:
```

If execution is allowed and performed, write/update only the protocol files required for that allowed action and end with the next recommended `$harnessloop-status` check.

## Safety Rules

- Do not continue without reading current state and latest decision.
- Do not turn neutral feedback into success.
- Do not bypass human-confirm states, missing evidence, failed intake, failed self-audit, unavailable named tools, or ambiguous external-system parameters.
- Do not infer named-tool substitutions or external-system access details; ask the user first.
- Do not accept a round after failed adversarial review unless the control contract and human decision explicitly allow it.
