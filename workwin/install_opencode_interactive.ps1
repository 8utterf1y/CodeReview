param(
  [Parameter(Mandatory = $true)]
  [string]$Target,

  [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = $env:PYTHON
if (-not $Python) {
  $Python = "python"
}

$Args = @("$Root\install_opencode_interactive.py", "--target", $Target)
if ($Force) {
  $Args += "--force"
}

& $Python @Args
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Host ""
Write-Host "SpecDiff OpenCode artifacts installed."
Write-Host "Run OpenCode from the target repository, then use:"
Write-Host "  /spec-audit <docs-path> .specdiff/issues.json"
