# Evidence Index Template

```markdown
# Evidence Index

| Evidence ID | Type | Path | Applies to | Freshness requirement | Observed timestamp | Validation method | Citation required | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Status Values

- `valid`: evidence exists, is fresh enough, and can be cited.
- `stale`: evidence exists but violates freshness or drift rules.
- `missing`: evidence path or source is absent.
- `inconclusive`: evidence exists but cannot support acceptance.
- `blocked`: evidence requires human access or external setup.

## Evidence Types

- static
- dynamic
- runtime
- source
- human-confirmation
```

