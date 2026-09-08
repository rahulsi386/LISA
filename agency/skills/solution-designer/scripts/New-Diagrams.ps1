[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ModelPath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$IconManifestPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'resources\icon-manifest.json'),
    [string]$ReferenceManifestPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'resources\reference-manifest.json'),
    [ValidateSet('Balanced', 'Spacious', 'Wide')][string]$LayoutProfile = 'Balanced'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$OutputDirectory = [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory))
if ((Split-Path $OutputDirectory -Leaf) -cne 'design') {
    throw "OutputDirectory must be the design child of the configured output root: $OutputDirectory"
}
foreach ($file in @($ModelPath, $IconManifestPath, $ReferenceManifestPath)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required diagram input is missing: $file" }
}
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw 'Node.js is required for the packaged measured-layout renderer.' }
$generator = Join-Path (Split-Path $PSScriptRoot -Parent) 'renderer\generate.js'
$result = & ([string]$node.Source) $generator --model $ModelPath --output $OutputDirectory `
    --icons $IconManifestPath --references $ReferenceManifestPath --profile $LayoutProfile
if ($LASTEXITCODE -ne 0) { throw "Diagram generation failed for the $LayoutProfile profile." }
$result | ConvertFrom-Json
