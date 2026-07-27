# Decision Template

```markdown
# Decision

- Feedback: positive | negative | neutral | blocked
- Verdict: pass | pass-with-residual | fail | inconclusive
- Residuals: none | <one per line: what was claimed / which part is uncovered / where it is deferred>
- Blocker type: none | runtime-recoverable | access-missing | write-safety-required | human-decision-required | contract-insufficient | external-system-unsafe | unknown
- Recovery eligible: yes | no | unknown
- Accepted: yes | no
- Review: <project-contained path to the review artifact> | none — <non-empty reason no review was done>
- Reviewer: <identity of who/what performed the review, e.g. a vendor name or "main-session">
- Review verdict: pass | pass-with-note | rework | fail | not-applicable
- Review digest: <sha256 of the Review file, optional>
- Mechanical gate: <exit-code> / <the coverage line printed by verify_protocol.py, verbatim> / <when it was run>
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
