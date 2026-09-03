[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'requirement_analyzer.py'

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python is required to run the requirement-analyzer pipeline.'
}

& python $scriptPath @Arguments
exit $LASTEXITCODE
