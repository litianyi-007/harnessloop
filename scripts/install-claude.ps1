[CmdletBinding()]
param(
  [ValidateSet("user", "project", "local")]
  [string]$Scope = "user",

  [switch]$SkipMarketplaceAdd
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $SkipMarketplaceAdd) {
  claude plugin marketplace add $RepoRoot --scope $Scope
}

claude plugin install "harnessloop@harnessloop" --scope $Scope
