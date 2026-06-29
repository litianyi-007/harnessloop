# Feedback Policy Template

```markdown
# Feedback Policy

## Feedback Classes

Positive:

- Expected behavior:
- Required evidence:
- Next action:

Negative:

- Execution-fault checks:
- Goal/business-fault checks:
- Default priority:

Neutral:

- Why evidence may be inconclusive:
- Treat as negative until:

## Negative Feedback Actions

Allowed next actions:

- continue-investigation
- minimal-fix
- rollback-prior-execution
- revise-contract-with-human-confirmation
- blocked-human-decision

## Blocked Feedback Actions

Classify before stopping:

- runtime-recoverable: enter read-only investigation or recovery-planning round.
- access-missing: ask for missing endpoint, credential reference, local parameter, permission, account role, or tool.
- write-safety-required: ask for dry-run, test resource, rollback path, and human confirmation before mutation.
- human-decision-required: ask for product, business, risk, policy, acceptance, or cleanup decision.
- contract-insufficient: repair goal, threshold, evidence, or control contract.
- external-system-unsafe: allow only bounded observation until safety is established.
- unknown: ask for facts needed to classify.

## Round Decision Format

Feedback class:

Blocker type:

Recovery eligible:

Evidence paths:

Fault hypothesis:

Chosen next action:

Next scope-lock:
```
