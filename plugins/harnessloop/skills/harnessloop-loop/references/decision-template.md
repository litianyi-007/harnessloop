# Decision Template

```markdown
# Decision

- Feedback: positive | negative | neutral | blocked
- Blocker type: none | runtime-recoverable | access-missing | write-safety-required | human-decision-required | contract-insufficient | external-system-unsafe | unknown
- Recovery eligible: yes | no | unknown
- Accepted: yes | no
- Active goal:
- Active round:
- Decision maker:
- Timestamp:

## Reason

## Evidence Cited

| Evidence ID | Path | Role in decision |
| --- | --- | --- |

## Next Action

- Action type: next-subgoal | investigation | minimal-fix | rollback | contract-revision | human-input | blocked
- Scope-lock required: yes | no
- Human confirmation required: yes | no
- Safe without user input: yes | no
- Recovery round objective:
- Disallowed until confirmed:
```
