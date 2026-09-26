[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateSet('Scout', 'CopilotCli', 'Agency')]
    [string]$Platform,
    [string]$ProjectPath,
    [switch]$SkipProjectSetup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:InstallerCmdlet = $PSCmdlet
$script:InstalledPackages = New-Object System.Collections.Generic.List[string]
$script:VerifiedComponents = New-Object System.Collections.Generic.List[string]

$DistributionRoot = $PSScriptRoot
$ScoutSkillsRoot = Join-Path $DistributionRoot 'scout\m-skills'
$PluginRoot = Join-Path $DistributionRoot 'github-copilot'
$RequirementsPath = Join-Path $DistributionRoot 'requirements.txt'
. (Join-Path $PluginRoot 'scripts\Get-LisaRuntimePrerequisites.ps1')
$userProfile = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
if ([string]::IsNullOrWhiteSpace($userProfile)) {
    throw 'The current Windows user profile directory cannot be resolved.'
}
$ScoutRoot = Join-Path $userProfile '.scout'
$script:TargetPlatform = $Platform
# Both distributions share the same solution-designer subtree, so one skills root drives every check.
$script:SourceSkillsRoot = $null

function Write-Section {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "`n== $Message ==" -ForegroundColor Cyan
}

function Update-ProcessPath {
    $paths = @(
        [Environment]::GetEnvironmentVariable('Path', 'Machine'),
        [Environment]::GetEnvironmentVariable('Path', 'User'),
        (Join-Path $env:USERPROFILE '.dotnet\tools'),
        $env:Path
    )
    $unique = New-Object System.Collections.Generic.List[string]
    foreach ($entry in (($paths -join ';') -split ';')) {
        if (-not [string]::IsNullOrWhiteSpace($entry) -and $unique -notcontains $entry) {
            $unique.Add($entry)
        }
    }
    $env:Path = $unique -join ';'
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter()][string[]]$Arguments = @(),
        [Parameter()][switch]$Quiet
    )

    $output = & $FilePath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if (-not $Quiet -and $null -ne $output) {
        $output | ForEach-Object { Write-Host $_ }
    }
    if ($exitCode -ne 0) {
        $rendered = ($output | Out-String).Trim()
        throw "Command failed with exit code $exitCode`: $FilePath $($Arguments -join ' ')`n$rendered"
    }
}

function Invoke-PythonSource {
    param(
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [Parameter(Mandatory = $true)][string]$Source
    )

    $output = $Source | & $PythonPath - 2>&1
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Text     = ($output | Out-String).Trim()
    }
}

function Install-WinGetPackage {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$DisplayName
    )

    if (-not $script:InstallerCmdlet.ShouldProcess($DisplayName, "Install WinGet package $Id")) {
        return
    }

    Invoke-NativeCommand -FilePath 'winget' -Arguments @(
        'install', '--id', $Id, '--exact', '--source', 'winget',
        '--accept-package-agreements', '--accept-source-agreements',
        '--silent', '--disable-interactivity'
    )
    $script:InstalledPackages.Add($DisplayName)
    Update-ProcessPath
}

function Ensure-WinGet {
    if ($null -eq (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'WinGet is required. Install or update Microsoft App Installer, reopen PowerShell, and run this script again.'
    }
    $script:VerifiedComponents.Add('WinGet')
}

function Ensure-Python {
    $python = Get-VersionFromCommand -Command 'python' -Arguments @('--version') -Pattern 'Python\s+(?<version>\d+\.\d+\.\d+)'
    if ($null -eq $python -or $python.Version -lt $LisaRuntimeVersions.Python) {
        Install-WinGetPackage -Id 'Python.Python.3.13' -DisplayName 'Python 3.13'
        Update-ProcessPath
        $python = Get-VersionFromCommand -Command 'python' -Arguments @('--version') -Pattern 'Python\s+(?<version>\d+\.\d+\.\d+)'
    }
    if ($null -eq $python) {
        if ($WhatIfPreference) {
            Write-Warning 'Python verification is deferred because -WhatIf skipped installation.'
            return $null
        }
        throw 'Python 3.11 or newer was not found after installation. Open a new terminal and rerun this script.'
    }
    if ($python.Version -lt $LisaRuntimeVersions.Python) {
        throw "Python 3.11 or newer is required; found $($python.Version) at $($python.Path)."
    }
    Write-Host "Python $($python.Version): $($python.Path)"
    $script:VerifiedComponents.Add("Python $($python.Version)")
    return $python.Path
}

function Ensure-Node {
    $node = Get-VersionFromCommand -Command 'node' -Arguments @('--version') -Pattern 'v(?<version>\d+\.\d+\.\d+)'
    $missingCommands = @($LisaNodeCommands | Where-Object { $null -eq (Get-Command $_ -ErrorAction SilentlyContinue) })
    if ($null -eq $node -or $node.Version -lt $LisaRuntimeVersions.Node -or $missingCommands.Count -gt 0) {
        Install-WinGetPackage -Id 'OpenJS.NodeJS.LTS' -DisplayName 'Node.js LTS'
        Update-ProcessPath
        $node = Get-VersionFromCommand -Command 'node' -Arguments @('--version') -Pattern 'v(?<version>\d+\.\d+\.\d+)'
    }
    if ($null -eq $node) {
        if ($WhatIfPreference) {
            Write-Warning 'Node.js verification is deferred because -WhatIf skipped installation.'
            return $false
        }
        throw 'Node.js 20 or newer was not found after installation. Open a new terminal and rerun this script.'
    }
    if ($node.Version -lt $LisaRuntimeVersions.Node) {
        throw "Node.js 20 or newer is required; found $($node.Version)."
    }
    foreach ($command in $LisaNodeCommands) {
        if ($null -eq (Get-Command $command -ErrorAction SilentlyContinue)) {
            throw "$command was not installed with Node.js."
        }
    }
    Write-Host "Node.js $($node.Version): $($node.Path)"
    $script:VerifiedComponents.Add("Node.js $($node.Version)")
    return $true
}

function Ensure-PowerShell {
    $windowsPowerShell = Get-VersionFromCommand -Command 'powershell' -Arguments @(
        '-NoLogo', '-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()'
    ) -Pattern '(?<version>\d+\.\d+(?:\.\d+){0,2})'
    if ($null -eq $windowsPowerShell -or $windowsPowerShell.Version -lt [version]'5.1') {
        throw 'Windows PowerShell 5.1 is required and must be enabled as a Windows component.'
    }

    $powerShell = Get-VersionFromCommand -Command 'pwsh' -Arguments @('--version') -Pattern 'PowerShell\s+(?<version>\d+\.\d+\.\d+)'
    if ($null -eq $powerShell -or $powerShell.Version -lt $LisaRuntimeVersions.PowerShell) {
        Install-WinGetPackage -Id 'Microsoft.PowerShell' -DisplayName 'PowerShell 7'
        Update-ProcessPath
        $powerShell = Get-VersionFromCommand -Command 'pwsh' -Arguments @('--version') -Pattern 'PowerShell\s+(?<version>\d+\.\d+\.\d+)'
    }
    if ($null -eq $powerShell) {
        if ($WhatIfPreference) {
            Write-Warning 'PowerShell 7 verification is deferred because -WhatIf skipped installation.'
            return
        }
        throw 'PowerShell 7 was not found after installation. Open a new terminal and rerun this script.'
    }
    Write-Host "Windows PowerShell $($windowsPowerShell.Version): $($windowsPowerShell.Path)"
    Write-Host "PowerShell $($powerShell.Version): $($powerShell.Path)"
    $script:VerifiedComponents.Add("Windows PowerShell $($windowsPowerShell.Version)")
    $script:VerifiedComponents.Add("PowerShell $($powerShell.Version)")
}

function Ensure-DotNet10 {
    $dotnet = Get-VersionFromCommand -Command 'dotnet' -Arguments @('--version') -Pattern '(?<version>\d+\.\d+\.\d+)'
    if ($null -eq $dotnet -or $dotnet.Version.Major -lt 10) {
        Install-WinGetPackage -Id 'Microsoft.DotNet.SDK.10' -DisplayName '.NET 10 SDK'
        Update-ProcessPath
        $dotnet = Get-VersionFromCommand -Command 'dotnet' -Arguments @('--version') -Pattern '(?<version>\d+\.\d+\.\d+)'
    }
    if ($null -eq $dotnet -or $dotnet.Version.Major -lt 10) {
        if ($WhatIfPreference) {
            Write-Warning '.NET 10 verification is deferred because -WhatIf skipped installation.'
            return $false
        }
        throw '.NET 10 SDK was not found after installation. Open a new terminal and rerun this script.'
    }
    Write-Host ".NET SDK $($dotnet.Version): $($dotnet.Path)"
    $script:VerifiedComponents.Add(".NET SDK $($dotnet.Version)")
    return $true
}

function Test-ModernPac {
    $pac = Get-Command pac -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $pac) {
        return $false
    }

    $commands = @(
        @('copilot', 'init', 'help'),
        @('copilot', 'push', 'help'),
        @('copilot', 'pull', 'help'),
        @('copilot', 'publish', 'help'),
        @('copilot', 'list', 'help'),
        @('copilot', 'pack', 'help'),
        @('solution', 'add-solution-component', 'help'),
        @('solution', 'export', 'help')
    )
    foreach ($arguments in $commands) {
        $output = (& $pac.Source @arguments 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) {
            return $false
        }
        if ($arguments[0] -eq 'copilot' -and $arguments[1] -eq 'init') {
            if ($output -notmatch '--authoring-mode' -or $output -notmatch 'cli-copilot') {
                return $false
            }
        }
    }
    return $true
}

function Ensure-ModernPac {
    if (Test-ModernPac) {
        $versionOutput = (& pac help 2>&1 | Out-String)
        $versionLine = $versionOutput -split "`r?`n" |
            Where-Object { $_ -match 'Version' } |
            Select-Object -First 1
        if ([string]::IsNullOrWhiteSpace($versionLine)) {
            $versionLine = 'Version was not reported by pac help.'
        }
        else {
            $versionLine = $versionLine.Trim()
        }
        Write-Host "Modern Power Platform CLI verified. $versionLine"
        $script:VerifiedComponents.Add('Power Platform CLI with Copilot authoring')
        return
    }

    if (-not (Ensure-DotNet10)) {
        return
    }

    if (-not $script:InstallerCmdlet.ShouldProcess(
        'Microsoft.PowerApps.CLI.Tool',
        'Install or update current-user .NET global tool'
    )) {
        return
    }

    $toolList = (& dotnet tool list --global 2>&1 | Out-String)
    if ($toolList -match '(?im)^microsoft\.powerapps\.cli\.tool\s') {
        Invoke-NativeCommand -FilePath 'dotnet' -Arguments @(
            'tool', 'update', '--global', 'Microsoft.PowerApps.CLI.Tool'
        )
    }
    else {
        Invoke-NativeCommand -FilePath 'dotnet' -Arguments @(
            'tool', 'install', '--global', 'Microsoft.PowerApps.CLI.Tool'
        )
    }
    $script:InstalledPackages.Add('Microsoft Power Platform CLI')
    Update-ProcessPath

    if (-not (Test-ModernPac)) {
        throw 'PAC CLI was installed, but the required Copilot and solution command surface is unavailable.'
    }
    $script:VerifiedComponents.Add('Power Platform CLI with Copilot authoring')
}

function Install-PythonRequirements {
    param([Parameter(Mandatory = $true)][string]$PythonPath)

    if (-not (Test-Path -LiteralPath $RequirementsPath -PathType Leaf)) {
        throw "Python requirements file does not exist: $RequirementsPath"
    }

    $pipCheck = & $PythonPath -m pip --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        if ($script:InstallerCmdlet.ShouldProcess('Python environment', 'Bootstrap pip')) {
            Invoke-NativeCommand -FilePath $PythonPath -Arguments @('-m', 'ensurepip', '--upgrade')
        }
    }

    if ($script:InstallerCmdlet.ShouldProcess($RequirementsPath, 'Install or update Python requirements')) {
        Invoke-NativeCommand -FilePath $PythonPath -Arguments @(
            '-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check',
            '-r', (Resolve-Path -LiteralPath $RequirementsPath).ProviderPath
        )
        $script:InstalledPackages.Add('LISA Python requirements')
    }

    if ($WhatIfPreference) {
        Write-Warning 'Python package verification is deferred because -WhatIf skipped installation.'
        return
    }

    $verification = @'
import jsonschema
from jsonschema import FormatChecker
import pypdf
import docx
import pptx
from PIL import Image
import openpyxl
from zoneinfo import ZoneInfo

checker = FormatChecker()
assert "date-time" in checker.checkers
assert "uri" in checker.checkers
assert checker.conforms("2026-08-28T12:00:00Z", "date-time")
assert not checker.conforms("not-a-date", "date-time")
assert checker.conforms("https://learn.microsoft.com/", "uri")
ZoneInfo("Asia/Kolkata")
print("Python imports, schema formats, and IANA time zones verified")
'@
    $result = Invoke-PythonSource -PythonPath $PythonPath -Source $verification
    if ($result.ExitCode -ne 0) {
        throw "Python library verification failed:`n$($result.Text)"
    }
    Write-Host $result.Text
    $script:VerifiedComponents.Add('LISA Python libraries')
}

function Ensure-Renderer {
    $rendererRoot = Join-Path $SourceSkillsRoot 'solution-designer\renderer'
    $packageLock = Join-Path $rendererRoot 'package-lock.json'
    $renderer = Join-Path $rendererRoot 'render.js'
    if (-not (Test-Path -LiteralPath $packageLock -PathType Leaf) -or
        -not (Test-Path -LiteralPath $renderer -PathType Leaf)) {
        throw "Solution Designer renderer package is incomplete: $rendererRoot"
    }

    $healthy = $false
    if (Test-Path -LiteralPath (Join-Path $rendererRoot 'node_modules') -PathType Container) {
        Push-Location $rendererRoot
        try {
            $null = & npm ls --depth=0 2>&1
            $healthy = $LASTEXITCODE -eq 0
        }
        finally {
            Pop-Location
        }
    }

    if (-not $healthy -and $script:InstallerCmdlet.ShouldProcess($rendererRoot, 'Restore locked npm dependencies')) {
        Push-Location $rendererRoot
        try {
            Invoke-NativeCommand -FilePath 'npm' -Arguments @(
                'ci', '--no-audit', '--no-fund'
            )
        }
        finally {
            Pop-Location
        }
        $script:InstalledPackages.Add('Solution Designer npm dependencies')
    }

    if (-not $WhatIfPreference -or $healthy) {
        Invoke-NativeCommand -FilePath 'node' -Arguments @($renderer, '--self-test')
        $script:VerifiedComponents.Add('Solution Designer renderer')
    }
}

function Get-ScoutExecutable {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Microsoft Scout\scout.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\scout.exe')
    )
    $command = Get-Command scout.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) {
        $candidates += $command.Source
    }
    return $candidates | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_) -and
        (Test-Path -LiteralPath $_ -PathType Leaf)
    } | Select-Object -First 1
}

function Test-ScoutProcessRunning {
    param([Parameter(Mandatory = $true)][string]$ScoutExecutable)

    $expectedPath = [IO.Path]::GetFullPath($ScoutExecutable)
    foreach ($process in @(Get-Process -Name 'scout' -ErrorAction SilentlyContinue)) {
        try {
            if ([string]::Equals(
                [IO.Path]::GetFullPath($process.Path),
                $expectedPath,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                return $true
            }
        }
        catch {
            continue
        }
    }
    return $false
}

function Test-PythonLibraries {
    param([Parameter(Mandatory = $true)][string]$PythonPath)

    $verification = @'
import importlib.metadata
import json

checks = {}
packages = {
    "jsonschema[format-nongpl]": "jsonschema",
    "pypdf": "pypdf",
    "python-docx": "python-docx",
    "python-pptx": "python-pptx",
    "Pillow": "Pillow",
    "openpyxl": "openpyxl",
    "tzdata": "tzdata",
    "networkx": "networkx",
}
for label, distribution in packages.items():
    try:
        checks[label] = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        checks[label] = None

try:
    from jsonschema import FormatChecker
    checker = FormatChecker()
    checks["jsonschema-formats"] = bool(
        checker.conforms("2026-08-28T12:00:00Z", "date-time")
        and not checker.conforms("not-a-date", "date-time")
        and checker.conforms("https://learn.microsoft.com/", "uri")
    )
except Exception:
    checks["jsonschema-formats"] = False

try:
    from zoneinfo import ZoneInfo
    ZoneInfo("Asia/Kolkata")
    checks["iana-timezones"] = True
except Exception:
    checks["iana-timezones"] = False

print(json.dumps(checks, sort_keys=True))
'@
    try {
        $result = Invoke-PythonSource -PythonPath $PythonPath -Source $verification
        if ($result.ExitCode -ne 0) {
            return [pscustomobject]@{
                Installed = $false
                Details   = $result.Text
            }
        }
        $checks = $result.Text | ConvertFrom-Json
        $missing = @(
            $checks.PSObject.Properties |
                Where-Object { $null -eq $_.Value -or $_.Value -eq $false } |
                Select-Object -ExpandProperty Name
        )
        return [pscustomobject]@{
            Installed = $missing.Count -eq 0
            Details   = if ($missing.Count -eq 0) {
                'All packages, JSON formats, and IANA time zones are available.'
            }
            else {
                "Missing or incomplete: $($missing -join ', ')"
            }
        }
    }
    catch {
        return [pscustomobject]@{
            Installed = $false
            Details   = $_.Exception.Message
        }
    }
}

function Test-RendererPrerequisite {
    $rendererRoot = Join-Path $SourceSkillsRoot 'solution-designer\renderer'
    if (-not (Test-Path -LiteralPath (Join-Path $rendererRoot 'package-lock.json') -PathType Leaf)) {
        return [pscustomobject]@{ Installed = $false; Details = 'package-lock.json is missing.' }
    }
    if ($null -eq (Get-Command npm -ErrorAction SilentlyContinue)) {
        return [pscustomobject]@{ Installed = $false; Details = 'npm is unavailable.' }
    }
    Push-Location $rendererRoot
    try {
        $output = & npm ls --depth=0 2>&1
        return [pscustomobject]@{
            Installed = $LASTEXITCODE -eq 0
            Details   = if ($LASTEXITCODE -eq 0) {
                '@resvg/resvg-js and pngjs are installed.'
            }
            else {
                ($output | Out-String).Trim()
            }
        }
    }
    finally {
        Pop-Location
    }
}

function Get-PrerequisiteState {
    $python = Get-VersionFromCommand -Command 'python' -Arguments @('--version') -Pattern 'Python\s+(?<version>\d+\.\d+\.\d+)'
    $runtime = @(Get-LisaRuntimePrerequisites)
    $windowsPowerShell = Get-VersionFromCommand -Command 'powershell' -Arguments @(
        '-NoLogo', '-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()'
    ) -Pattern '(?<version>\d+\.\d+(?:\.\d+){0,2})'
    $dotnet = Get-VersionFromCommand -Command 'dotnet' -Arguments @('--version') -Pattern '(?<version>\d+\.\d+\.\d+)'
    $pythonLibraries = if ($null -ne $python -and $python.Version -ge $LisaRuntimeVersions.Python) {
        Test-PythonLibraries -PythonPath $python.Path
    }
    else {
        [pscustomobject]@{ Installed = $false; Details = 'Python 3.11+ is unavailable.' }
    }
    $renderer = Test-RendererPrerequisite
    $layoutRouter = Join-Path $SourceSkillsRoot 'solution-designer\scripts\layout_engine.py'
    $scout = Get-ScoutExecutable
    $copilotCli = Get-Command copilot -ErrorAction SilentlyContinue | Select-Object -First 1
    $agencyCli = Get-Command agency -ErrorAction SilentlyContinue | Select-Object -First 1
    $modernPac = Test-ModernPac

    return @(
        [pscustomobject]@{
            Key = 'WinGet'; Requirement = 'WinGet / Microsoft App Installer'
            Installed = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
            Details = 'Required to install missing Windows applications.'
            InstallAction = 'Install Microsoft App Installer from Microsoft Store.'
        }
        if ($script:TargetPlatform -eq 'Scout') {
            [pscustomobject]@{
                Key = 'Scout'; Requirement = 'Microsoft Scout'; Installed = $null -ne $scout
                Details = if ($null -ne $scout) { $scout } else { 'Scout executable was not found.' }
                InstallAction = 'WinGet package Microsoft.ScoutAgent.'
            }
        }
        if ($script:TargetPlatform -eq 'CopilotCli') {
            [pscustomobject]@{
                Key = 'CopilotCli'; Requirement = 'GitHub Copilot CLI'; Installed = $null -ne $copilotCli
                Details = if ($null -ne $copilotCli) { $copilotCli.Source } else { 'The copilot executable was not found on PATH.' }
                InstallAction = 'WinGet package GitHub.Copilot; sign in with copilot /login.'
            }
        }
        if ($script:TargetPlatform -eq 'Agency') {
            [pscustomobject]@{
                Key = 'Agency'; Requirement = 'Microsoft Agency (internal Microsoft only)'; Installed = $null -ne $agencyCli
                Details = if ($null -ne $agencyCli) { $agencyCli.Source } else { 'The agency executable was not found on PATH.' }
                InstallAction = 'Install Microsoft Agency through its internal Microsoft channel.'
            }
        }
        [pscustomobject]@{
            Key = 'WindowsPowerShell'; Requirement = 'Windows PowerShell 5.1+'
            Installed = $null -ne $windowsPowerShell -and $windowsPowerShell.Version -ge [version]'5.1'
            Details = if ($null -ne $windowsPowerShell) { "$($windowsPowerShell.Version) at $($windowsPowerShell.Path)" } else { 'Not found.' }
            InstallAction = 'Enable Windows PowerShell as a Windows component.'
        }
        $runtime
        [pscustomobject]@{
            Key = 'PythonLibraries'; Requirement = 'LISA Python libraries'
            Installed = [bool]$pythonLibraries.Installed; Details = $pythonLibraries.Details
            InstallAction = "Install from $RequirementsPath with pip."
        }
        [pscustomobject]@{
            Key = 'Renderer'; Requirement = 'Solution Designer npm dependencies'
            Installed = [bool]$renderer.Installed; Details = $renderer.Details
            InstallAction = 'Restore the locked renderer dependencies with npm ci.'
        }
        [pscustomobject]@{
            Key = 'Pac'; Requirement = 'Modern Power Platform CLI with Copilot commands'
            Installed = $modernPac
            Details = if ($modernPac) { 'Required copilot and solution commands are available.' } else { 'Required command surface is unavailable.' }
            InstallAction = 'Install .NET 10, then Microsoft.PowerApps.CLI.Tool.'
        }
        [pscustomobject]@{
            Key = 'DotNet'; Requirement = '.NET 10 SDK (conditional)'
            Installed = $modernPac -or ($null -ne $dotnet -and $dotnet.Version.Major -ge 10)
            Details = if ($modernPac) { 'Not needed for PAC bootstrap because modern PAC is already installed.' } elseif ($null -ne $dotnet) { "$($dotnet.Version) at $($dotnet.Path)" } else { 'Required to install modern PAC.' }
            InstallAction = 'WinGet package Microsoft.DotNet.SDK.10.'
        }
        [pscustomobject]@{
            Key = 'LayoutRouter'; Requirement = 'Packaged Solution Designer Python layout router'
            Installed = (Test-Path -LiteralPath $layoutRouter -PathType Leaf) -and (Get-Item -LiteralPath $layoutRouter -ErrorAction SilentlyContinue).Length -gt 0
            Details = $layoutRouter
            InstallAction = 'Restore scripts\layout_engine.py from the LISA distribution.'
        }
    )
}

function Show-PrerequisiteState {
    param([Parameter(Mandatory = $true)][object[]]$State)

    foreach ($item in $State) {
        $status = if ($item.Installed) { 'INSTALLED' } else { 'MISSING' }
        $color = if ($item.Installed) { 'Green' } else { 'Yellow' }
        Write-Host "[$status] $($item.Requirement)" -ForegroundColor $color
        Write-Host "  Detected: $($item.Details)"
        if (-not $item.Installed) {
            Write-Host "  Install:  $($item.InstallAction)"
        }
    }
}

function Install-MissingPrerequisites {
    param([Parameter(Mandatory = $true)][object[]]$State)

    $missingKeys = @($State | Where-Object { -not $_.Installed } | Select-Object -ExpandProperty Key)
    if ($missingKeys -contains 'WinGet') {
        throw 'WinGet cannot be bootstrapped reliably by this script. Install Microsoft App Installer and run the installer again.'
    }
    if ($missingKeys -contains 'WindowsPowerShell') {
        throw 'Windows PowerShell 5.1 must be enabled as a Windows component before continuing.'
    }
    if ($missingKeys -contains 'Scout') {
        Install-WinGetPackage -Id 'Microsoft.ScoutAgent' -DisplayName 'Microsoft Scout'
    }
    if ($missingKeys -contains 'CopilotCli') {
        Install-WinGetPackage -Id 'GitHub.Copilot' -DisplayName 'GitHub Copilot CLI'
    }
    if ($missingKeys -contains 'Agency') {
        throw 'Microsoft Agency must be installed from its internal Microsoft channel before running this installer.'
    }

    $python = Get-VersionFromCommand -Command 'python' -Arguments @('--version') -Pattern 'Python\s+(?<version>\d+\.\d+\.\d+)'
    if ($missingKeys -contains 'Python') {
        $pythonPath = Ensure-Python
    }
    else {
        $pythonPath = $python.Path
    }
    if ($missingKeys -contains 'Node') {
        $nodeAvailable = Ensure-Node
    }
    else {
        $nodeAvailable = $true
    }
    if ($missingKeys -contains 'PowerShell') {
        Ensure-PowerShell
    }
    if ($missingKeys -contains 'Pac' -or $missingKeys -contains 'DotNet') {
        Ensure-ModernPac
    }
    if ($missingKeys -contains 'PythonLibraries' -and $null -ne $pythonPath) {
        Install-PythonRequirements -PythonPath $pythonPath
    }
    if ($missingKeys -contains 'Renderer' -and $nodeAvailable) {
        Ensure-Renderer
    }
    if ($missingKeys -contains 'LayoutRouter') {
        throw 'The packaged Solution Designer Python layout router is missing from the LISA distribution.'
    }
}

function Confirm-Exact {
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    $answer = Read-Host $Prompt
    return $answer.Trim() -ceq $Expected
}

function Select-TargetPlatform {
    $options = [ordered]@{
        '1' = [pscustomobject]@{ Key = 'Scout'; Name = 'Microsoft Scout Desktop' }
        '2' = [pscustomobject]@{ Key = 'CopilotCli'; Name = 'GitHub Copilot CLI' }
        '3' = [pscustomobject]@{ Key = 'Agency'; Name = 'Microsoft Agency (internal Microsoft only)' }
    }
    Write-Host 'Where should LISA be installed?' -ForegroundColor Cyan
    foreach ($entry in $options.GetEnumerator()) {
        Write-Host ("  [{0}] {1}" -f $entry.Key, $entry.Value.Name)
    }
    while ($true) {
        $answer = (Read-Host 'Enter 1, 2 or 3').Trim()
        if ($options.Contains($answer)) {
            return $options[$answer].Key
        }
        Write-Warning 'Enter 1, 2 or 3.'
    }
}

function Get-PlatformName {
    param([Parameter(Mandatory = $true)][string]$TargetPlatform)
    switch ($TargetPlatform) {
        'Scout' { 'Microsoft Scout Desktop' }
        'CopilotCli' { 'GitHub Copilot CLI' }
        default { 'Microsoft Agency (internal Microsoft only)' }
    }
}

function Resolve-SourceSkillsRoot {
    param([Parameter(Mandatory = $true)][string]$TargetPlatform)
    $path = if ($TargetPlatform -eq 'Scout') { $ScoutSkillsRoot } else { Join-Path $PluginRoot 'skills' }
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "The LISA distribution is incomplete; expected skills under: $path"
    }
    return $path
}

function Install-LisaPlugin {
    param([Parameter(Mandatory = $true)][string]$TargetPlatform)

    $executable = if ($TargetPlatform -eq 'CopilotCli') { 'copilot' } else { 'agency' }
    $arguments = if ($TargetPlatform -eq 'CopilotCli') {
        @('plugin', 'install', $PluginRoot)
    }
    else {
        @('plugin', 'install', "local:$PluginRoot")
    }
    Write-Warning @"
The installer will register the LISA plugin from:
  $PluginRoot
with $executable. An existing installation of the same plugin is replaced.
"@
    if (-not (Confirm-Exact -Prompt 'Type INSTALL PLUGIN to register the LISA plugin, or press Enter to skip' -Expected 'INSTALL PLUGIN')) {
        Write-Warning 'Plugin registration was skipped. Register it later with the command shown above.'
        return $false
    }
    if (-not $script:InstallerCmdlet.ShouldProcess($PluginRoot, "Register the LISA plugin with $executable")) {
        return $false
    }
    Invoke-NativeCommand -FilePath $executable -Arguments $arguments
    $script:InstalledPackages.Add("LISA plugin registered with $executable")
    return $true
}

function Confirm-ScoutSignIn {
    $scout = Get-ScoutExecutable
    if ($null -eq $scout) {
        throw 'Microsoft Scout is not installed.'
    }

    if (Test-ScoutProcessRunning -ScoutExecutable $scout) {
        Write-Host 'Microsoft Scout is already running. Switch to its existing window.'
    }
    else {
        Write-Host 'Microsoft Scout will now open.'
        $explorer = Join-Path $env:WINDIR 'explorer.exe'
        Start-Process -FilePath $explorer -ArgumentList ('"{0}"' -f $scout)
    }
    Write-Host @'
In Scout, open Settings > Integrations and complete Microsoft 365 sign-in.
Return here only after Scout confirms that the Microsoft 365 account is
connected.
'@
    $confirmation = Read-Host 'Did Microsoft 365 sign-in complete successfully in Scout? [Y/N]'
    if ($confirmation.Trim() -notmatch '^(?i:y|yes)$') {
        Write-Error 'A successful Microsoft Scout sign-in is mandatory. Installation has been terminated.'
    }

    $accountRecord = Join-Path $ScoutRoot 'm-auth\msal-last-account.enc'
    if (-not (Test-Path -LiteralPath $accountRecord -PathType Leaf)) {
        Write-Error 'Scout did not create its Microsoft 365 account record. Complete Microsoft 365 sign-in and run this installer again.'
    }
    if ((Get-Item -LiteralPath $accountRecord -Force).Length -le 0) {
        Write-Error 'Scout created an empty Microsoft 365 account record. Sign in again and rerun this installer.'
    }
    Write-Host 'Microsoft 365 sign-in evidence was found in the Scout profile.' -ForegroundColor Green
}

function Initialize-LisaProject {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $lisaRoot = [IO.Path]::GetFullPath($ProjectRoot)
    $ancestor = $lisaRoot
    while (-not [string]::IsNullOrWhiteSpace($ancestor)) {
        if (Test-Path -LiteralPath $ancestor) {
            $item = Get-Item -LiteralPath $ancestor -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "The project path must contain only real directories: $ancestor"
            }
        }
        $ancestor = Split-Path $ancestor -Parent
    }

    $folders = @('requirements', 'output', 'evalData') | ForEach-Object {
        Join-Path $lisaRoot $_
    }
    foreach ($path in $folders) {
        if (Test-Path -LiteralPath $path) {
            $item = Get-Item -LiteralPath $path -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "The required project path is not a real folder: $path"
            }
        }
    }

    $configPath = Join-Path $lisaRoot 'lisa-config.json'
    if (Test-Path -LiteralPath $configPath) {
        $item = Get-Item -LiteralPath $configPath -Force
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "The project configuration is not a regular file: $configPath"
        }
    }
    if ($PSCmdlet.ShouldProcess($lisaRoot, 'Create missing project folders and configuration; preserve existing data')) {
        foreach ($path in @($lisaRoot) + $folders) {
            if (-not (Test-Path -LiteralPath $path)) {
                $null = New-Item -ItemType Directory -Path $path -Force
            }
        }
        if (-not (Test-Path -LiteralPath $configPath)) {
            $template = [IO.File]::ReadAllBytes((Join-Path $DistributionRoot 'lisa-config.json'))
            $stream = [IO.File]::Open($configPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
            try { $stream.Write($template, 0, $template.Length) }
            finally { $stream.Dispose() }
        }
        Write-Host "Project ready at $lisaRoot; existing configuration and data preserved." -ForegroundColor Green
    }
    return $lisaRoot
}

function Resolve-Codebase {
    $rawPath = Read-Host 'Enter the full path to the downloaded LISA codebase'
    $expandedPath = [Environment]::ExpandEnvironmentVariables($rawPath.Trim().Trim('"'))
    try {
        $root = (Resolve-Path -LiteralPath $expandedPath -ErrorAction Stop).ProviderPath
    }
    catch {
        throw "The LISA codebase path does not exist: $expandedPath"
    }
    if (-not (Get-Item -LiteralPath $root -Force).PSIsContainer) {
        throw "The LISA codebase path is not a folder: $root"
    }

    $skills = Join-Path $root 'scout\m-skills'
    if (-not (Test-Path -LiteralPath $skills -PathType Container) -or
        @(Get-ChildItem -LiteralPath $skills -Force).Count -eq 0) {
        throw "The mandatory scout\m-skills folder is missing or empty: $skills"
    }
    $skillDefinitions = @(Get-ChildItem -LiteralPath $skills -Directory -Force | Where-Object {
        Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') -PathType Leaf
    })
    if ($skillDefinitions.Count -eq 0) {
        throw "The scout\m-skills folder contains no skill directories with SKILL.md: $skills"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $skills 'sync_skills_metadata.py') -PathType Leaf)) {
        throw "The source scout\m-skills folder does not contain sync_skills_metadata.py: $skills"
    }
    $automations = Join-Path $root 'scout\m-automations'
    $automationsAvailable = (Test-Path -LiteralPath $automations -PathType Container) -and
        @(Get-ChildItem -LiteralPath $automations -Force).Count -gt 0
    if (-not $automationsAvailable) {
        Write-Warning 'The optional scout\m-automations folder is missing or empty. Skill installation can continue.'
    }

    $configPath = Join-Path $root 'lisa-config.json'
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "The mandatory lisa-config.json file is missing: $configPath"
    }
    try {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        if ($null -eq $config) {
            throw 'The JSON document is empty.'
        }
    }
    catch {
        throw "lisa-config.json is not valid JSON: $($_.Exception.Message)"
    }

    Write-Host "Validated $($skillDefinitions.Count) LISA skill definitions." -ForegroundColor Green
    Write-Host "Optional m-automations available: $automationsAvailable"
    Write-Host "Configuration found: $configPath"
    return [pscustomobject]@{
        Root                 = $root
        SkillsPath           = $skills
        AutomationsAvailable = $automationsAvailable
        ConfigPath           = $configPath
        SkillCount           = $skillDefinitions.Count
        SkillNames           = @($skillDefinitions | Select-Object -ExpandProperty Name)
    }
}

function Install-LisaSkills {
    param([Parameter(Mandatory = $true)][string]$SourceSkillsPath)

    $destination = Join-Path $ScoutRoot 'm-skills'
    $sourceResolved = (Resolve-Path -LiteralPath $SourceSkillsPath).ProviderPath.TrimEnd('\')
    if (Test-Path -LiteralPath $destination) {
        $destinationResolved = (Resolve-Path -LiteralPath $destination).ProviderPath.TrimEnd('\')
        if ($sourceResolved -ieq $destinationResolved) {
            Write-Host 'The selected m-skills folder is already Scout''s active m-skills folder; no copy is required.'
            return $destination
        }
    }
    else {
        $null = New-Item -ItemType Directory -Path $destination
    }

    $staging = Join-Path $ScoutRoot ('.lisa-skills-install-{0}' -f [guid]::NewGuid().ToString('N'))
    try {
        $null = New-Item -ItemType Directory -Path $staging
        Get-ChildItem -LiteralPath $SourceSkillsPath -Force | Where-Object { $_.Name -ne 'skills-metadata.json' } | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $staging -Recurse -Force
        }

        Get-ChildItem -LiteralPath $staging -Force | ForEach-Object {
            $target = Join-Path $destination $_.Name
            if (Test-Path -LiteralPath $target) {
                $targetItem = Get-Item -LiteralPath $target -Force
                if ($targetItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    throw "Refusing to replace a reparse point in Scout m-skills: $target"
                }
                Remove-Item -LiteralPath $target -Recurse -Force
            }
            Move-Item -LiteralPath $_.FullName -Destination $target
        }
    }
    finally {
        if (Test-Path -LiteralPath $staging) {
            Remove-Item -LiteralPath $staging -Recurse -Force
        }
    }
    return $destination
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This installer supports Windows only.'
}
if (-not (Test-Path -LiteralPath $RequirementsPath -PathType Leaf)) {
    throw "The prerequisite manifest is missing: $RequirementsPath"
}

Write-Section '1. Select the LISA target platform'
if ([string]::IsNullOrWhiteSpace($script:TargetPlatform)) {
    $script:TargetPlatform = Select-TargetPlatform
}
$script:SourceSkillsRoot = Resolve-SourceSkillsRoot -TargetPlatform $script:TargetPlatform
$platformName = Get-PlatformName -TargetPlatform $script:TargetPlatform
Write-Host "Target platform: $platformName" -ForegroundColor Green
Write-Host "Skill source:    $script:SourceSkillsRoot"

Write-Section '2. Check installed prerequisites'
$state = @(Get-PrerequisiteState)
Show-PrerequisiteState -State $state
$missing = @($state | Where-Object { -not $_.Installed })

if ($missing.Count -gt 0) {
    Write-Section '3. Missing prerequisites'
    Write-Host 'The following requirements must be installed:' -ForegroundColor Yellow
    foreach ($item in $missing) {
        Write-Host "`n$($item.Requirement)"
        Write-Host "  Reason:  $($item.Details)"
        Write-Host "  Action:  $($item.InstallAction)"
    }

    if ($WhatIfPreference) {
        Write-Host "`n-WhatIf was specified; no prerequisites, folders, skills, or plugins will be changed."
        return
    }
    if (-not (Confirm-Exact -Prompt 'Type INSTALL to install all missing prerequisites, or press Enter to cancel' -Expected 'INSTALL')) {
        Write-Warning 'Prerequisite installation was not approved. Installation has been terminated.'
        return
    }

    Write-Section '4. Install prerequisites'
    Install-MissingPrerequisites -State $state
    Update-ProcessPath

    $state = @(Get-PrerequisiteState)
    $remaining = @($state | Where-Object { -not $_.Installed })
    if ($remaining.Count -gt 0) {
        $names = $remaining | Select-Object -ExpandProperty Requirement
        throw "Prerequisite installation did not complete successfully: $($names -join ', ')"
    }
}
else {
    Write-Host 'All machine prerequisites are already installed.' -ForegroundColor Green
    if ($WhatIfPreference) {
        Write-Host '-WhatIf was specified; sign-in, folder creation, skill copy, plugin registration, and metadata synchronization were not performed.'
        return
    }
}

$projectRoot = switch ($script:TargetPlatform) {
    'Scout' { Join-Path $ScoutRoot 'LISA' }
    'Agency' { Join-Path $userProfile '.agency\LISA' }
    default { Join-Path $userProfile '.lisa\LISA' }
}
if (-not [string]::IsNullOrWhiteSpace($ProjectPath)) {
    $projectRoot = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($ProjectPath))
}
$lisaRoot = $null

if ($script:TargetPlatform -eq 'Scout') {
    Write-Section '5. Sign in to Microsoft Scout'
    Confirm-ScoutSignIn

    Write-Section '7. Select and validate the downloaded LISA codebase'
    $codebase = Resolve-Codebase

    Write-Section '8. Confirm LISA skill installation'
    Write-Warning @"
The installer will copy every item from:
  $($codebase.SkillsPath)
to Scout's active skill directory:
  $(Join-Path $ScoutRoot 'm-skills')

Any destination file or top-level folder with the same name will be replaced.
Take a backup before continuing if existing skills or support files must be kept.
The optional scout\m-automations folder and lisa-config.json are validated but are not copied.
"@
    if (-not (Confirm-Exact -Prompt 'Type INSTALL SKILLS to replace matching items and continue' -Expected 'INSTALL SKILLS')) {
        Write-Warning 'LISA skill installation was not approved. Installation has been terminated.'
        return
    }

    Write-Section '9. Install LISA skills'
    $activeSkillsRoot = Install-LisaSkills -SourceSkillsPath $codebase.SkillsPath

    Write-Section '10. Synchronize the Scout skill registry'
    $python = Get-VersionFromCommand -Command 'python' -Arguments @('--version') -Pattern 'Python\s+(?<version>\d+\.\d+\.\d+)'
    if ($null -eq $python -or $python.Version -lt [version]'3.11.0') {
        throw 'Python 3.11 or newer is unavailable after prerequisite installation.'
    }
    $synchronizer = Join-Path $activeSkillsRoot 'sync_skills_metadata.py'
    if (-not (Test-Path -LiteralPath $synchronizer -PathType Leaf)) {
        throw "The installed skill synchronizer is missing: $synchronizer"
    }
    $registryPath = Join-Path $activeSkillsRoot 'skills-metadata.json'
    if ((Test-Path -LiteralPath $registryPath) -and
        ((Get-Item -LiteralPath $registryPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to update a reparse point registry: $registryPath"
    }
    Invoke-NativeCommand -FilePath $python.Path -Arguments (@($synchronizer, '--initialize', '--skills') + $codebase.SkillNames)

    if (-not $SkipProjectSetup) {
        Write-Section 'Prepare the LISA project (preserve existing data)'
        $lisaRoot = Initialize-LisaProject -ProjectRoot $projectRoot
    }
    Write-Section 'Installation complete'
    Write-Host "Target platform: $platformName"
    Write-Host 'Microsoft Scout account: verified'
    Write-Host "LISA project folder: $lisaRoot"
    Write-Host "Installed skills: $($codebase.SkillCount)"
    Write-Host 'Skill registry: synchronized'
    if ($null -ne $lisaRoot) { Write-Host "Review $lisaRoot\lisa-config.json and complete its tenant values before running LISA." }
    Write-Host 'Restart Microsoft Scout so it reloads the installed skill registry.' -ForegroundColor Yellow

    [pscustomobject]@{
        Status               = 'Installed'
        TargetPlatform       = $platformName
        ScoutRoot            = $ScoutRoot
        LisaRoot             = $lisaRoot
        SourceCodebase       = $codebase.Root
        ActiveSkillsRoot     = $activeSkillsRoot
        InstalledSkillCount  = $codebase.SkillCount
        AutomationsAvailable = $codebase.AutomationsAvailable
        SkillRegistrySynced  = $true
    }
}
else {
    Write-Section '5. Register the LISA plugin'
    $registered = Install-LisaPlugin -TargetPlatform $script:TargetPlatform

    if ($registered -and -not $SkipProjectSetup) {
        Write-Section 'Prepare the LISA project (preserve existing data)'
        $lisaRoot = Initialize-LisaProject -ProjectRoot $projectRoot
    }
    Write-Section 'Installation complete'
    Write-Host "Target platform: $platformName"
    Write-Host "LISA project folder: $lisaRoot"
    Write-Host "Plugin source: $PluginRoot"
    Write-Host "Plugin registered: $registered"
    if ($null -ne $lisaRoot) { Write-Host "Review $lisaRoot\lisa-config.json and complete its tenant values before running LISA." -ForegroundColor Yellow }
    Write-Host 'Start a new session from the project folder, then invoke /cad-orchestrator.' -ForegroundColor Yellow

    [pscustomobject]@{
        Status          = if ($registered) { 'Installed' } else { 'PrerequisitesReady' }
        TargetPlatform  = $platformName
        LisaRoot        = $lisaRoot
        PluginRoot      = $PluginRoot
        PluginRegistered = $registered
        SkillsRoot      = $script:SourceSkillsRoot
    }
}