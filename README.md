# Harnessloop Plugin Marketplace

This repository is a local marketplace scaffold for one plugin:

- `plugins/harnessloop/` is the plugin source.
- `.agents/plugins/marketplace.json` is the Codex marketplace manifest.
- `.claude-plugin/marketplace.json` is the Claude Code marketplace manifest.
- `plugins/harnessloop/skills/` contains the installable Harnessloop skills.

Current design files:

- `docs/harnessloop-framework.md` explains the minimal framework.
- `docs/usage.md` is the product-level usage guide.
- `docs/harnessloop-flow.mmd` contains the Mermaid flow source.
- `docs/harnessloop-flow.svg` is a directly viewable flow diagram.
- `plugins/harnessloop/skills/harness-loop/SKILL.md` is the first installable skill draft.
- `plugins/harnessloop/skills/harness-loop-issue/SKILL.md` analyzes Harnessloop evolution issues.
- `examples/mock-project/` is a small project-local Harnessloop sample.

## Install In Codex

Add the marketplace, then install the plugin:

```powershell
.\scripts\install-codex.ps1
```

If the marketplace is already configured and you only need to reinstall the plugin:

```powershell
.\scripts\install-codex.ps1 -SkipMarketplaceAdd
```

Equivalent CLI commands:

```powershell
codex plugin marketplace add .
codex plugin add harnessloop@harnessloop
```

## Install In Claude Code

Add the marketplace, then install the plugin:

```powershell
.\scripts\install-claude.ps1
```

Choose a Claude Code install scope when needed:

```powershell
.\scripts\install-claude.ps1 -Scope project
.\scripts\install-claude.ps1 -Scope local
```

If the marketplace is already configured and you only need to reinstall the plugin:

```powershell
.\scripts\install-claude.ps1 -SkipMarketplaceAdd
```

Equivalent CLI commands:

```powershell
claude plugin marketplace add . --scope user
claude plugin install harnessloop@harnessloop --scope user
```

## Validate

```powershell
.\scripts\validate.ps1
```

The validation script checks both marketplace manifests and runs Claude Code strict validation
against the marketplace root and plugin root.

## Plugin Skill Layout

Skills live under:

```text
plugins/harnessloop/skills/
```

Keep the plugin name as `harnessloop` in both manifests so marketplace selectors stay stable:

```text
harnessloop@harnessloop
```
