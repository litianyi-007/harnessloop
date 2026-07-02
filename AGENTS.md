# Repository Guidelines

## Project Structure & Module Organization

This repository packages Harnessloop as a local plugin marketplace. Core plugin code lives in `plugins/harnessloop/`, with Codex and Claude manifests under `.codex-plugin/` and `.claude-plugin/`. Skills live in `plugins/harnessloop/skills/`; each skill has a `SKILL.md`, optional `agents/`, reusable `references/` templates, and scripts such as `skills/harnessloop-loop/scripts/init_project.py`. Documentation and diagrams are in `docs/`, with source assets in `docs/assets/`. Example generated project state is under `examples/mock-project/`. Repository-level install, validation, and init entry points are in `scripts/`.

## Build, Test, and Development Commands

- `npm run validate`: runs `scripts/validate.py` (via a Node shim that resolves Python 3), checking manifests, marketplace entries, init smoke output, secrets smoke output, documentation skeleton consistency, mechanical protocol gates (`verify_protocol.py`), and Claude strict plugin validation. `scripts/validate.ps1` and `scripts/validate.sh` are thin wrappers around the same validator. Set `HARNESSLOOP_SKIP_CLAUDE=1` to skip the Claude CLI step where it is not installed (e.g. CI).
- `npm run init:project -- --project C:\path\to\project`: initializes Harnessloop files in a target project through the Python wrapper.
- `npm run install:codex` / `npm run install:claude`: installs the local marketplace plugin for the target agent.
- `./scripts/install-codex.sh` and `./scripts/install-claude.sh`: Unix equivalents for local installation.

Run commands from the repository root so relative marketplace paths such as `./plugins/harnessloop` resolve correctly.

## Coding Style & Naming Conventions

Prefer small, explicit scripts and stable file names because plugin manifests and marketplace entries depend on paths. PowerShell scripts use two-space indentation, `$PascalCase` variables, `CmdletBinding()`, `$ErrorActionPreference = "Stop"`, and `-LiteralPath` for filesystem checks. Python helper scripts should stay standard-library friendly unless a dependency is intentionally added. Keep plugin names as `harnessloop` in all manifests and marketplace entries.

## Testing Guidelines

There is no separate unit-test suite yet; `npm run validate` is the required regression check before changes. It verifies required JSON fields, runs the Harnessloop init smoke test, and calls Claude plugin validation. For skill changes, also run the Codex skill validator shown in `README.md` against the affected skill directory. Check generated `.harnessloop/` files in a temporary project when changing templates or `init_project.py`.

## Commit & Pull Request Guidelines

Git history uses Conventional Commit-style prefixes, especially `feat:`. Use concise subjects such as `feat: add intake validation template` or `fix: preserve marketplace path`. Pull requests should describe the behavior change, list validation commands run, link related issues when available, and include screenshots only for documentation image changes.

## Security & Configuration Tips

Do not commit generated `.tmp/`, `node_modules/`, local secrets, credentials, or real customer evidence. Transfer packet and template examples should mention credential requirements without storing secret values.
