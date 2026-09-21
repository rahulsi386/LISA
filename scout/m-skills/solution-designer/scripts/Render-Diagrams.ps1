[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$SvgPaths,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][string]$ProfileRoot,
    [ValidateRange(5, 120)][int]$TimeoutSeconds = 45
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$outputDirectory = Split-Path ([IO.Path]::GetFullPath($OutputPath)) -Parent
if ((Split-Path $outputDirectory -Leaf) -cne 'design') {
    throw "OutputPath must be stored directly under tempOutputPath\design: $OutputPath"
}
foreach ($svgPath in $SvgPaths) {
    if ((Split-Path ([IO.Path]::GetFullPath($svgPath)) -Parent) -ne $outputDirectory) {
        throw "SVG must be stored in the same Design directory as the render report: $svgPath"
    }
    if (-not (Test-Path -LiteralPath $svgPath -PathType Leaf)) {
        throw "SVG not found: $svgPath"
    }
}

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    throw 'Node.js is required for deterministic resvg rendering.'
}
$skillRoot = Split-Path $PSScriptRoot -Parent
$renderer = Join-Path $skillRoot 'renderer\render.js'
if (-not (Test-Path -LiteralPath $renderer -PathType Leaf)) {
    throw "Packaged resvg renderer was not found: $renderer"
}

$started = [DateTimeOffset]::Now
$startInfo = [Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = [string]$node.Source
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$renderArguments = @($renderer, '--report', $OutputPath) + $SvgPaths
$startInfo.Arguments = @(
    $renderArguments | ForEach-Object {
        '"' + ([string]$_).Replace('"', '\"') + '"'
    }
) -join ' '
$process = [Diagnostics.Process]::new()
$process.StartInfo = $startInfo
if (-not $process.Start()) {
    throw 'Failed to start the packaged resvg renderer.'
}

try {
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "resvg rendering exceeded the $TimeoutSeconds-second timeout."
    }
    if ($process.ExitCode -ne 0) {
        $details = $process.StandardError.ReadToEnd().Trim()
        if ([string]::IsNullOrWhiteSpace($details)) { $details = 'No error output was captured.' }
        throw "resvg rendering failed with exit code $($process.ExitCode): $details"
    }
} finally {
    $process.Dispose()
    if (Test-Path -LiteralPath $ProfileRoot -PathType Container) {
        Remove-Item -LiteralPath $ProfileRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
    throw "resvg did not produce its render report: $OutputPath"
}
$report = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
if ([string]$report.renderer -ne '@resvg/resvg-js 2.6.2') {
    throw "Unexpected renderer reported: $($report.renderer)"
}
foreach ($render in @($report.renders)) {
    if (-not (Test-Path -LiteralPath ([string]$render.png) -PathType Leaf)) {
        throw "PNG render is missing: $($render.png)"
    }
    if ([long]$render.bytes -lt 1000) {
        throw "PNG render is unexpectedly small: $($render.png)"
    }
    if ([string]$render.sha256 -notmatch '^[a-f0-9]{64}$') {
        throw "PNG render has an invalid hash: $($render.png)"
    }
}

$report
