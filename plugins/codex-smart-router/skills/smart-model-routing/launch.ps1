param([switch]$Check)
& (Join-Path $PSScriptRoot 'scripts\launch.ps1') -Check:$Check
exit $LASTEXITCODE
