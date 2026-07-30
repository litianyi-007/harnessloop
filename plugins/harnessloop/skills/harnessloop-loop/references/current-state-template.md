# Current State Template

`- Last accepted round:` is scoped to this SAME file's own `- Active goal:`
(TH-0018 ruling, evolution-issues/0018-current-md-accepted-round-
annotation-contradiction.md): it names the last round, **under the
currently active goal**, whose `decision.md` declares `- Accepted: yes` —
not "the last round accepted anywhere in the project's history". It must
be updated (or explicitly noted as none-yet) whenever `- Active goal:`
switches to a new goal; a stale annotation left over from the previous
goal reads as a false claim about the new one.
`verify_protocol.py`'s `check_current_last_accepted_round` mechanically
checks both halves of this (the declared round is under `Active goal`,
and that round's own `decision.md` really is `Accepted: yes`) but reports
any mismatch against this file, never against the round named — see
harnessloop-loop/SKILL.md's Mechanical Gate Boundary OUT column.

```markdown
# Current State

- Active goal:
- Active round:
- Current feedback:
- Blocker type:
- Recovery eligible:
- Open handoffs:
- Last accepted round:
- Next proposed action:
- Next action safety: read-only | write | external-trigger | human-decision | unknown
- Human decision requirement:
- Blocking reason:
- Recovery round:
- Imported intake path:
- State sources:
```
