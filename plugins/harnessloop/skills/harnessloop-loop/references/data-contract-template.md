# Data Contract Template

```markdown
# Data Contract

## Valid Evidence Sources

| Source | Type | Access method | Freshness | Validation method | Drift risk | Credential requirement |
| --- | --- | --- | --- | --- | --- | --- |

## Valid Tools And Systems

| Tool/system | Purpose | Read/write scope | Account role | Verification command | Failure handling |
| --- | --- | --- | --- | --- | --- |

## Invalid Evidence

## Secret Handling

- Do not store secret values in Harnessloop files.
- Store secret names, required scopes, configured storage, and verification commands only.

## Revision Policy

- Human confirmation required for source changes: yes | no
- Human confirmation required for threshold changes: yes | no
```

