---
name: harnessloop-init
description: "Use when the user explicitly asks to initialize Harnessloop, references harnessloop:init, says to set up the Harnessloop framework, or wants to create project-local .harnessloop files before running the full Harnessloop loop. This skill performs only initialization and handoff into the main harnessloop-loop protocol."
---

# Harnessloop Init

Initialize Harnessloop in the target project and prepare the project for the full `$harnessloop-loop` protocol. Treat `harnessloop:init` as an invocation phrase for this skill; skill names cannot contain `:`, so the installed skill name is `harnessloop-init`.

## Input Contract

Accept a target project path, optional intake slug, and optional mode:

- `target-project`: defaults to the current working directory.
- `intake-slug`: optional; use when initialization is for taking over an existing agent session.
- `dry-run`: optional; preview files without writing.
- `force`: optional; overwrite generated files only after explicit user confirmation.

Accept an explicit skill invocation such as `$harnessloop-init this repo` or `$harnessloop-init --project C:\repo --intake task-slug`. Treat `harnessloop:init` as a natural-language alias only; `$harnessloop:init` is not a valid skill invocation.

## Processing Contract

Resolve the target project, check whether `.harnessloop/` already exists, then prefer the bundled initializer from `harnessloop-loop/scripts/init_project.py`. If the initializer is unavailable, create only the minimal protocol skeleton. Do not infer project facts, credentials, goals, data sources, or validation results.

## Output Contract

Return the target project path, whether initialization was created, skipped, previewed, or blocked, and the files/directories created or expected. If intake was requested, return the transfer packet path and tell the user to run `$harnessloop-intake` before business execution.

## Initialization Decision

First identify the target project:

- Use the current working directory unless the user names another path.
- If `AGENTS.md`, `CLAUDE.md`, or repository docs already mention a project-specific Harnessloop policy, read them before initializing.
- If `.harnessloop/` already exists, do not overwrite it. Report that Harnessloop is already initialized and suggest `$harnessloop-loop` for status or continuation.

## Preferred Setup

When the bundled initializer is available, run it instead of creating files by hand:

```bash
python <plugin-root>/skills/harnessloop-loop/scripts/init_project.py --project <target-project>
```

For a takeover from an existing agent session, include an intake slug:

```bash
python <plugin-root>/skills/harnessloop-loop/scripts/init_project.py --project <target-project> --intake <task-slug>
```

Use `--dry-run` when the user asks to preview the initialization. Use `--force` only after explicit user confirmation.

## Manual Fallback

If the initializer cannot be found or cannot run, create only the protocol skeleton that the main Harnessloop skill expects:

```text
.harnessloop/
  setup/
    data-sources.md
    cost-context-policy.md
  local/
    .gitignore
    channel-params.example.json
  state/
    current.md
    environment.md
    control-contract.md
    evidence-index.md
    self-check.md
  meta/
    self-audit.md
    evolution-issues/
  evals/
    matrix.md
  goals/
```

Do not invent goals, data sources, accounts, credentials, validation output, or evidence. Leave unknown values as explicit TODOs for the user or for the first `$harnessloop-loop` setup round.

## After Initialization

Report:

- Target project path.
- Whether initialization was created, skipped, or blocked.
- Files or directories created.
- Next recommended prompt: `Use $harnessloop-loop to define the goal and start the evidence-backed loop.`

If this was a takeover intake, tell the user where to place the transfer packet and that `$harnessloop-loop` must run the intake gate before business execution continues.
