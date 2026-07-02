[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

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

$Python = Resolve-Python3
& $Python.Command @($Python.Args) (Join-Path $RepoRoot "scripts/validate.py")
exit $LASTEXITCODE
