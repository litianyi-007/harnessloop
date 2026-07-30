# Environment Self-Check Template

`Pass/fail:` (in `## Result` below) takes one of three values: `pass |
pass-with-open-items | fail`. TH-0017 ruling (a) (evolution-issues/0017-
environment-todo-vs-pass-semantics-unclear.md): a literal `TODO (owner:
user)` marker anywhere in this file is the setup wizard's own legitimate
owner-occupant placeholder — the record of a step the user chose to skip,
not a claim that the step is unfinished — and it does not, by itself,
block `pass`. But when this file still carries any `TODO (owner: user)`
marker, `Pass/fail:` must say so itself: use `pass-with-open-items` and
give the count of open items in that same field (e.g. `pass-with-open-
items（3 open items）`), not folded into a free-text remark elsewhere in
the file. `verify_protocol.py`'s `check_environment_pass_with_open_todos`
(kind `environment-pass-with-open-todos`) enforces exactly this: any
literal `TODO (owner: user)` marker in this file plus a bare `Pass/fail:
pass` is reported; `pass-with-open-items` and `fail` are both unaffected.

```markdown
# Environment Self-Check

## Detection

Detected environment: codex | claude-code | other | unknown

Detected from:

Available tools:

Unavailable tools:

## Delegation

Expected mechanism:

Observed mechanism:

Can create independent task:

Can constrain read/write scope:

Can require output path:

Can verify evidence citations:

## Model And Effort

Expected model:

Observed model:

Expected effort/reasoning:

Observed effort/reasoning:

Verification method:

Mismatch action:

Residual risk:

## Result

Pass/fail: pass | pass-with-open-items | fail

Allowed next actions:

Required human action:

Last checked:
```

