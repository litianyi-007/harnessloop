# Harnessloop Plugin Marketplace

This repository is a local marketplace scaffold for one plugin:

- `plugins/harnessloop/` is the plugin source.
- `.agents/plugins/marketplace.json` is the Codex marketplace manifest.
- `.claude-plugin/marketplace.json` is the Claude Code marketplace manifest.
- `plugins/harnessloop/skills/` is reserved for skills that will be added later.

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

## Add Skills Later

Add future skills under:

```text
plugins/harnessloop/skills/
```

Keep the plugin name as `harnessloop` in both manifests so marketplace selectors stay stable:

```text
harnessloop@harnessloop
```
