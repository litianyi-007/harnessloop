---
name: harnessloop-delegation
description: "Use when the user references harnessloop:delegation, asks to check subagent or swarm readiness, verify delegated task model/effort success, inspect delegation capability, record expected versus observed model/reasoning, or decide whether Harnessloop may delegate discovery, evidence collection, execution, adversarial review, or acceptance testing."
---

# Harnessloop Delegation

Check whether Harnessloop can safely rely on subagents, swarm, or another delegated execution mechanism. This skill is a control-plane check; it does not perform business execution or accept a round.

## Input Contract

Accept an explicit skill invocation such as `$harnessloop-delegation`, `$harnessloop-delegation check`, or `$harnessloop-delegation check handoff <path>`. Treat `harnessloop:delegation` as a natural-language alias only; `$harnessloop:delegation` is not a valid skill invocation.

Useful input includes:

- `target-project`: defaults to the current working directory.
- `task-type`: read-only discovery, evidence collection, low-context execution, adversarial review, acceptance testing, or unknown.
- `delegation-mechanism`: Codex subagent, Claude Code swarm, Claude Code subagent, external worker, manual handoff, or unknown.
- `expected-model` and `expected-effort`: from `setup/cost-context-policy.md` or user instruction.
- `observed-model` and `observed-effort`: only when directly reported by the delegated mechanism or reliable metadata.
- `handoff-path`: delegated handoff file, if checking an existing or completed handoff.
- `scope`: read-only, write-bounded, review-only, or unknown.
- `verification-method`: how model, effort, scope boundaries, output path, and evidence citations can be checked.

If any required fact is missing, ask a focused question. Do not infer model, effort, tool identity, delegation mechanism, or success from surrounding context.

## Processing Contract

1. Read `.harnessloop/setup/cost-context-policy.md`, `.harnessloop/state/environment.md`, `.harnessloop/state/self-check.md`, `.harnessloop/meta/self-audit.md`, current state, active round handoffs, and the requested handoff path when present.
2. Determine the expected delegation policy for the task type: allowed, preferred, optional, degraded, or forbidden.
3. Verify whether the environment can create independent tasks, constrain read/write scope, require output paths, and verify evidence citations.
4. Compare expected model/effort with observed model/effort only when observed values are explicit and verifiable.
5. If observed model/effort cannot be verified, mark it `unknown`; do not mark delegation successful.
6. If a specific delegation tool or mechanism is named but unavailable, ambiguous, misspelled, or not exposed in the current environment, ask the user to confirm the correct mechanism before substituting.
7. For high-risk, cross-cutting, write-capable, or external-system delegation, require verified mechanism, scope boundaries, output path, evidence citation behavior, and expected versus observed model/effort.
8. Write or recommend updates to `.harnessloop/state/environment.md`, `.harnessloop/state/self-check.md`, active handoff closeout, or `.harnessloop/meta/self-audit.md` when the check changes delegation health.

## Output Contract

Return a delegation report:

```text
Harnessloop delegation check:
- project:
- requested task type:
- delegation mechanism:
- expected model:
- observed model:
- expected effort/reasoning:
- observed effort/reasoning:
- mechanism status: verified | unavailable | ambiguous | unknown
- scope control: pass | warn | fail | unknown
- output path control: pass | warn | fail | unknown
- evidence citation control: pass | warn | fail | unknown
- model/effort match: pass | warn | fail | unknown
- result: pass | warn | fail | blocked | unknown
- allowed delegation: yes | no | conservative-only | human-confirmation-required
- files read:
- files changed:
- missing fields:
- questions for user:
- next action:
```

## Decision Rules

- `pass`: mechanism, scope, output path, evidence citation behavior, and expected versus observed model/effort are verified enough for the requested risk level.
- `warn`: delegation may proceed only for low-risk or read-only work, with residual risk recorded.
- `fail`: a required delegation condition was contradicted or unsafe.
- `blocked`: a required fact is missing and must be answered before delegation.
- `unknown`: the environment cannot prove the requested condition; use the main session, conservative handoffs, or human confirmation.

## Safety Rules

- Do not treat a delegated result as valid just because it returned content.
- Do not assume Codex, Claude Code, subagent, swarm, model, or effort from product branding alone.
- Do not delegate final goal interpretation, goal breakdown approval, scope-lock changes, human-required decisions, or round acceptance.
- Do not perform external-system access checks from this skill; route channel inventory to `$harnessloop-channels` and connectivity checks to `$harnessloop-connectivity`.
- If delegation degradation affects continuation, route to `$harnessloop-continue` after recording the check.
