param(
    [string]$Python = 'python',
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$demoScript = Join-Path $PSScriptRoot 'run_demo.py'
$demoArgs = @($demoScript)
if ($SkipTests) { $demoArgs += '--skip-tests' }
& $Python @demoArgs
if ($LASTEXITCODE -ne 0) { throw "Demo failed with exit code $LASTEXITCODE" }
