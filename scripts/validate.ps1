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

  $ClaudeCommand = (Get-Command claude.cmd -ErrorAction SilentlyContinue).Source
  if (-not $ClaudeCommand -and (Test-Path -LiteralPath "C:\nvm4w\nodejs\claude.cmd")) {
    $ClaudeCommand = "C:\nvm4w\nodejs\claude.cmd"
  }
  if (-not $ClaudeCommand) {
    throw "claude.cmd not found. Install Claude Code or add it to PATH."
  }

  $Output = & $ClaudeCommand plugin validate --strict $Path 2>&1
  $ExitCode = $LASTEXITCODE
  $Output | ForEach-Object { Write-Host $_ }

  if ($ExitCode -ne 0 -or (($Output -join "`n") -match "Validation failed")) {
    throw "Claude plugin validation failed for $Path"
  }
}

function Resolve-Python3 {
  $Candidates = @(
    @("py", "-3"),
    @("python3"),
    @("python")
  )

  foreach ($Candidate in $Candidates) {
    $Command = $Candidate[0]
    $CommandArgs = @($Candidate | Select-Object -Skip 1)
    $Resolved = (Get-Command $Command -ErrorAction SilentlyContinue).Source
    if (-not $Resolved) {
      continue
    }

    $VersionOutput = & $Resolved @CommandArgs --version 2>&1
    if ($LASTEXITCODE -eq 0 -and (($VersionOutput -join " ") -match "Python 3")) {
      return @{
        Command = $Resolved
        Args = $CommandArgs
      }
    }
  }

  throw "Python 3 not found. Install Python 3 or ensure py -3, python3, or python points to Python 3."
}

function Invoke-HarnessloopInitSmoke {
  $InitScript = Join-Path $PluginRoot "skills/harnessloop-loop/scripts/init_project.py"
  if (-not (Test-Path -LiteralPath $InitScript)) {
    throw "Missing Harnessloop init script: $InitScript"
  }

  $SmokeRoot = Join-Path $RepoRoot (Join-Path ".tmp" ("init-smoke-" + [guid]::NewGuid().ToString("N")))
  New-Item -ItemType Directory -Path $SmokeRoot -Force | Out-Null

  $Python = Resolve-Python3
  $Output = & $Python.Command @($Python.Args) $InitScript --project $SmokeRoot --intake smoke-task --json 2>&1
  $ExitCode = $LASTEXITCODE
  if ($ExitCode -ne 0) {
    $Output | ForEach-Object { Write-Host $_ }
    throw "Harnessloop init smoke test failed."
  }

  $ExpectedFiles = @(
    ".harnessloop/setup/data-sources.md",
    ".harnessloop/setup/cost-context-policy.md",
    ".harnessloop/state/current.md",
    ".harnessloop/state/environment.md",
    ".harnessloop/state/control-contract.md",
    ".harnessloop/state/evidence-index.md",
    ".harnessloop/state/self-check.md",
    ".harnessloop/meta/self-audit.md",
    ".harnessloop/evals/matrix.md"
  )

  foreach ($RelativePath in $ExpectedFiles) {
    $Path = Join-Path $SmokeRoot $RelativePath
    if (-not (Test-Path -LiteralPath $Path)) {
      throw "Harnessloop init smoke test missing file: $Path"
    }
  }

  $TransferPackets = Get-ChildItem -LiteralPath (Join-Path $SmokeRoot ".harnessloop/intake") -Recurse -Filter "transfer-packet.md"
  if (@($TransferPackets).Count -ne 1) {
    throw "Harnessloop init smoke test expected one transfer-packet.md, found $(@($TransferPackets).Count)."
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

Invoke-HarnessloopInitSmoke
Invoke-ClaudePluginValidate $RepoRoot
Invoke-ClaudePluginValidate $PluginRoot

Write-Host "Plugin framework validation passed."
