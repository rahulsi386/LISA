[CmdletBinding()]
param(
    [switch]$InstallPythonPackages,
    [switch]$RestoreRenderer,
    [switch]$RequireCloudStages,
    [switch]$RequireAzureMcp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$pluginRoot = Split-Path $PSScriptRoot -Parent
$failures = [System.Collections.Generic.List[string]]::new()

function Test-CommandVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][version]$Minimum
    )

    $resolved = Get-Command $Command -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $resolved) {
        $failures.Add("$Command was not found on PATH.")
        return
    }
    $output = (& $resolved.Source @Arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $output -notmatch $Pattern) {
        $failures.Add("Cannot determine the $Command version from: $output")
        return
    }
    $actual = [version]$Matches.version
    if ($actual -lt $Minimum) {
        $failures.Add("$Command $Minimum or newer is required; found $actual.")
        return
    }
    Write-Host "OK  $Command $actual" -ForegroundColor Green
}

if (-not $IsWindows) {
    $failures.Add('The packaged LISA Agency distribution currently supports Windows only.')
}

Test-CommandVersion -Command 'python' -Arguments @('--version') -Pattern 'Python\s+(?<version>\d+\.\d+\.\d+)' -Minimum ([version]'3.11.0')
Test-CommandVersion -Command 'node' -Arguments @('--version') -Pattern 'v(?<version>\d+\.\d+\.\d+)' -Minimum ([version]'20.0.0')
Test-CommandVersion -Command 'pwsh' -Arguments @('--version') -Pattern 'PowerShell\s+(?<version>\d+\.\d+\.\d+)' -Minimum ([version]'7.0.0')
Test-CommandVersion -Command 'dotnet' -Arguments @('--version') -Pattern '(?m)^(?<version>\d+\.\d+\.\d+)' -Minimum ([version]'10.0.100')

foreach ($command in 'npm', 'npx') {
    if ($null -eq (Get-Command $command -ErrorAction SilentlyContinue)) {
        $failures.Add("$command is required for Playwright MCP and renderer restoration but was not found on PATH.")
    }
}

if ($InstallPythonPackages) {
    & python -m pip install --upgrade -r (Join-Path $pluginRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        $failures.Add('Python dependency installation failed.')
    }
}

$imports = 'jsonschema', 'pypdf', 'docx', 'pptx', 'PIL', 'openpyxl', 'tzdata'
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

$layoutEngine = Join-Path $pluginRoot 'skills\solution-designer\resources\layout-engine\SolutionDesigner.LayoutEngine.exe'
if (-not (Test-Path -LiteralPath $layoutEngine -PathType Leaf)) {
    $failures.Add("Packaged layout engine is missing: $layoutEngine")
}
else {
    Write-Host 'OK  Packaged layout engine' -ForegroundColor Green
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