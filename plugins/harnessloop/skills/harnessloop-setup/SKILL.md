---
name: harnessloop-setup
description: "Use when the user references harnessloop:setup, runs $harnessloop-setup, or asks to complete, fill in, resume, or check Harnessloop project setup — environment detection, data sources, cost/context policy, or control-contract profile selection — before running $harnessloop-goal, $harnessloop-loop, or $harnessloop-continue. This skill runs the five-step setup wizard backed by check_setup.py and must not execute business work or accept a round."
---

# Harnessloop Setup

Walk the user through completing the Harnessloop project setup skeleton that `$harnessloop-init` creates empty. This skill is a conversation-driven wizard backed by a machine-readable completeness check (`check_setup.py`); it does not execute business work, does not accept a round, and does not replace `$harnessloop-goal`, `$harnessloop-loop`, or `$harnessloop-continue`.

## Input Contract

Accept an explicit skill invocation such as `$harnessloop-setup`, or natural language asking to complete, check, or resume Harnessloop setup. Treat `harnessloop:setup` and `harnessloop setup` as natural-language aliases only; `$harnessloop:setup` is not a valid skill invocation.

Useful input includes:

- `target-project`: defaults to the current working directory.
- Optional request to run a single step only (e.g., "just the control-contract step").
- Optional profile preference for S4 (`lite`, `standard`, or `strict`).

If `.harnessloop/` is missing, stop and suggest `$harnessloop-init`. If imported intake work is pending and has not passed the intake gate, route to `$harnessloop-intake` before running this wizard.

## Completeness Check (`check_setup.py`)

Run this before asking the user anything, every time this skill is invoked:

```bash
python3 -B <plugin-root>/skills/harnessloop-loop/scripts/check_setup.py --project <target-project> --json
```

The `-B` flag (or `PYTHONDONTWRITEBYTECODE=1`) guarantees no `__pycache__` bytecode is written, so this check stays read-only. Exit codes: `0` = `complete: true` (5/5 files fully filled); `1` = `complete: false`; `2` = usage/environment error (bad project path, missing `references/` directory, or missing template file — a packaging problem, not an incomplete setup).

Fields this wizard reads from the JSON output: `files.<path>.state` (`template` | `partial` | `filled` | `missing`) and `.missing_sections`; `complete` / `filled` / `total`; `gate_blocking`; `field_todo_count`; `selfcheck_todo_count`; `next_step`. See "Skip Semantics And The Setup Gate" below for what `gate_blocking`, `field_todo_count`, and `selfcheck_todo_count` mean.

## Processing Contract

1. Run the completeness check above first, always.
2. If `complete: true`, report `Setup completeness: 5/5` and stop. Do not re-ask any question.
3. Otherwise enter review mode. For each of the 5 files, read its `state`:
   - `filled`: skip entirely; report one line, e.g. "state/environment.md already complete, skipped."
   - `partial`: ask only about the `missing_sections` listed for that file.
   - `template` or `missing`: run the full first-run conversation for that step.
4. Walk the steps in fixed order — S1 → S2 → S3 → S4 → S5 — regardless of review mode; only the amount of questioning per step shrinks.
5. Never write a field before showing the user its current value (or, for S4, a diff) and getting confirmation, a correction, or an explicit skip. Display → propose → confirm/modify/skip is the only interaction pattern; never write first and ask after.
6. Tag every value this wizard writes with how it was obtained, appended after the value: `(detected)` for something observed in this session at zero cost (no confirmation needed), `(user-confirmed)` for a proposal the user confirmed or corrected, `(default-accepted)` for a protocol default the user accepted without customizing. This suffix never changes whether `check_setup.py` treats the field as filled — the blank/filled judgment only looks at whether there is content after the colon.
7. For anything the user skips, do not write a fabricated value. Instead append one line to the `Action` field of `state/self-check.md`: `TODO (owner: user): <step> <what> — skipped at setup wizard on <date>`. Leave the underlying field or table untouched (template state).
8. Route any credential, token, API key, or password mentioned during the wizard to `$harnessloop-secrets`; never write a secret value into `setup/data-sources.md`, `setup/cost-context-policy.md`, or any other Harnessloop file. Record only the parameter name and storage method.
9. Prefer `AskUserQuestion` for every confirmation, correction, and skip decision in this wizard. Ask directly in chat only when `AskUserQuestion` is unavailable.
10. Re-run the completeness check at S5 and report `Setup completeness: N/5` plus the setup gate state before ending.

## S1 Environment Detection → `state/environment.md`

Fill the 21 fields of `environment-self-check-template.md` (Detection ×4, Delegation ×6, Model And Effort ×7, Result ×4).

- Detect for free, mark `(detected)`, and never ask the user to confirm: `Detected environment`, `Detected from`, `Available tools`, `Unavailable tools` (the current session's tool list), `Expected mechanism`/`Observed mechanism` (whether a subagent/delegation-equivalent mechanism exists), `Observed model` (the session's own model identity), `Last checked` (current timestamp).
- Verify, do not assume, `Can create independent task`, `Can constrain read/write scope`, `Can require output path`, and `Can verify evidence citations`: if this session has already run a real delegation, cite that delegation's actual output as evidence, marked `(detected)`. If there is no such evidence, write `unknown` — never infer `pass` just because the protocol describes delegation as generally available. State the limitation explicitly in `Residual risk`: a probe only proves what one delegation did, not what every delegation will do.
- Ask the user (provenance `user-confirmed` or `default-accepted`) for `Expected model`/`Expected effort/reasoning` (pull the value from `setup/cost-context-policy.md` if S3 already ran; otherwise ask now and let S3 stay consistent with it) and `Mismatch action` (what should happen when a later observed model/effort disagrees with expected).
- Write `Verification method` as the method actually used (e.g., "session self-report + one delegation probe"), never a placeholder like "not run" unless there truly is no delegation evidence to cite.
- Only `Expected model/effort` and `Mismatch action` are skippable. Every other field is zero-cost detection: if it genuinely cannot be detected, write `unknown` — that is not a skip, and does not get a TODO line.
- Because `state/environment.md` is one of the three gate-blocking files, a skip that leaves this file fully at `template` will short-circuit `$harnessloop-continue`/`$harnessloop-loop` to `needs-setup`. Say so before letting the user skip both remaining fields.

## S2 Data Sources → `setup/data-sources.md`

Ask about each of the 4 categories in `data-sources-template.md` separately. Never ask about `Local Channel Parameters` — that table is owned by `$harnessloop-secrets`. Never ask about `Secret Handling` — it is fixed protocol text, not user input.

1. **Static Sources**: source, access method, freshness requirement, drift risk, validation method, credential requirement.
2. **Dynamic Or Generated Sources**: same shape, with generator/tool in place of access method.
3. **Runtime Validation Systems**: access method, validation method, pass condition, failure handling, credential requirement, local parameter reference.
4. **External Tools And Platforms**: purpose, read/write scope, account role, verification method, failure handling, local parameter keys.

Any category may be answered "none." When it is, write this exact sentinel line under that section (case-sensitive; it must contain the literal phrase `(confirmed via setup wizard)` — `check_setup.py`'s sentinel pattern anchors on that phrase, not on general "no ... declared" wording):

```text
_No <category> declared for this project (confirmed via setup wizard)._
```

Use the category's template heading in lowercase for `<category>` (e.g., `dynamic or generated sources`). A vaguer answer such as "not sure yet" or "no, need to think about it" must **not** be written as this sentinel — it is not yet a confirmed "none." Leave the section untouched and record a TODO instead.

If a source needs a credential, do not record its value here. Hand off to `$harnessloop-secrets add channel <id> key <NAME> --sensitivity secret --storage <...>`; this file's "Credential requirement"/"Local parameter" columns record only the parameter name and whether one is required.

Skipping an entire category (asking nothing, writing nothing) is allowed and only produces a TODO. `setup/data-sources.md` is not one of the three gate-blocking files (see below), so this kind of skip never short-circuits `$harnessloop-continue`/`$harnessloop-loop` — it only shows up as a warning and a `selfcheck_todo_count` increment (the skip is recorded as a `TODO (owner: user):` line in `state/self-check.md`'s `Action` field, not as a literal-`TODO` value written into the leaf field itself).

## S3 Cost And Context Policy → `setup/cost-context-policy.md`

Display, don't interview. Render the protocol's own written-down defaults (`harnessloop-loop/SKILL.md`'s Core Contract and Role And Model Rules sections) as the 29 field values of `cost-context-policy-template.md`, and ask the user to accept as-is or name specific changes.

Write each field at its exact heading-path location, not by label alone. Several labels repeat across the template: `Core decisions` appears under Main Session, Codex, and Claude Code (3 independent slots); `Low-context execution` and `Adversarial review` each appear under Delegation Rules, Codex, and Claude Code (3 slots each); `Independent investigation` appears under Codex and Claude Code (2 slots). `Main Session > Responsibilities > Core decisions`, `Model Policy > Codex > Core decisions`, and `Model Policy > Claude Code > Core decisions` take different source content (main-session orchestration duties vs. each model's decision-making boundary) — never write one sentence into all three and call it done.

Do not touch `Execution Delegation Matrix`: its 8 `Decision` rows are already protocol-level prefilled content (from the loop skill's own delegation matrix), not a question for this step.

Whole-section skip only: if the user defers the whole step, leave the file at template and record a TODO; there is no partial-skip for this step (all 29 fields are shown and confirmed/edited together, in one pass, because the confirm-everything-at-once interaction is already low-friction). Because this file is one of the three gate-blocking core files, skipping it while it remains fully template-state will short-circuit `$harnessloop-continue`/`$harnessloop-loop` to `needs-setup` — say so before letting the user skip.

## S4 Control Contract Profile → `state/control-contract.md`

1. Show the three-profile summary (full field-by-field content in `references/control-contract-profiles.md`): `lite` (personal/low-risk projects; most positive or runtime-recoverable investigation auto-continues), `standard` (default; positive feedback with fully-valid evidence auto-continues), `strict` (external systems or sensitive data; human confirmation is required before continuing even when every automatic condition is met).
2. Ask with `AskUserQuestion`: lite / standard / strict.
3. Build a diff of the current file (template, or a previously chosen profile) against the selected profile's full 24-field content, show the diff to the user, and only then write it. Never overwrite silently.
4. This is the one step with no partial-fill state: all 24 fields are written together, or the file stays as it is. Treat re-selecting a profile on an already-filled file the same way — still show the diff before writing.
5. Skip = choose no profile; the file stays as-is and gets a TODO. Because `state/control-contract.md` is one of the three gate-blocking files, this is the single most likely real-world way a user triggers the short circuit. Tell them explicitly: "leaving this unpicked means `$harnessloop-continue`/`$harnessloop-loop` will keep returning `needs-setup` until you come back and choose a profile" — not just "recorded as a TODO."

## S5 Self-Check Summary → `state/self-check.md`

1. Re-run the completeness check (`check_setup.py --project <target-project> --json`) after S1-S4 have written whatever they wrote.
2. Fill the 12 fields of `self-check-template.md`:
   - `Setup files present`: pass/partial plus this run's filled-file count.
   - `Environment policy recorded` / `Control contract recorded`: reflect S1's/S4's output state.
   - `Runtime validation described` / `Data/tool access described`: reflect S2's output state.
   - `Evidence index recorded` / `Self-audit present` / `Intake gate required`: outside this wizard's five steps. Read the current state where determinable; otherwise write "not applicable at setup stage; maintained by loop's first round." Never fabricate `pass`.
   - `Local channel parameter store protected`: reflect whether `.harnessloop/local/.gitignore` exists and covers the local parameter store.
   - `Delegation model verified`: reflect S1's delegation-probe fields.
   - `Action`: "setup complete, no TODO" when nothing was skipped; otherwise one line per skipped item, naming the owner, the exact sub-item, the timestamp, and whether it is gate-blocking.
   - `Last checked`: current timestamp.
3. Report to the user:
   - `Setup completeness: N/5` (`N` = `filled` from `check_setup.py`).
   - `setup gate: complete | warning (TODO count: field=F, self-check=S) | blocking` — matching `check_setup.py`'s own human-readable `TODO count: field=<N>, self-check=<M>` line.
   - Next step: if `N == 5`, suggest `$harnessloop-goal propose <one-line goal>` or `$harnessloop-loop`. If `N < 5` and `gate_blocking == false`, list the remaining gaps and note that they do not block continuation — a re-run of `$harnessloop-setup` will re-enter review mode and ask only about what remains. If `gate_blocking == true`, name the still-`template`/`missing` core file and state that `$harnessloop-continue`/`$harnessloop-loop` will return `needs-setup` until it is completed.

## Skip Semantics And The Setup Gate

Skipping is always legal, and a skip is always recorded — never as a fabricated value, always as a `TODO (owner: user)` line appended to `state/self-check.md`'s `Action` field, with the underlying field or table left untouched. What differs is whether a skip blocks `$harnessloop-continue`/`$harnessloop-loop`, and that is decided entirely by `gate_blocking`, not by "any incompleteness blocks" or "nothing ever blocks."

`check_setup.py --json` reports four independent signals — do not treat any one of them as a substitute for another, and never add `field_todo_count` and `selfcheck_todo_count` together as if they were one combined total. This two-counter split is a documented, round-0003-sanctioned deviation from design-v2 section 4.4's original single-merged-counter proposal (see the `check_setup.py` module docstring for the full rationale), adopted because the original merge would have needed an undefined de-duplication predicate between per-field literal placeholders and `self-check.md` Action-field entries. The two counters can legitimately overlap for the same underlying text — for example, if `state/self-check.md`'s own `Action` field is written as a literal `TODO (owner: user)` value, that one field is counted once in `field_todo_count` (as one of self-check.md's 12 leaf fields) and its text is also scanned for `selfcheck_todo_count`. That overlap is expected, not a bug, and is not something to subtract or reconcile:

- **`complete` / `filled` / `total`**: strict "all 5 files 100% filled" arithmetic. This is what the wizard's own `N/5` report uses. A field written as the literal `TODO (owner: user)` counts as filled here — it is a deliberate, protocol-recognized placeholder, not an untouched blank.
- **`field_todo_count`**: how many leaf fields, across the 5 files, hold a value that is the literal `TODO (owner: user)` marker (optionally followed by free text). This wizard's own skip flow does not normally create these — a skip in this wizard leaves the field blank (template) and records the TODO in `self-check.md`'s `Action` field instead (see Processing Contract step 7) — but the counter still exists to catch a literal per-field `TODO (owner: user)` value however it got there (manual edits, other tooling), so `complete: true` never silently hides one.
- **`selfcheck_todo_count`**: how many `TODO (owner: user):`-formatted entries exist inside `state/self-check.md`'s `Action` field. This is the counter this wizard's own skip flow populates. `complete: true` with `selfcheck_todo_count > 0` is a normal, expected state — "5/5 filled, but N steps were actually skipped and only recorded as TODOs" — and must still be surfaced to the user, never hidden.
- **`gate_blocking`**: `true` if and only if `state/environment.md`, `state/control-contract.md`, or `setup/cost-context-policy.md` is still at `state: template` or `state: missing`. Neither `field_todo_count` nor `selfcheck_todo_count` participates in `gate_blocking` or `complete` — both are presentation-only counters. These three files, and only these three, gate:
  - `state/environment.md` and `state/control-contract.md` are read directly by `$harnessloop-continue`'s environment gate and control gate.
  - `setup/cost-context-policy.md` is not read by `$harnessloop-continue` itself, but is read directly by `$harnessloop-delegation` as the source of expected model/effort — a one-hop dependency — and S3 is also the cheapest of the three to establish (a display-and-confirm step, not an interview), which keeps the bar for blocking proportionate.
  - `setup/data-sources.md` is deliberately excluded: `$harnessloop-continue`'s evidence gate reads `state/evidence-index.md`, never `data-sources.md`. A fully-skipped data-sources file cannot make any continuation gate unevaluable, and excluding it is what keeps S2's "skip a whole category" a true, non-blocking skip rather than a hidden trap.
  - `state/self-check.md` is deliberately excluded too — not because no other skill ever reads it, but because it is this wizard's own S5 output record, and the TODO claim ledger for every other step's skip lives in its own `Action` field. Gating on `self-check.md` itself being non-template would make the claim-recording mechanism depend on its own prior existence — a self-referential deadlock, not a real safety requirement.

`complete` and `gate_blocking` are independent signals: `complete=false, gate_blocking=false` is the normal, common case (for example, only `data-sources.md` has one unanswered category). Never warn about a `$harnessloop-continue`/`$harnessloop-loop` short-circuit just because `complete=false` — only `gate_blocking=true` does that. Conversely, `gate_blocking=true` always deserves a clear, upfront warning, because it means the user's very next `$harnessloop-continue`/`$harnessloop-loop` call will stop before doing any work.

## Secrets Boundary

This wizard never accepts or writes a secret value. Any credential, token, API key, or password mentioned by the user during S1-S4 must be handed to `$harnessloop-secrets add channel <id> key <NAME> --sensitivity secret --storage <...>`. This wizard's own files record only parameter names and storage method, never values.

## Output Contract

```text
Harnessloop setup:
- project:
- mode: first-run | review | already-complete
- steps run: (subset of S1-S5 actually executed this call)
- files changed:
- setup completeness: N/5
- setup gate: complete | warning | blocking
- TODO count: field=<field_todo_count>, self-check=<selfcheck_todo_count>
- gate-blocking file: (the template/missing core file, if any)
- next action:
```

## Safety Rules

- Never write a field or table before showing its current value (or, for S4, a diff) and getting an explicit confirmation, correction, or skip.
- Never fabricate a `pass`, a detected value, or a data source that was not actually observed by this session or confirmed by the user.
- Never write a secret value into any Harnessloop file; route it to `$harnessloop-secrets`.
- Never treat `complete: false` alone as a reason to warn about a `$harnessloop-continue`/`$harnessloop-loop` short-circuit — only `gate_blocking: true` does that.
- Never claim a delegation probe (`Can create independent task`, `Can constrain read/write scope`, `Can require output path`, `Can verify evidence citations`) passed without a real, citable delegation from this session; write `unknown` otherwise.
- Do not execute business work, propose a goal, or accept a round from this skill; end by pointing to `$harnessloop-goal propose` or `$harnessloop-loop`.
- Run `check_setup.py` with `-B` (or `PYTHONDONTWRITEBYTECODE=1`) so every idempotency/review-mode check stays read-only.

## Examples

Fresh project, nothing filled yet:

```text
$harnessloop-setup
```

```text
Harnessloop setup:
- project: .
- mode: first-run
- steps run: (none yet — waiting on S1 Q1/Q2)
- files changed: (none yet)
- setup completeness: 0/5
- setup gate: blocking
- TODO count: field=0, self-check=0
- gate-blocking file: state/environment.md, state/control-contract.md, setup/cost-context-policy.md (all template)
- next action: answer S1's two questions to continue the wizard
```

Review mode, two core files already filled, control contract still template:

```text
$harnessloop-setup
```

```text
Harnessloop setup:
- project: .
- mode: review
- steps run: (none this call — waiting on user to pick a profile)
- files changed: (none)
- setup completeness: 2/5
- setup gate: blocking
- TODO count: field=0, self-check=0
- gate-blocking file: state/control-contract.md (still template — no profile chosen yet)
- next action: pick lite/standard/strict to unblock $harnessloop-continue/$harnessloop-loop
```

Review mode after the profile is chosen and only a non-blocking gap remains:

```text
Harnessloop setup:
- project: .
- mode: review
- steps run: S4
- files changed: state/control-contract.md
- setup completeness: 4/5
- setup gate: warning (TODO count: field=0, self-check=1)
- TODO count: field=0, self-check=1
- gate-blocking file: (none — environment.md, control-contract.md, and cost-context-policy.md are all filled)
- next action: $harnessloop-goal propose <goal>, or $harnessloop-loop; the remaining data-sources.md gap does not block either
```
