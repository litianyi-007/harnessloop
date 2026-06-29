# Evidence Index Template

```markdown
# Evidence Index

| Evidence ID | Type | Path | Applies to | Freshness requirement | Observed timestamp | Validation method | Citation required | Artifact health | Claim support | Acceptance effect | Reproducibility | Sensitivity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Artifact Health Values

- `valid`: evidence exists, is fresh enough, and can be cited.
- `stale`: evidence exists but violates freshness or drift rules.
- `missing`: evidence path or source is absent.
- `inconclusive`: evidence exists but cannot support acceptance.
- `blocked`: evidence requires human access or external setup.

## Claim Support Values

- `supports`: supports the claim being tested.
- `refutes`: refutes the claim being tested.
- `partial`: supports only part of the claim.
- `unrelated`: valid artifact but not relevant to the claim.
- `unknown`: claim relationship has not been assessed.

## Acceptance Effect Values

- `pass`: contributes to accepting a round.
- `fail`: contributes to rejecting a round.
- `neutral`: cited but not decisive.
- `blocked`: cannot be evaluated without access or human action.

## Evidence Types

- static
- dynamic
- runtime
- source
- human-confirmation
```
