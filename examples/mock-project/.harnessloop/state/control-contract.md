# Control Contract

## Auto-Continue States

- Positive feedback with all evidence valid.
- Negative feedback when next action is investigation, minimal fix, or rollback within the current scope-lock.

## Human-Confirm States

- Data contract revision.
- Scope-lock expansion.
- Acceptance after failed adversarial review.

## Stop Conditions

- Missing required external access.
- Evidence cannot be refreshed or cited.
- Self-audit finds contradiction that needs a product decision.

## Blocker Classification

- runtime-recoverable: continue into read-only investigation or recovery planning.
- access-missing: ask for missing access facts.
- write-safety-required: ask for dry-run, rollback, and human confirmation before mutation.
- human-decision-required: ask for the required decision.
