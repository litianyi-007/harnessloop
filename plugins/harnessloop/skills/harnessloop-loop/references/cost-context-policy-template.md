# Cost And Context Policy Template

```markdown
# Cost And Context Policy

## Main Session

Responsibilities:

- Orchestration:
- Core decisions:
- Final acceptance:

Must not spend context on:

- Large raw logs:
- Full external reports:
- Repeated source dumps:

## Delegation Rules

Use subagent or swarm for:

- Read-only discovery:
- Evidence collection:
- Low-context execution:
- Adversarial review:
- Acceptance testing:

Do not delegate:

- Goal interpretation:
- Goal breakdown approval:
- Scope-lock changes:
- Human-required product or business decisions:
- Acceptance after failed review:

## Execution Delegation Matrix

| Task type | Delegation decision | Goal | Value | Preconditions | Never delegate when |
| --- | --- | --- | --- | --- | --- |
| Read-only discovery | should delegate |  |  |  |  |
| Evidence collection | delegate when bounded and read-only |  |  |  |  |
| External connectivity check | main gate or `$harnessloop-connectivity` |  |  |  |  |
| Low-risk local implementation | may delegate |  |  |  |  |
| High-risk or cross-cutting implementation | main session owns; delegate narrow subtasks only |  |  |  |  |
| Adversarial review | must delegate when verifiable |  |  |  |  |
| Acceptance testing | should delegate when independent |  |  |  |  |
| Round acceptance and control decisions | never delegate |  |  |  |  |

## Model Policy

Codex:

- Independent investigation:
- Low-context execution:
- Adversarial review:
- Core decisions:

Claude Code:

- Independent investigation:
- Low-context execution:
- Adversarial review:
- Core decisions:

## Handoff Budget Rules

Input limit:

Output limit:

Evidence path requirement:

Summary requirement:

Context that must stay out of main session:
```
