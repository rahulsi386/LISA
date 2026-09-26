[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'solution_designer.py'

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python is required to run the solution-designer orchestrator.'
}

& python $scriptPath @Arguments
exit $LASTEXITCODE
