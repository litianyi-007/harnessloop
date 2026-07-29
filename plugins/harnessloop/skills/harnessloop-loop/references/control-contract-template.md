# Control Contract Template

```markdown
# Control Contract

## Auto-Continue

Canonical fields (machine-parsed by `verify_protocol.py`'s loop-autocontinue
anomaly gate; docs/loop-stop-record-spec-20260728.md §5, Appendix B.1):

- Profile: lite | standard | strict | custom
- Auto-continue on positive: yes | no
- Auto-continue on negative/neutral remediation: yes | no

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

## Pre-Authorized Test-Resource Writes (optional)

TH-0022 (evolution-issues/0022-test-resource-write-preauth-no-anchor.md,
user ruling ③): the ONLY legal landing spot for declaring that a specific
test-resource-scoped write/cleanup on an already-declared external system
(`.harnessloop/setup/external-systems.json`) is pre-authorized, narrowing
`write-safety-required`'s stop condition (see
`harnessloop-continue/SKILL.md`) for exactly that named write and nothing
else. This section is never pre-filled by the plugin, by `$harnessloop-setup`,
or by any profile in `control-contract-profiles.md` — absent or empty means
no pre-authorization exists, and every write remains `write-safety-required`
exactly as it was before this section existed (zero migration). Declaring a
row here never relaxes `Human Confirmation Required`'s `Irreversible or
external-system write` row above — a production system or an irreversible
operation is never eligible for pre-authorization here, regardless of what
this table says, and this section may only narrow, never widen, that row.

| System id | Operation class | Resource scope | Cleanup contract | Authorized by |
| --- | --- | --- | --- | --- |

`System id` must match an id already declared in
`.harnessloop/setup/external-systems.json`. `Operation class` is one of
`probe-read` / `test-resource-create` / `test-resource-delete` / `cleanup`.
`Resource scope` states exactly what may be touched (e.g. a naming
convention or path prefix that marks a resource as test-only). `Cleanup
contract` states what must happen afterward (e.g. "delete every resource
this operation created, verified by listing the scope empty afterward").
`Authorized by` names who/what approved this row (a human, or a prior
control-contract revision's own confirmation).

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
