[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'complexity_classifier.py'

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python is required to run the complexity-classifier pipeline.'
}

& python $scriptPath @Arguments
exit $LASTEXITCODE
