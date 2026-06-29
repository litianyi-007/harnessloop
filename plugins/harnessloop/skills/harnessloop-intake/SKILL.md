---
name: harnessloop-intake
description: "Use when the user references harnessloop:intake, wants Harnessloop to take over an existing agent session, provides a transfer packet, asks to run an intake gate, or needs a gap review before importing previous work into a Harnessloop goal. This skill reviews imported session context and blocks business execution until the packet is evidence-backed."
---

# Harnessloop Intake

Run the takeover intake path for work that began outside Harnessloop. This skill accepts or rejects an imported session handoff; it does not continue the business task.

## Input Contract

Accept any of these inputs:

- A target project path and task slug for creating an intake directory.
- A path to `.harnessloop/intake/YYYYMMDD-HHMM-<task-slug>/transfer-packet.md`.
- A pasted `Harnessloop Transfer Packet`.
- A request such as `harnessloop:intake --project C:\repo --intake task-slug`.

The transfer packet should contain task identity, goal contract, progress state, change state, documentation inventory, process artifacts, evidence state, external tool and access contract, credential requirements without secret values, decision log, risks/blockers, next handoff recommendation, and human questions.

## Processing Contract

1. Ensure `.harnessloop/` exists. If not, ask to run `harnessloop:init` or run the initializer with an intake slug when the user requested setup.
2. Place or locate `transfer-packet.md` under `.harnessloop/intake/YYYYMMDD-HHMM-<task-slug>/`.
3. Review the packet against `harnessloop-loop/references/intake-gate-template.md`.
4. Check that claims are evidence-backed with paths, commands, test output, logs, URLs, or explicit unsupported-hypothesis labels.
5. Verify secrets are not present; credential requirements must name only storage, scope, use, verification method, and status.
6. If information is missing, write `gap-review.md` using the gap template and ask only for missing facts.
7. If the packet passes, write `intake-gate.md` and recommend an `intake-review` round before any business execution.

## Output Contract

Produce one of these outcomes:

- `blocked`: missing `.harnessloop/`, missing transfer packet, secret exposure, or unsafe continuation.
- `gap-review`: packet is incomplete; write the missing-facts review and request targeted answers.
- `accepted-for-intake-review`: packet is complete enough; write the gate result and state the first allowed next action.

Always report the intake directory, files written or reviewed, whether business execution is blocked, and the next required prompt: `Use $harnessloop-loop to run the intake-review round.`

## Safety Rules

Do not create a formal goal directly from an imported packet. Do not continue code, data, research, or operational work until the intake gate passes and an intake-review round maps accepted evidence into `.harnessloop/state/evidence-index.md`.
