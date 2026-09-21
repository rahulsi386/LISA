[CmdletBinding()]
param(
    [switch]$InstallPythonPackages,
    [switch]$RestoreRenderer,
    [switch]$RequireCloudStages,
    [switch]$RequireAzureMcp,
    [switch]$RequireGepa
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$pluginRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'Get-LisaRuntimePrerequisites.ps1')
$failures = [System.Collections.Generic.List[string]]::new()

if (-not $IsWindows) {
    $failures.Add('The packaged LISA Agency distribution currently supports Windows only.')
}

foreach ($requirement in Get-LisaRuntimePrerequisites) {
    if (-not $requirement.Installed) {
        $failures.Add("$($requirement.Requirement): $($requirement.Details)")
    }
    else {
        Write-Host "OK  $($requirement.Requirement)" -ForegroundColor Green
    }
}

if ($InstallPythonPackages) {
    & python -m pip install --upgrade -r (Join-Path $pluginRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        $failures.Add('Python dependency installation failed.')
    }
}

$imports = 'jsonschema', 'pypdf', 'docx', 'pptx', 'PIL', 'openpyxl', 'tzdata', 'networkx'
if ($RequireGepa) {
    if ($InstallPythonPackages) {
        & python -m pip install -r (Join-Path $pluginRoot 'skills\agent-optimizer\requirements-gepa.txt')
        if ($LASTEXITCODE -ne 0) { $failures.Add('Optional GEPA installation failed.') }
    }
    & python -c 'import sys; from importlib.metadata import version; assert (3,11) <= sys.version_info[:2] < (3,15); assert version("gepa") == "0.1.4"; import gepa'
    if ($LASTEXITCODE -ne 0) {
        $failures.Add('Agency GEPA requires Python 3.11-3.14 and gepa==0.1.4; install its optional requirements.')
    }
    else { Write-Host 'OK  Agency GEPA core; live shadow isolation and reflection approval are checked per run.' -ForegroundColor Green }
}
$importProbe = 'import importlib.util,sys; missing=[x for x in sys.argv[1:] if importlib.util.find_spec(x) is None]; print("\n".join(missing)); raise SystemExit(bool(missing))'
$missingImports = (& python -c $importProbe @imports 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    $failures.Add("Missing Python modules: $($missingImports -replace "`r?`n", ', ')")
}
else {
    Write-Host 'OK  Python modules' -ForegroundColor Green
}

$renderer = Join-Path $pluginRoot 'skills\solution-designer\renderer'
if ($RestoreRenderer) {
    & npm --prefix $renderer ci --omit=dev
    if ($LASTEXITCODE -ne 0) {
        $failures.Add('Solution Designer renderer restoration failed.')
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $renderer 'node_modules\@resvg\resvg-js'))) {
    $failures.Add('Renderer dependencies are absent. Re-run with -RestoreRenderer.')
}
else {
    Write-Host 'OK  Solution Designer renderer' -ForegroundColor Green
}

$layoutEngine = Join-Path $pluginRoot 'skills\solution-designer\scripts\layout_engine.py'
if (-not (Test-Path -LiteralPath $layoutEngine -PathType Leaf)) {
    $failures.Add("Packaged Python layout router is missing: $layoutEngine")
}
else {
    Write-Host 'OK  Packaged Python layout router (no .NET runtime required)' -ForegroundColor Green
}

if ($RequireCloudStages) {
    foreach ($command in 'pac') {
        if ($null -eq (Get-Command $command -ErrorAction SilentlyContinue)) {
            $failures.Add("$command is required for cloud stages but was not found on PATH.")
        }
    }
}

if ($RequireAzureMcp) {
    if ($null -eq (Get-Command 'az' -ErrorAction SilentlyContinue)) {
        $failures.Add('Azure CLI (az) is required for the recommended Azure MCP authentication flow but was not found on PATH.')
    }
    else {
        Write-Host 'OK  Azure CLI available; sign in separately to the intended Azure tenant.' -ForegroundColor Green
    }
}

if ($failures.Count -gt 0) {
    Write-Host "`nLISA Agency prerequisite check failed:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    exit 1
}

Write-Host "`nLISA Agency prerequisites are ready." -ForegroundColor Green