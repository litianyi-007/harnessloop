# Scope Lock

## Objective

Capture runtime evidence and run adversarial review.

## Allowed Changes

- Write evidence under `rounds/0001/evidence/`.
- Write review under `rounds/0001/reviews/`.
- Write decision and archive handoffs.

## Disallowed Changes

- Source code changes.
- Data contract changes.
- Threshold changes during the round.

## Verification

- Runtime output exists.
- Review cites runtime output.

## Rollback Condition

Delete round 0001 files if evidence was captured from the wrong project or wrong command.

