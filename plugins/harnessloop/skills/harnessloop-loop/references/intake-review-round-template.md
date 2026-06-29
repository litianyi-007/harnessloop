# Intake Review Round Template

```markdown
# Intake Review Round

## Objective

Verify an imported transfer packet before business execution.

## Scope Lock

Allowed:

- Read transfer packet.
- Read cited documents, process artifacts, evidence, and tool/access descriptions.
- Write intake gate, gap review, evidence index updates, and formal goal draft.

Disallowed:

- Business code changes.
- Data contract relaxation.
- Acceptance of uncited completed work.

## Required Checks

- Transfer packet is evidence-backed.
- Source-of-truth documents are identified.
- Process artifacts are traceable.
- External tool access and credential requirements are clear without secret values.
- Next action is minimal.
- Human decision requirements are explicit.

## Outputs

- `intake-gate.md`
- `gap-review.md` when needed
- `.harnessloop/state/evidence-index.md` updates when accepted
- Formal goal directory when accepted
```

