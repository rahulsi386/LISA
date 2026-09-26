[CmdletBinding()]
param(
    [string]$ReferenceManifestPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'resources\reference-manifest.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$manifest = Get-Content -LiteralPath $ReferenceManifestPath -Raw | ConvertFrom-Json
$refreshedAt = [DateTimeOffset]::Parse([string]$manifest.refreshedAt)
$ageDays = ([DateTimeOffset]::Now - $refreshedAt).TotalDays
[pscustomobject]@{
    status = if ($ageDays -le [double]$manifest.maxAgeDays) { 'packaged-fresh' } else { 'packaged-stale' }
    refreshedAt = $refreshedAt.ToString('o')
    ageDays = [Math]::Round($ageDays, 2)
    maxAgeDays = [double]$manifest.maxAgeDays
    sourceCount = @($manifest.sources).Count
    timedRunNetworkAccess = [bool]$manifest.timedRunNetworkAccess
}
