# Transfer Packet Template

```markdown
# Harnessloop Transfer Packet

## 1. Task Identity

- Original user goal:
- Current agent environment:
- Project/repository path:
- Current branch:
- Why this is a long-running task:

## 2. Goal Contract

- Current goal interpretation:
- Non-goals:
- Success condition:
- Acceptance criteria:
- Required human decisions:
- Goal ambiguity:

## 3. Progress State

- Completed:
- In progress:
- Not started:
- Smallest next step:
- Can continue now: yes | no | unknown

## 4. Change State

- Modified files:
- Added files:
- Deleted files:
- Key diff summary:
- Unverified changes:
- Rollback recommendation or risk:

## 5. Documentation Inventory

| Path or URL | Source of truth | Last updated | Trust level | Relationship to goal | Sensitive content |
| --- | --- | --- | --- | --- | --- |

## 6. Process Artifact Inventory

| Path, URL, or command | Artifact type | Status | How Harnessloop should use it |
| --- | --- | --- | --- |

## 7. Evidence State

- Commands run and results:
- Test/build/CI/runtime results:
- Data sources:
- External system sources:
- Evidence paths:
- Claims without evidence:

## 8. External Tool And Access Contract

| Tool name | Purpose | Read/write permissions | Account role | Permission scope | Local parameter references | Access verification method | Failure handling |
| --- | --- | --- | --- | --- | --- | --- | --- |

## 9. Credential Requirements And Secret Handling

Do not include secret values.

| Secret name | Storage | Required scope | Used by | Verification command | Current status | Human action required |
| --- | --- | --- | --- | --- | --- | --- |

## 9.1 Local Channel Parameter Requirements

Do not include parameter values. List only keys, storage/provider references, and expected presence.

| Channel ID | Parameter key | Sensitivity | Storage | Reference | Required for | Current status |
| --- | --- | --- | --- | --- | --- | --- |

## 10. Decision Log

- Key decisions made:
- Rejected alternatives:
- Evidence behind decisions:
- Unconfirmed assumptions:

## 11. Risk And Blockers

- Current blockers:
- High-risk areas:
- Dead-loop, drift, or contradiction risks:
- Source session uncertainty:

## 12. Next Handoff Recommendation

- Recommended Harnessloop goal:
- Recommended first subgoal or task:
- Recommended first round scope-lock:
- Recommended verification conditions:
- Recommended adversarial review focus:

## 13. Unknowns And Questions For Human
```
