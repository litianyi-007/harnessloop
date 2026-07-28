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

If `.harnessloop/` exists but `check_setup.py` reports `complete: false`, report `setup-incomplete`, surface `field_todo_count` and `selfcheck_todo_count` and every non-`filled` file's `missing_sections`, and suggest `$harnessloop-setup`. Do not run the wizard from this skill.

## Processing Contract

1. Read `.harnessloop/state/current.md` first when present.
2. Run `python3 -B <plugin-root>/skills/harnessloop-loop/scripts/check_setup.py --project <target-project> --json` (the `-B` flag, or `PYTHONDONTWRITEBYTECODE=1`, guarantees no `__pycache__` bytecode is written, keeping this step strictly read-only). If it reports `complete: false`, set state to `setup-incomplete` and record `field_todo_count` and `selfcheck_todo_count`, the first non-`filled` file, and its `missing_sections` as the setup completeness and next setup step. Note whether `gate_blocking` is `true` (a core policy file — environment/control-contract/cost-context-policy — is still `template`/`missing`) or `false` (only non-blocking gaps, such as `data-sources.md` or `self-check.md`, remain); report this distinction so the user knows whether `$harnessloop-continue` will short-circuit.
3. Run `python3 -B <plugin-root>/skills/harnessloop-loop/scripts/verify_protocol.py --project <target-project> --json` (read-only, no writes) and read `coverage.loop_autocontinue_anomaly`, `coverage.loop_anomaly_skipped_unparsable`, and any `loop-contract-profile-missing` violation (docs/loop-stop-record-spec-20260728.md §4/§5, Appendix B.1). If `loop_autocontinue_anomaly` is non-zero, or `loop-contract-profile-missing` is present, show it at the very top of the Output Contract, above `state:`, and check `state/self-audit.md`'s `## Loop Continuation Anomalies` section (or equivalent) for whether this round/goal already has a recorded acknowledgement; if not, report it as unacknowledged. **This step is read-only reporting only** — status itself never writes the acknowledgement (that would violate this skill's own no-mutation mandate); it tells the user/agent an acknowledgement is expected via `$harnessloop-continue` or a manual `state/self-audit.md` edit, and this expectation is a discipline this skill and `$harnessloop-continue` are asked to follow, not something the mechanical gate itself enforces or checks was followed.
4. Follow only the source paths referenced by current state, active goal, active round, open handoffs, latest decision, evidence index, control contract, environment self-check, and self-audit.
5. Summarize evidence health without revalidating external systems unless the user explicitly asks for evidence checking; route that to `$harnessloop-evidence`.
6. Report contradictions, missing state files, stale pointers, unresolved human decisions, intake blockers, blocker type, recovery eligibility, and next action safety.
7. Do not mutate any file, run continuation gates, execute tests as business work, or change feedback classification.

## Output Contract

Return a concise status report:

```text
Harnessloop status:
- project:
- unacknowledged loop-autocontinue anomaly: <count, from `coverage.loop_autocontinue_anomaly`> — shown here, before `state:`, whenever non-zero (see Processing Contract step 3)
- state: initialized | not-initialized | setup-incomplete | inconsistent | blocked
- setup completeness:
- setup gate: complete | warning | blocking
- field todo count:
- selfcheck todo count:
- setup next step:
- active goal:
- active round:
- current feedback:
- verdict mix: <pass>/<pass-with-residual>/<fail>/<inconclusive> across this goal's decisions (drift signal only, not a control)
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
- Running `check_setup.py` with `-B`/`PYTHONDONTWRITEBYTECODE=1` satisfies the read-only mandate above: it performs no writes (including bytecode cache), no external probing, and no continuation decision. The same applies to running `verify_protocol.py --json` for the anomaly check in Processing Contract step 3 — it is a read-only mechanical gate, and this skill only reads its output, never writes the acknowledgement itself.
- Surfacing an unacknowledged `loop_autocontinue_anomaly` prominently (Processing Contract step 3) is a discipline this skill is asked to follow, not a mechanical requirement: `verify_protocol.py` does not check whether status actually displayed it, so this is the same family of gap as "a round can write `Feedback: positive` without anyone having run the verification step first" — expected practice, not a machine-enforced guarantee.
