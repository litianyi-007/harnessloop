---
name: harnessloop-evidence
description: "Use when the user references harnessloop:evidence or asks to add, check, revise, reject, or explain Harnessloop evidence contracts during a loop. This skill updates or validates acceptable evidence entries, freshness rules, validation methods, citation requirements, and continuation effects without continuing business execution."
---

# Harnessloop Evidence

Manage evidence contract changes during a Harnessloop run. This skill controls whether evidence can support acceptance; it does not execute the business task or accept a round by itself.

## Input Contract

Accept a request such as `harnessloop:evidence add`, `harnessloop:evidence check`, `harnessloop:evidence revise`, `harnessloop:evidence reject`, or natural language asking to update accepted evidence.

Useful input includes:

- `action`: `add`, `check`, `revise`, `reject`, or `diff`.
- `target`: `.harnessloop/state/evidence-index.md`, a goal `data-contract.md`, a round evidence directory, or a specific evidence file.
- `evidence-id`: stable ID when updating an existing evidence entry.
- `evidence-type`: `static`, `dynamic`, `runtime`, `source`, or `human-confirmation`.
- `path-or-url`: local file path, command output path, CI/build URL, report path, dataset path, source file, or monitoring/probe reference.
- `applies-to`: project setup, goal, threshold, round, scope-lock, review, or decision.
- `freshness-rule`: expected timestamp, max age, refresh cadence, or immutability statement.
- `validation-method`: command, test, checksum, query, review method, access check, or reproducibility condition.
- `citation-requirement`: how future reviews must cite this evidence.
- `sensitivity`: public, internal, confidential, secret-reference-only, or unknown.
- `human-confirmation`: required for any acceptance criteria revision, lower validation bar, or broader evidence scope.

If the request lacks enough information to safely mutate the contract, produce a missing-fields response instead of guessing.

## Processing Contract

1. Read `.harnessloop/state/evidence-index.md`, the active goal's `data-contract.md`, and the active round `scope-lock.md` or `decision.md` when present.
2. Determine whether the requested action changes evidence indexing, acceptance criteria, validation method, or continuation authority.
3. For `add`, register evidence only if the path/source and validation method are explicit.
4. For `check`, verify existence or reachability where possible, freshness status, citation readiness, and whether artifact health differs from claim support.
5. For `revise`, require explicit human confirmation when the revision changes acceptance criteria, weakens validation, broadens evidence scope, or affects continuation.
6. For `reject`, record why evidence is invalid, stale, unsupported, too sensitive, or not applicable.
7. For `diff`, summarize the contract change and its continuation effect.
8. Update self-audit or recommend `$harnessloop-loop` self-audit when the evidence change reveals drift, contradiction, stale data, or validation drift.

## Output Contract

Return and, when safe, write an evidence contract action record:

```text
Evidence contract action:
- action: add | check | revise | reject | diff | missing-fields
- target:
- evidence id:
- evidence type:
- paths or URLs:
- applies to:
- freshness rule:
- observed freshness:
- validation method:
- citation requirement:
- artifact health: valid | invalid | stale | unreachable | unknown
- claim support: supports | refutes | inconclusive | not-evaluated
- acceptance effect: allow | block | needs-review | no-change
- human confirmation: required | provided | not-required
- files changed:
- next allowed action:
```

Prefer updating `.harnessloop/state/evidence-index.md` for global evidence inventory and the active goal's `data-contract.md` for acceptance criteria. Do not copy raw sensitive data into Harnessloop files; store references, summaries, and validation methods.

## Safety Rules

- Do not mark a round accepted. Acceptance remains a `$harnessloop-loop` review/decision action.
- Do not weaken evidence requirements without human confirmation.
- Do not treat valid artifact health as claim support; failed tests may be valid evidence that refutes acceptance.
- Do not store secrets, tokens, cookies, private keys, raw customer data, or unnecessary proprietary excerpts.
- If evidence mutation would permit continuation after a blocked, negative, or neutral decision, return `needs-review` and route back to `$harnessloop-loop`.

## Examples

Add runtime evidence:

```text
harnessloop:evidence add runtime evidence/e2e-login-20260629.md applies-to round 0003 validation "npm run test:e2e" freshness "same day"
```

Check current evidence:

```text
harnessloop:evidence check .harnessloop/state/evidence-index.md for active round
```

Revise acceptance evidence:

```text
harnessloop:evidence revise goal data-contract.md to require CI URL plus local test log; human confirmed
```
