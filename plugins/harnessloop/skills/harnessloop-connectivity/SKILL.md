---
name: harnessloop-connectivity
description: "Use when the user references harnessloop:connectivity or asks to check external system, access channel, tool, MCP server, CLI, API, CI, database, broker, or integration connectivity declared in Harnessloop evidence contracts or channel inventory. This skill only runs declared verification methods and must ask the user first when required tools, parameters, credentials, or permissions are missing."
---

# Harnessloop Connectivity

Check declared external system/tool connectivity for Harnessloop evidence and validation. This skill tests access only when the channel contract is explicit enough; it must not infer tools, endpoints, credentials, or parameters.

## Input Contract

Accept an explicit skill invocation such as `$harnessloop-connectivity`, or natural language asking to check a named system/tool/channel. Treat `harnessloop:connectivity` as a natural-language alias only; `$harnessloop:connectivity` is not a valid skill invocation.

Useful input includes:

- `target-project`: defaults to the current working directory.
- `channel-id` or system/tool name.
- `operation`: read, write, read-write, auth-check, metadata-check, dry-run, or unknown.
- `verification-method`: exact command/tool/API/MCP call or documented manual check.
- `required-tool`: exact tool name and expected capability.
- `credential-reference`: name/location only, never a secret value.
- `required-parameters`: endpoint/resource, account/role, permission scope, target resource, environment, and failure handling.
- `local-parameter-reference`: `.harnessloop/local/channel-params.json` key or external provider reference managed by `$harnessloop-secrets`.
- `write-safety`: dry-run, test resource, rollback path, or explicit human confirmation for write checks.

If the channel inventory is missing, run or request `$harnessloop-channels` first. If any required field is missing, ask the user a focused question before any tool call.

If a self-check cannot pass because a required tool, endpoint/resource, credential reference, permission, account role, required parameter, write-safety condition, or failure-handling rule is missing or invalid, actively ask the user for the exact missing information. Use `askuserquestion` when available; otherwise ask directly in chat. Do not only report the failed check.

If the missing condition is a reusable channel parameter or secret reference, route to `$harnessloop-secrets` before attempting connectivity. Do not ask the user to paste secret values into chat.

## Processing Contract

1. Read channel declarations from `.harnessloop/setup/data-sources.md`, `.harnessloop/state/evidence-index.md`, active goal `data-contract.md`, active round evidence/review files, intake packets, and open handoffs.
2. Build a check plan from declared verification methods only.
3. Before tool use, verify the named tool exists and the request includes all required parameters, credential references or local parameter references, permission scope, operation, target resource, and failure handling.
4. If a named tool is unavailable, uninstalled, ambiguous, or possibly wrong, stop and ask the user to confirm the correct tool or installation path.
5. For write checks, require explicit human confirmation plus dry-run/test-resource/rollback details.
6. Run only the declared checks that are complete and safe.
7. If any check result is `fail`, `blocked`, `skipped`, or `needs-user-confirmation`, include focused user questions for the missing or invalid conditions before recommending continuation.
8. Record results as evidence artifacts or recommend `$harnessloop-evidence` updates when the check changes evidence health.

When a connectivity or runtime preflight blocks the original action because external state is unsafe, classify whether the next step is read-only. If safe read-only investigation can proceed, report `blocker type: runtime-recoverable` and `continuation effect: recovery-round`; if cleanup, trigger, rollback, or mutation is required, report `write-safety-required` or `human-decision-required` and ask for confirmation.

## Output Contract

Return a connectivity report:

```text
Harnessloop connectivity:
- project:
- scope:
- checked channels:
  - id:
  - system:
  - required tool:
  - operation:
  - verification method:
  - result: pass | fail | skipped | blocked | needs-user-confirmation
  - artifact path:
  - error summary:
  - missing fields:
  - questions for user:
  - permission status:
  - credential reference status:
  - local parameter status:
  - write safety:
  - blocker type:
  - recovery eligible:
  - next action:
- overall result: pass | fail | partial | blocked
- evidence update needed:
- continuation effect: allow | block | recovery-round | needs-review | no-change
```

## Safety Rules

- Do not infer endpoints, tools, credential locations, permissions, parameters, account roles, or fallback paths.
- Do not substitute another tool or provider without user confirmation.
- Do not perform write connectivity checks without explicit human confirmation and rollback/dry-run/test-resource details.
- Do not store secrets or raw sensitive outputs.
- Do not print local parameter values; report only presence, source, and status.
- If connectivity changes evidence acceptance, route to `$harnessloop-evidence`.
- If a blocked connectivity check prevents continuation, ask the user for the exact missing condition first, then route to `$harnessloop-continue` after the user resolves it.

## Examples

List before checking:

```text
$harnessloop-channels
```

Check all complete declarations:

```text
$harnessloop-connectivity all complete declarations
```
