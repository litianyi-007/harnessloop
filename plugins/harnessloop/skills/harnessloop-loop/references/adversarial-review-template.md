# Adversarial Review Template

```markdown
# Adversarial Review

## Review Scope

- Goal:
- Round:
- Scope lock:
- Reviewer:
- Timestamp:

## Evidence Used

| Evidence ID | Path | What it proves | Limitations |
| --- | --- | --- | --- |

## Checks

| Check | Result | Evidence path | Notes |
| --- | --- | --- | --- |
| Goal alignment | unknown |  |  |
| Scope-lock post-hoc edit | unknown | `git log -p -- <round>/scope-lock.md` | If this round's scope-lock was edited after its evidence existed, decision.md must already record why |
| Mechanical gate record | unknown | `<round>/decision.md` | Must carry the `Mechanical gate` line, and its coverage numbers must match an actual run |
| Scope-lock compliance | unknown |  |  |
| Data thresholds | unknown |  |  |
| Verification thresholds | unknown |  |  |
| Runtime validation | unknown |  |  |
| Source/source-data consistency | unknown |  |  |
| Drift or contradiction risk | unknown |  |  |

## Finding

## Feedback

positive | negative | neutral | blocked

## Required Next Action
```

