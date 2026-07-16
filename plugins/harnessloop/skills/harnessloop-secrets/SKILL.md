---
name: harnessloop-secrets
description: "Use when the user references harnessloop:secrets or asks to create, check, update, resolve, or audit local channel parameters, secret references, credential keys, API tokens, environment-variable names, local-only values, or redaction rules needed by Harnessloop evidence, channels, connectivity, or external-system access."
---

# Harnessloop Secrets

Manage local-only channel parameters and secret references for Harnessloop. This skill records the keys a channel needs, where values should be resolved from, and whether each value is present, without copying secret values into chat, evidence, or committed files.

## Local Store

Use this project-local path for non-committed channel parameters:

```text
.harnessloop/local/channel-params.json
```

Initialize these companion files when missing:

```text
.harnessloop/local/.gitignore
.harnessloop/local/channel-params.example.json
```

`.harnessloop/local/.gitignore` must ignore `channel-params.json`, `*.secret.json`, `*.token`, and other local secret material. The example file may contain keys, provider names, and placeholder values only.

## Input Contract

Accept explicit invocations such as:

- `$harnessloop-secrets init`
- `$harnessloop-secrets add channel <channel-id> key <name>`
- `$harnessloop-secrets set channel <channel-id> key <name>`
- `$harnessloop-secrets check channel <channel-id>`
- `$harnessloop-secrets resolve channel <channel-id>`
- `$harnessloop-secrets audit`

Useful input includes:

- `channel-id`: stable external channel/tool id.
- `parameter-key`: endpoint, username, token, API key, account role, project id, job name, region, or other required parameter.
- `sensitivity`: public, internal, credential-reference, secret, or unknown.
- `storage`: local-file, env, os-keychain, vault, onepassword, manual, or unknown.
- `env-name` or `reference-name`: e.g. `JENKINS_TOKEN`; never include the value unless the user explicitly asks to store it locally.
- `required-for`: inventory, connectivity, evidence collection, write check, review, or continuation.
- `set-value`: optional; only write to local ignored store after explicit user instruction and never echo the value.

If the user provides a secret value in chat, do not repeat it. Ask whether to store it in the local ignored file, convert it to an environment-variable reference, or discard it.

## Deterministic Manager

Prefer the bundled script for local store mutations and checks:

```text
python <skill-dir>/scripts/channel_params.py --project <project> init
python <skill-dir>/scripts/channel_params.py --project <project> add --channel <channel-id> --key <KEY> --sensitivity secret --storage env --env <ENV_NAME> --required-for connectivity
python <skill-dir>/scripts/channel_params.py --project <project> set --channel <channel-id> --key <KEY> --value-env <ENV_NAME>
python <skill-dir>/scripts/channel_params.py --project <project> check --channel <channel-id>
python <skill-dir>/scripts/channel_params.py --project <project> resolve --channel <channel-id> --key <KEY>
python <skill-dir>/scripts/channel_params.py --project <project> audit
```

The script prints redacted JSON with presence, source, missing fields, and questions. It must not print secret values.

## Processing Contract

1. Read declared channels from `.harnessloop/setup/data-sources.md`, `.harnessloop/state/evidence-index.md`, active goal data contract, active round files, and open handoffs.
2. Ensure `.harnessloop/local/.gitignore` exists and protects local parameter files.
3. Ensure `channel-params.example.json` documents the expected shape without real values.
4. Create or update `.harnessloop/local/channel-params.json` only when the user asks to initialize, add, or set local parameters, or when an evidence/channel contract explicitly declares reusable parameter keys.
5. Store secret values only in `.harnessloop/local/channel-params.json` or an approved external secret provider reference. Do not store secret values in setup, evidence, state, handoff, review, or decision files.
6. When resolving, return presence and source only; never print secret values.
7. When a required parameter is missing, ask the user for the exact missing key and acceptable storage method before connectivity or evidence collection continues. Use `askuserquestion` when available; otherwise ask directly in chat.
8. Route access verification to `$harnessloop-connectivity` after required parameters are present.

When evidence addition or revision introduces a reusable external-channel parameter and the channel id, parameter key, sensitivity, storage method, and required-for purpose are explicit, create a placeholder key immediately. When any of those fields are missing, stop and ask for the missing fields instead of inventing names or storage.

## Local JSON Shape

```json
{
  "version": 1,
  "channels": {
    "channel-id": {
      "parameters": {
        "KEY_NAME": {
          "sensitivity": "secret",
          "storage": "env",
          "env": "KEY_NAME",
          "value": null,
          "required_for": ["connectivity"],
          "status": "missing",
          "notes": ""
        }
      }
    }
  }
}
```

For `storage: local-file`, `value` may be set only in the ignored local file and must never be copied into any other artifact.

## Output Contract

```text
Harnessloop secrets:
- project:
- action: init | add | set | check | resolve | audit | blocked
- channel:
- local store:
- keys:
  - name:
  - sensitivity:
  - storage:
  - reference:
  - required for:
  - status: present | missing | unknown | invalid
- files changed:
- missing fields:
- questions for user:
- next action:
```

## Safety Rules

- Never print, summarize, or copy secret values.
- Never commit `.harnessloop/local/channel-params.json`.
- Never infer a key value, credential location, endpoint, account role, or permission scope.
- Never use a secret for a different channel or operation without user confirmation.
- For write-capable channels, require explicit write-safety details before routing to connectivity.
