# Data Contract Template

```markdown
# Data Contract

## Valid Evidence Sources

| Source | Type | Access method | Freshness | Validation method | Drift risk | Credential requirement |
| --- | --- | --- | --- | --- | --- | --- |

## Valid Tools And Systems

| Tool/system | Purpose | Read/write scope | Account role | Verification command | Failure handling | Local parameter reference |
| --- | --- | --- | --- | --- | --- | --- |

## Local Channel Parameter Requirements

| Channel ID | Parameter key | Sensitivity | Storage | Required for | Must be present before |
| --- | --- | --- | --- | --- | --- |

## Invalid Evidence

## Secret Handling

- Do not store secret values in Harnessloop files.
- Store secret names, local parameter keys, required scopes, configured storage, and verification commands only.
- Use `.harnessloop/local/channel-params.json` for local ignored values or provider references.

## Revision Policy

- Human confirmation required for source changes: yes | no
- Human confirmation required for threshold changes: yes | no
```
