# Self-Audit Template

```markdown
# Self Audit

## Audit Metadata

- Audit ID:
- Trigger: setup | pre-continue | post-feedback | scheduled | pre-blocked
- Active goal:
- Active round:
- Auditor:
- Timestamp:

## Loop Health

| Check | Status | Evidence path | Notes |
| --- | --- | --- | --- |
| Dead loop risk | pass |  |  |
| Self-contradiction | pass |  |  |
| Goal drift | pass |  |  |
| Evidence drift | pass |  |  |
| Validation drift | pass |  |  |
| Handoff stagnation | pass |  |  |
| Cost/context runaway | pass |  |  |

Status values: `pass`, `warn`, `fail`, `unknown`.

## Deterministic Signals

| Signal | Current value | Previous value | Threshold | Status |
| --- | --- | --- | --- | --- |
| Recent feedback sequence |  |  | no repeated neutral/negative without new evidence | unknown |
| Repeated next action count |  |  | max 2 identical actions | unknown |
| Scope-lock version |  |  | must change after failed action unless rollback | unknown |
| Goal contract version/hash |  |  | no silent change | unknown |
| Threshold version/hash |  |  | no silent change | unknown |
| Data contract version/hash |  |  | no silent change | unknown |
| Verification command set |  |  | no silent change | unknown |
| Stale evidence count |  |  | 0 for acceptance | unknown |
| Open handoff age |  |  | project-defined | unknown |
| Main-session raw context risk |  |  | raw logs stay in evidence files | unknown |
| Delegation model/effort verified |  |  | required for high-risk delegation | unknown |

## Local Repair Decision

- Required repair:
- Smallest safe next action:
- Human confirmation required:
- Block execution until repaired:

## Evolution Issue Decision

- Create upstream evolution issue: yes | no
- Reason:
- Issue path:
- Redaction notes:
```
