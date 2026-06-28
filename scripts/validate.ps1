[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PluginRoot = Join-Path $RepoRoot "plugins/harnessloop"

function Read-JsonFile {
  param([Parameter(Mandatory = $true)][string]$Path)

  if (-not (Test-Path -LiteralPath $Path)) {
    throw "Missing required file: $Path"
  }

  return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Invoke-ClaudePluginValidate {
  param([Parameter(Mandatory = $true)][string]$Path)

  $Output = & claude plugin validate $Path --strict 2>&1
  $ExitCode = $LASTEXITCODE
  $Output | ForEach-Object { Write-Host $_ }

  if ($ExitCode -ne 0 -or (($Output -join "`n") -match "Validation failed")) {
    throw "Claude plugin validation failed for $Path"
  }
}

$CodexManifestPath = Join-Path $PluginRoot ".codex-plugin/plugin.json"
$CodexMarketplacePath = Join-Path $RepoRoot ".agents/plugins/marketplace.json"
$ClaudeManifestPath = Join-Path $PluginRoot ".claude-plugin/plugin.json"
$ClaudeMarketplacePath = Join-Path $RepoRoot ".claude-plugin/marketplace.json"

$CodexManifest = Read-JsonFile $CodexManifestPath
$CodexMarketplace = Read-JsonFile $CodexMarketplacePath
$ClaudeManifest = Read-JsonFile $ClaudeManifestPath
$ClaudeMarketplace = Read-JsonFile $ClaudeMarketplacePath

if ($CodexManifest.name -ne "harnessloop") {
  throw "Codex plugin name must be harnessloop."
}

$CodexEntry = @($CodexMarketplace.plugins | Where-Object { $_.name -eq "harnessloop" })[0]
if ($null -eq $CodexEntry) {
  throw "Codex marketplace is missing the harnessloop entry."
}
if ($CodexEntry.source.source -ne "local" -or $CodexEntry.source.path -ne "./plugins/harnessloop") {
  throw "Codex marketplace entry must point to local ./plugins/harnessloop."
}
if ($CodexEntry.policy.installation -ne "AVAILABLE" -or $CodexEntry.policy.authentication -ne "ON_INSTALL") {
  throw "Codex marketplace policy must be AVAILABLE / ON_INSTALL."
}

if ($ClaudeManifest.name -ne "harnessloop") {
  throw "Claude plugin name must be harnessloop."
}

$ClaudeEntry = @($ClaudeMarketplace.plugins | Where-Object { $_.name -eq "harnessloop" })[0]
if ($null -eq $ClaudeEntry) {
  throw "Claude marketplace is missing the harnessloop entry."
}
if ($ClaudeEntry.source -ne "./plugins/harnessloop") {
  throw "Claude marketplace entry must point to ./plugins/harnessloop."
}

Invoke-ClaudePluginValidate $RepoRoot
Invoke-ClaudePluginValidate $PluginRoot

Write-Host "Plugin framework validation passed."
