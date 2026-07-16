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
- Optional blocker classification, recovery eligibility, and safe read-only investigation target.

If `.harnessloop/` is missing, stop and suggest `$harnessloop-init`. If imported intake work is pending, route to `$harnessloop-intake`.

If `.harnessloop/` exists and `check_setup.py` reports `gate_blocking: true` (a core policy file — environment/control-contract/cost-context-policy — is still `template` or `missing`), stop and return `needs-setup` before evaluating any other gate (see Processing Contract step 1); suggest `$harnessloop-setup`. If `gate_blocking` is `false` but `complete` is `false` (non-blocking gaps remain, e.g. in `data-sources.md` or acknowledged via TODO), do not stop; surface a warning with `field_todo_count` and `selfcheck_todo_count` and continue evaluating the remaining gates normally.

## Processing Contract

1. Run `python3 -B <plugin-root>/skills/harnessloop-loop/scripts/check_setup.py --project <target-project> --json`. If `gate_blocking` is `true`, set decision to `needs-setup`, name the `template`/`missing` core file (environment.md, control-contract.md, or cost-context-policy.md) as the next setup step, and stop before evaluating any other gate. Do not execute business work. If `gate_blocking` is `false` but `complete` is `false`, do not stop; record `setup gate: warning`, `field_todo_count`, `selfcheck_todo_count`, and the `missing_sections` of any non-`filled` file, then proceed to step 2.
2. Read `.harnessloop/state/current.md`, `state/control-contract.md`, `state/environment.md`, `state/evidence-index.md`, `state/self-check.md`, `meta/self-audit.md`, the active goal, active round, open handoffs, and latest decision.
3. If the latest decision treats the active round as `positive`, confirm that `python <plugin-root>/skills/harnessloop-loop/scripts/verify_protocol.py --project <target-project>` was run for that round and exited zero, or run it now. A non-zero exit means the round must not be treated as `positive`; reclassify the blocker as `contract-insufficient` and stop for evidence/contract repair instead of continuing.
4. Confirm the requested next action matches the control contract and latest feedback.
5. If feedback is `positive`, continue only to the next subgoal/task or goal completion path.
6. If feedback is `negative` or `neutral`, continue only with investigation, minimal fix, rollback, missing evidence repair, or human-confirmed contract revision.
7. If feedback is `blocked`, classify the blocker before stopping. Use `runtime-recoverable`, `access-missing`, `write-safety-required`, `human-decision-required`, `contract-insufficient`, `external-system-unsafe`, or `unknown`.
8. If the blocker is `runtime-recoverable` and the next action is read-only investigation with declared evidence targets, create or enter the next investigation/recovery round instead of pausing for the user.
9. If the blocker requires write cleanup, external mutation, missing access facts, missing local channel parameters, a named tool that is unavailable, or business judgment, stop and ask the user through `askuserquestion` when available.
10. If evidence contract changes are needed, route to `$harnessloop-evidence` before execution.
11. If active work came from `.harnessloop/intake/`, require passed intake gate and accepted intake-review round before business execution.
12. If self-audit, environment, delegation, named-tool, external-system, or access requirements are missing or ambiguous, ask the user for confirmation before tool use or execution. Use `askuserquestion` when available; otherwise ask directly in chat.
13. If the next action relies on subagent, swarm, or another delegated mechanism and model/effort or scope control is unverified, route to `$harnessloop-delegation` before execution.

## Blocker Classification

- `runtime-recoverable`: runtime state blocks the original action, but a safe read-only investigation or evidence refresh can proceed.
- `access-missing`: required endpoint, credential reference, local parameter, permission, account role, or named tool is missing or invalid.
- `write-safety-required`: progress requires cleanup, mutation, trigger, rollback, or any write operation without declared dry-run/test-resource/rollback/human confirmation.
- `human-decision-required`: progress requires product, business, risk, policy, acceptance, or cleanup authorization from the user.
- `contract-insufficient`: the evidence, goal, threshold, or control contract lacks required fields for safe continuation.
- `external-system-unsafe`: an external system is in a state where probing or mutation could duplicate work, corrupt state, or hide evidence.
- `unknown`: the blocker cannot be classified from current evidence.

For a recoverable runtime blocker, the next round must be bounded to observation, diagnosis, evidence refresh, or drafting a cleanup plan. It must not perform the blocked trigger or cleanup write.

## Output Contract

Return a continuation decision before action:

```text
Harnessloop continuation:
- project:
- decision: allowed | blocked | needs-setup | needs-evidence | needs-intake | needs-human | needs-self-audit | complete
- active goal:
- active round:
- current feedback:
- requested next action:
- allowed next action:
- setup gate: complete | warning | blocking
- field todo count:
- selfcheck todo count:
- evidence gate:
- control gate:
- environment gate:
- self-audit gate:
- delegation gate:
- blocker type:
- recovery eligible: yes | no
- recovery round:
- recovery scope:
- human decision:
- files read:
- files changed:
- next status command:
```

If execution is allowed and performed, write/update only the protocol files required for that allowed action and end with the next recommended `$harnessloop-status` check.

## Safety Rules

- Do not continue without reading current state and latest decision.
- Do not turn neutral feedback into success.
- Do not treat every blocked state as a user pause; classify the blocker first.
- Do not bypass human-confirm states, missing evidence, failed intake, failed self-audit, unavailable named tools, ambiguous external-system parameters, or unsafe writes.
- Do not perform cleanup, trigger, rollback, or other external writes from a runtime-recovery round without explicit write-safety details and human confirmation when required.
- Do not rely on subagent or swarm model/effort claims that have not passed `$harnessloop-delegation` or equivalent file-backed environment self-check.
- Do not infer named-tool substitutions or external-system access details; ask the user first.
- Do not accept a round after failed adversarial review unless the control contract and human decision explicitly allow it.
- Do not evaluate evidence, control, environment, self-audit, or delegation gates before the setup gate; `gate_blocking: true` short-circuits directly to `needs-setup`. `gate_blocking: false` with `complete: false` is not a block — surface the gap as a warning and proceed.
