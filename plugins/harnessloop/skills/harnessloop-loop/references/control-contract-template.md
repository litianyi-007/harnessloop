# Control Contract Template

```markdown
# Control Contract

## Auto-Continue

Allowed when:

- Feedback class:
- Evidence health:
- Environment self-check:
- Open handoffs:
- Human confirmation:

## Human Confirmation Required

Required for:

- Scope-lock mutation:
- Evidence contract revision:
- Control contract revision:
- Failed review acceptance:
- Rollback:
- Irreversible or external-system write:

## Stop Conditions

Stop when:

- Blocking condition:
- Blocker type:
- Missing evidence:
- Environment mismatch:
- Model/effort mismatch:
- Contract cannot be evaluated:

## Blocker Classification

| Type | Continue behavior | User input required |
| --- | --- | --- |
| runtime-recoverable | Start read-only investigation or recovery-planning round | no |
| access-missing | Stop and ask for missing access/tool facts | yes |
| write-safety-required | Stop before mutation; ask for write safety and confirmation | yes |
| human-decision-required | Stop and ask for decision | yes |
| contract-insufficient | Repair contract before execution | maybe |
| external-system-unsafe | Allow bounded observation only | maybe |
| unknown | Ask for facts needed to classify | yes |

## Delegation Boundaries

Allowed delegated work:

Disallowed delegated work:

Required handoff evidence:

## Acceptance Authority

Round acceptance:

Failed review escalation:

Blocked state unblock requirement:

Recoverable blocker auto-round policy:
```
