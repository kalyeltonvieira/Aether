[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ExtraArgs)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    & python scripts/run_studio.py @ExtraArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
