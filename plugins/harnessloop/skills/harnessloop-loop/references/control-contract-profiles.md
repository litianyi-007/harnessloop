# Control Contract Profiles

Full `lite` / `standard` / `strict` presets for the 24 leaf fields of `control-contract-template.md`. `$harnessloop-setup` step S4 shows the summary below, asks the user to pick one with `AskUserQuestion`, builds a diff of the current `state/control-contract.md` against the selected profile's full content, and writes it only after the user sees that diff. Re-selecting a profile later — including switching from one profile to another — follows the same diff-and-confirm flow; it never silently overwrites.

All three profiles cover every leaf field; none is left blank. The `Blocker Classification` table is identical across all three profiles and is not reproduced per profile below — it is the protocol's own 7-category blocker taxonomy, already prefilled in `control-contract-template.md` (`runtime-recoverable`, `access-missing`, `write-safety-required`, `human-decision-required`, `contract-insufficient`, `external-system-unsafe`, `unknown`), and no profile changes it.

- **`lite`**: personal or low-risk projects. Most positive or runtime-recoverable investigation auto-continues; only external writes, failed-review acceptance, and material evidence-contract changes require a human.
- **`standard`** (default): positive feedback with fully-valid evidence auto-continues; evidence-contract and control-contract changes require a human.
- **`strict`**: projects touching external systems or sensitive data. Human confirmation is required before continuing even when every automatic condition is met.

## Canonical Auto-Continue Fields (machine-parsed)

Three fields added by docs/loop-stop-record-spec-20260728.md §5 (Appendix
B.1 restated): `verify_protocol.py`'s loop-autocontinue anomaly gate
(`check_loop_autocontinue_anomaly`) parses these, not the free-text rows
below, and they are **not** part of `check_setup.py`'s existing 24-leaf-field
completeness manifest for `control-contract.md` — that manifest is
unchanged by this addition, so an existing filled-in contract does not
regress to "incomplete" merely for predating these three lines. `custom` has
no preset row here (a hand-authored contract, not one of the three profiles
`$harnessloop-setup` renders) but is still a legal `Profile:` value the gate
recognizes.

| Field | lite | standard (default) | strict |
| --- | --- | --- | --- |
| Profile | lite | standard | strict |
| Auto-continue on positive | yes | yes | no (Human Confirmation below requires confirmation even when every condition is met, so nothing auto-continues on `positive` alone) |
| Auto-continue on negative/neutral remediation | yes (Feedback class row already lists T2 auto-continue explicitly) | no (§0's corrected ruling: standard's Feedback class row lists only `positive`) | no |

## Auto-Continue (Allowed when)

| Field | lite | standard (default) | strict |
| --- | --- | --- | --- |
| Feedback class | positive; or negative/neutral when the next step is read-only investigation, a minimal fix, or a rollback within this round's scope-lock | positive | positive, and any external-system write in this round has already passed independent human acceptance |
| Evidence health | no stale evidence; inconclusive evidence may exist but must not by itself support acceptance | every evidence-index entry has artifact health = valid | every entry valid; any entry with secret/sensitive sensitivity never supports auto-continue |
| Environment self-check | pass, or unknown when delegation is limited to read-only work | pass | pass, and observed model/effort has been verified by `$harnessloop-delegation` (not just the expected value) |
| Open handoffs | no open handoff in `blocked` state | no open handoff | no open handoff, and the prior round's adversarial review concluded positive |
| Human confirmation | not required — auto-continue to the next subgoal or read-only investigation round when conditions are met | not required — auto-continue to the next subgoal or task when conditions are met | required — human confirmation before the next subgoal even when every condition above is met |

## Human Confirmation Required (Required for)

| Field | lite | standard | strict |
| --- | --- | --- | --- |
| Scope-lock mutation | not required (main session may narrow or broaden autonomously; must be recorded in `decision.md`) | required to broaden; not required to narrow | required (any direction of change) |
| Evidence contract revision | required whenever the revision changes acceptance criteria, weakens the validation bar, broadens evidence scope, or affects continuation — this aligns with `harnessloop-evidence`'s hard confirmation constraint and is not relaxed by any profile. Evidence-contract maintenance edits outside these four conditions (adding a citation path, fixing a typo, adding a timestamp to an already-accepted source) may still be recorded by the main session on its own, without human confirmation | required | required |
| Control contract revision | required | required | required |
| Failed review acceptance | required (protocol-level hard constraint; no profile may turn this off) | required | required |
| Rollback | not required (main session may roll back an execution it has already classified as wrong, on its own; must be recorded) | required | required, and must state whether the rollback touches an external system |
| Irreversible or external-system write | required | required | required, and must declare a dry-run/rollback plan in advance |

Note on `Evidence contract revision`: the four trigger conditions (changes acceptance criteria / weakens validation / broadens evidence scope / affects continuation) are a protocol-level hard constraint owned by `$harnessloop-evidence`, not a control-contract policy choice — every profile requires human confirmation whenever any one of the four is true. What `lite` relaxes is only the maintenance-level editing that falls **outside** all four conditions; `standard`/`strict` do not carve out that exception and simply require confirmation for any evidence-contract edit.

## Stop Conditions (Stop when)

| Field | lite | standard | strict |
| --- | --- | --- | --- |
| Blocking condition | access-missing / human-decision-required / write-safety-required, and the next action needs external-system write permission | same as lite, plus contract-insufficient | same as standard, plus: any external-system-unsafe condition always stops — no bounded observation |
| Blocker type | adopt the protocol's 7 categories as-is | same as lite | same as lite, but external-system-unsafe never auto-continues at a "maybe" level |
| Missing evidence | stop when evidence required for acceptance has artifact health = missing/blocked (stale/inconclusive evidence may still support read-only investigation) | stop when any acceptance-relevant evidence is not valid | same as standard, plus: secret/sensitive evidence must be human-confirmed before it can be marked valid |
| Environment mismatch | stop only when the delegated task involves acceptance/writes and self-check = fail | stop when environment self-check is not pass | same as standard, plus: re-verify at the start of every round; never reuse the prior round's conclusion |
| Model/effort mismatch | stop only for high-risk delegation (adversarial review/acceptance testing) when observed does not match expected | stop for any delegation when observed does not match expected and it has not been reviewed by `$harnessloop-delegation` | stop for any delegation, including read-only discovery, when observed does not match expected |
| Contract cannot be evaluated | stop when a key control-contract/evidence-index field is missing and cannot be derived | stop when any required field of control-contract/evidence-index/goal is empty | same as standard, plus: a missing Acceptance Authority field also counts as an incomplete contract |

## Delegation Boundaries

| Field | lite | standard | strict |
| --- | --- | --- | --- |
| Allowed delegated work | read-only discovery, evidence collection, low-risk local implementation, adversarial review, acceptance testing (everything in the execution delegation matrix except round acceptance and control decisions) | same as lite, but high-risk/cross-cutting implementation may only delegate an isolated subtask of it | read-only discovery, evidence collection (excluding sensitive/secret data), adversarial review, acceptance testing; local implementation stays with the main session, or is delegated only as an already-approved, narrowest subtask |
| Disallowed delegated work | goal interpretation, breakdown approval, scope-lock changes, human-required business decisions, acceptance after failed review, round acceptance | same as lite | same as standard, plus: any external-system write, any secret/sensitive data read |
| Required handoff evidence | file path + conclusion summary | file path + conclusion summary + evidence health | file path + conclusion summary + evidence health + actual verification record of the delegated model/effort |

## Acceptance Authority

| Field | lite | standard | strict |
| --- | --- | --- | --- |
| Round acceptance | main session decides autonomously | main session decides, and must cite evidence paths in `decision.md` | same as standard, plus: confirm environment/delegation gates both pass before every round's acceptance |
| Failed review escalation | user only | user only | user only, and the reason must be recorded in writing |
| Blocked state unblock requirement | access-missing/human-decision-required/write-safety-required need user input to unblock; runtime-recoverable/contract-insufficient may self-enter a recovery round | same as lite | same as standard, plus: external-system-unsafe can only be unblocked by the user |
| Recoverable blocker auto-round policy | runtime-recoverable auto-opens a read-only investigation round without user confirmation | runtime-recoverable auto-opens a read-only investigation round; contract-insufficient auto-opens a contract-repair round (must not be used to perform business writes) | same as standard, plus: output of both recovery-round types still needs a user spot-check before the next acceptance — strict does not allow multiple consecutive rounds with no human involvement |

## How `$harnessloop-setup` Applies A Profile

1. Read the current `state/control-contract.md` (template, or a previously applied profile).
2. Ask which profile to apply with `AskUserQuestion`: `lite` / `standard` / `strict`.
3. Render the selected profile's full 24-field content from the tables above into the `control-contract-template.md` structure (`Auto-Continue`, `Human Confirmation Required`, `Stop Conditions`, `Blocker Classification` unchanged, `Delegation Boundaries`, `Acceptance Authority`).
4. Show the diff between the current file and the rendered content, and write only after the user confirms.
5. If the user skips this step, leave the file exactly as it is and record a TODO in `state/self-check.md`'s `Action` field; `state/control-contract.md` is one of the three gate-blocking core files, so a skip that leaves it at `template` will short-circuit `$harnessloop-continue`/`$harnessloop-loop` to `needs-setup`.
