---
name: harnessloop-evidence
description: "Use when the user references harnessloop:evidence or asks to add, check, revise, reject, or explain Harnessloop evidence contracts during a loop. This skill updates or validates acceptable evidence entries, freshness rules, validation methods, citation requirements, and continuation effects without continuing business execution."
---

# Harnessloop Evidence

Manage evidence contract changes during a Harnessloop run. This skill controls whether evidence can support acceptance; it does not execute the business task or accept a round by itself.

## Input Contract

Accept an explicit skill invocation such as `$harnessloop-evidence add`, `$harnessloop-evidence check`, `$harnessloop-evidence revise`, or `$harnessloop-evidence reject`, or natural language asking to update accepted evidence. Treat `harnessloop:evidence` as a natural-language alias only; `$harnessloop:evidence` is not a valid skill invocation.

Useful input includes:

- `action`: `add`, `check`, `revise`, `reject`, or `diff`.
- `target`: `.harnessloop/state/evidence-index.md`, a goal `data-contract.md`, a round evidence directory, or a specific evidence file.
- `evidence-id`: stable ID when updating an existing evidence entry.
- `evidence-type`: `static`, `dynamic`, `runtime`, `source`, or `human-confirmation`.
- `path-or-url`: local file path, command output path, CI/build URL, report path, dataset path, source file, or monitoring/probe reference.
- `applies-to`: project setup, goal, threshold, round, scope-lock, review, or decision.
- `freshness-rule`: expected timestamp, max age, refresh cadence, or immutability statement.
- `validation-method`: command, test, checksum, query, review method, access check, or reproducibility condition.
- `required-tool`: required when evidence collection or validation depends on a specified tool call; include tool name, intended operation, required parameters, target resource, expected read/write scope, and fallback policy.
- `external-system`: required when evidence depends on reading from or writing to an external system; include system name, operation, endpoint or resource identifier, required account/role, permission scope, credential reference without secret value, required parameters, and access verification method.
- `channel-parameters`: required when an external channel needs reusable local parameters; include parameter keys, sensitivity, storage method, and whether values should be user-set or locally stored through `$harnessloop-secrets`.
- `citation-requirement`: how future reviews must cite this evidence.
- `sensitivity`: public, internal, confidential, secret-reference-only, or unknown.
- `human-confirmation`: required for any acceptance criteria revision, lower validation bar, or broader evidence scope.

If the request lacks enough information to safely mutate the contract, produce a missing-fields response instead of guessing.

For external-system evidence, missing connection conditions or parameters are a hard stop. Ask the user immediately for the missing facts; do not infer endpoint names, account roles, credential locations, permission scopes, request parameters, write semantics, or fallback access paths. If a channel requires reusable parameters, route to `$harnessloop-secrets` to create or check local parameter keys before connectivity or evidence collection.

When asking for missing external-system facts, use `askuserquestion` when it is available; otherwise ask directly in chat. Ask for only the missing fields needed to proceed.

For required tool calling, missing or invalid tool availability is also a hard stop. If the specified tool is not installed, not exposed, misspelled, ambiguous, or lacks the required capability, ask the user to confirm the correct tool or installation path before attempting an alternative.

Use `$harnessloop-channels` to list declared external systems/tools/channels before connectivity work. Use `$harnessloop-connectivity` to run declared connectivity checks. Do not fold inventory or connectivity probing into evidence mutation unless the user explicitly asks and all required conditions are declared. If connectivity is failed, blocked, skipped, or needs user confirmation, ask the user for the missing access facts before changing evidence health or recommending continuation.

## Processing Contract

1. Read `.harnessloop/state/evidence-index.md`, the active goal's `data-contract.md`, and the active round `scope-lock.md` or `decision.md` when present.
2. Determine whether the requested action changes evidence indexing, acceptance criteria, validation method, or continuation authority.
3. For `add`, register evidence only if the path/source and validation method are explicit.
4. For `check`, verify existence or reachability where possible, freshness status, citation readiness, and whether artifact health differs from claim support.
5. For `revise`, require explicit human confirmation when the revision changes acceptance criteria, weakens validation, broadens evidence scope, or affects continuation.
6. For `reject`, record why evidence is invalid, stale, unsupported, too sensitive, or not applicable.
7. For `diff`, summarize the contract change and its continuation effect.
8. Update self-audit or recommend `$harnessloop-loop` self-audit when the evidence change reveals drift, contradiction, stale data, or validation drift.

When an external system read or write is involved, first verify that the request states the system, operation, required parameters, permission scope, credential reference, and failure handling. If any of these are missing or ambiguous, stop before tool use and ask the user a focused question for the missing condition.

When adding or revising evidence introduces a channel that needs persistent local parameters, do not ask the user to paste values into chat. If channel id, parameter key, sensitivity, storage method, and required-for purpose are explicit, create or check the local parameter placeholder through `$harnessloop-secrets` before updating the evidence contract. Store only the local parameter reference in evidence contracts.

When the evidence action requires a named tool, verify that the tool exists and supports the requested operation before use. If it does not, stop and ask; do not infer aliases, swap providers, rewrite the operation for another tool, or test random commands to discover intent.

If the user asks for a channel/tool inventory, route to `$harnessloop-channels`. If the user asks for connectivity validation, route to `$harnessloop-connectivity`; then update evidence health only after the connectivity report exists.

If a connectivity report blocks evidence because information is missing, preserve the report's `questions for user` and ask those questions directly instead of guessing or silently marking the evidence unknown.

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
- external system:
- required tool:
- access requirements:
- channel parameter references:
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
- Do not store local channel parameter values in evidence contracts; use `.harnessloop/local/channel-params.json` through `$harnessloop-secrets` for ignored local values or provider references.
- Do not infer external-system access details. Missing endpoint, account, credential reference, permission, required parameter, write target, or access verification method must be resolved by asking the user before attempting access.
- Do not infer tool identity or substitute tools. A missing, uninstalled, ambiguous, or wrong named tool must be resolved by asking the user before any tool call.
- If evidence mutation would permit continuation after a blocked, negative, or neutral decision, return `needs-review` and route back to `$harnessloop-loop`.

## Examples

Add runtime evidence:

```text
$harnessloop-evidence add runtime evidence/e2e-login-20260629.md applies-to round 0003 validation "npm run test:e2e" freshness "same day"
```

Check current evidence:

```text
$harnessloop-evidence check .harnessloop/state/evidence-index.md for active round
```

Revise acceptance evidence:

```text
$harnessloop-evidence revise goal data-contract.md to require CI URL plus local test log; human confirmed
```
