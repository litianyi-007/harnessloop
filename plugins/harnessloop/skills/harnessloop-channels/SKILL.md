---
name: harnessloop-channels
description: "Use when the user references harnessloop:channels or asks to list all external systems, access channels, tools, MCP servers, CLIs, APIs, CI systems, databases, broker services, or other integrations declared in Harnessloop evidence contracts, data sources, transfer packets, goals, rounds, or handoffs. This skill is inventory-only and must not probe connectivity."
---

# Harnessloop Channels

List all declared external systems, channels, and tools that Harnessloop may rely on. This skill produces an inventory; it does not test connectivity, infer missing tools, or call external systems.

## Input Contract

Accept an explicit skill invocation such as `$harnessloop-channels`, or natural language asking to list external systems/tools/channels. Treat `harnessloop:channels` as a natural-language alias only; `$harnessloop:channels` is not a valid skill invocation.

Useful input includes:

- `target-project`: defaults to the current working directory.
- Optional scope: setup, evidence, active goal, active round, intake, handoffs, or all.
- Optional output preference: table, grouped by system, grouped by tool, or missing-fields list.

If `.harnessloop/` is missing, report `not-initialized` and suggest `$harnessloop-init`.

## Processing Contract

1. Read declared sources from `.harnessloop/setup/data-sources.md`, `.harnessloop/state/evidence-index.md`, active goal `data-contract.md`, active round evidence/review files, intake transfer packets, and open handoffs when present.
2. Extract only declared external systems, tools, channels, accounts, credential references, permissions, required parameters, verification methods, failure handling, and sensitivity labels.
3. Mark missing or ambiguous fields explicitly instead of inferring them.
4. Classify each channel as `declared-complete`, `declared-incomplete`, `unused`, `unknown-owner`, `missing-verification`, or `needs-user-confirmation`.
5. Do not call tools, probe endpoints, check credentials, run CLIs, or access external systems.
6. When missing fields would block `$harnessloop-connectivity`, include the focused questions the user must answer before any connectivity self-check can run.

## Output Contract

Return a channel inventory:

```text
Harnessloop channel inventory:
- project:
- scope:
- channel count:
- channels:
  - id:
  - system:
  - channel/tool type:
  - purpose:
  - operations: read | write | read-write | unknown
  - target resources:
  - required tool:
  - account/role:
  - permission scope:
  - credential reference:
  - required parameters:
  - verification method:
  - failure handling:
  - sensitivity:
  - declaration status:
  - source paths:
- missing fields:
- questions for user:
- recommended next action:
```

When the user asks to test connectivity, route to `$harnessloop-connectivity`.

## Safety Rules

- Inventory is read-only by default; do not mutate contracts unless the user explicitly asks to repair documentation.
- Do not infer tool identity, endpoint, credential location, permission scope, or required parameters.
- Do not test connectivity from this skill.
- If inventory is incomplete, ask for the exact missing fields before recommending a connectivity check.
- Do not include secret values; report only credential names or references.
