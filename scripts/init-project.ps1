[CmdletBinding()]
param(
  [string]$Project = ".",
  [string]$Intake,
  [switch]$Force,
  [switch]$DryRun,
  [switch]$Json
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$InitScript = Join-Path $RepoRoot "plugins/harnessloop/skills/harness-loop/scripts/init_project.py"

if (-not (Test-Path -LiteralPath $InitScript)) {
  throw "Missing Harnessloop init script: $InitScript"
}

$Args = @($InitScript, "--project", $Project)
if ($Intake) {
  $Args += @("--intake", $Intake)
}
if ($Force) {
  $Args += "--force"
}
if ($DryRun) {
  $Args += "--dry-run"
}
if ($Json) {
  $Args += "--json"
}

& python @Args
exit $LASTEXITCODE

