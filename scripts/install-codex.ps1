[CmdletBinding()]
param(
  [switch]$SkipMarketplaceAdd
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $SkipMarketplaceAdd) {
  codex plugin marketplace add $RepoRoot
}

codex plugin add "harnessloop@harnessloop"
