# Data Sources Template

```markdown
# Data Sources

## Static Sources

| Source | Access method | Freshness requirement | Drift risk | Validation method | Credential requirement |
| --- | --- | --- | --- | --- | --- |

## Dynamic Or Generated Sources

| Source | Generator/tool | Refresh expectation | Drift risk | Validation method | Credential requirement |
| --- | --- | --- | --- | --- | --- |

## Runtime Validation Systems

| System | Access method | Validation method | Pass condition | Failure handling | Credential requirement | Local parameter reference |
| --- | --- | --- | --- | --- | --- | --- |

## External Tools And Platforms

| Tool/platform | Purpose | Read/write scope | Account role | Verification method | Failure handling | Local parameter keys |
| --- | --- | --- | --- | --- | --- | --- |

## Local Channel Parameters

Store reusable channel parameter keys in `.harnessloop/local/channel-params.json`, which must be ignored by `.harnessloop/local/.gitignore`.

| Channel ID | Parameter key | Sensitivity | Storage | Reference | Required for | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Secret Handling

Do not write secret values here. Record only secret names, storage locations, required scopes, and verification commands.
```
