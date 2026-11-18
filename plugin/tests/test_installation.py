from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("pwsh")
# Dot-sources every installer function plus the host catalog without running the installer.
INSTALLER_PRELUDE = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PWD 'Install-LISA-Prerequisites.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw ($parseErrors.Message -join '; ') }
foreach ($definition in $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $false)) { . ([scriptblock]::Create($definition.Extent.Text)) }
foreach ($statement in $ast.EndBlock.Statements | Where-Object {
    $_.Extent.Text -match '^\$(script:HostCatalog|MarketplaceName|PluginName)\s*='
}) { . ([scriptblock]::Create($statement.Extent.Text)) }
"""

PLUGIN_INSTALL_PRELUDE = INSTALLER_PRELUDE + r"""
$DistributionRoot = 'C:\LISA'
$PluginRoot = 'C:\LISA\plugin'
$script:InstalledPackages = [System.Collections.Generic.List[string]]::new()
$script:InstallerCmdlet = [pscustomobject]@{} | Add-Member -MemberType ScriptMethod -Name ShouldProcess -Value { $true } -PassThru
function Write-Warning { param($Message) }
function Confirm-Exact { param($Prompt, $Expected) $true }
$emptyListings = @{
    CopilotCli = '[]'
    ClaudeCode = '[]'
    Codex = '{"marketplaces":[]}'
}
$localListings = @{
    CopilotCli = '[{"name":"lisa","source":"Local: c:\\lisa\\."}]'
    ClaudeCode = '[{"name":"lisa","source":"directory","path":"c:\\lisa\\."}]'
    Codex = '{"marketplaces":[{"name":"lisa","root":"C:\\LISA","marketplaceSource":{"sourceType":"local","source":"c:\\lisa\\."}}]}'
}
"""


@unittest.skipUnless(POWERSHELL, "PowerShell 7 is required")
class InstallationTests(unittest.TestCase):
    def test_repository_runner_propagates_native_failures(self):
        self.run_powershell(r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PWD 'scripts/Test-LisaRepository.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw ($parseErrors.Message -join '; ') }
foreach ($definition in $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-RepositoryCheck'
}, $false)) { . ([scriptblock]::Create($definition.Extent.Text)) }
function Test-NativeCommand { $global:LASTEXITCODE = $script:exitCode }
foreach ($code in @(7, 0)) {
    $script:exitCode = $code
    $rejected = $false
    try { Invoke-RepositoryCheck Test-NativeCommand @('fixture') } catch { $rejected = $true }
    if ($rejected -ne ($code -ne 0)) { throw "Incorrect failure propagation for $code" }
}
""")

    def test_plugin_registration_is_independent_of_project_setup(self):
        self.run_powershell(INSTALLER_PRELUDE + r"""
$entry = $ast.EndBlock.Statements | Where-Object { $_.Extent.Text.StartsWith('if ([Environment]::OSVersion.Platform') } | Select-Object -First 1
$main = [scriptblock]::Create($ast.Extent.Text.Substring($entry.Extent.StartOffset))
$DistributionRoot = $PWD.Path
$PluginRoot = Join-Path $PWD 'plugin'
$RequirementsPath = Join-Path $PWD 'requirements.txt'
$userProfile = Join-Path $PWD 'unused-profile'
$ProjectPath = ''
$WhatIfPreference = $false
function Write-Section { param($Message) }
function Get-PrerequisiteState { [pscustomobject]@{ Installed=$true; Requirement='fixture'; Details='fixture' } }
function Install-LisaPlugin { param($TargetPlatform) $events.Add("register:$TargetPlatform"); return $script:approved }
function Initialize-LisaProject { param($ProjectRoot) $events.Add('project'); return $ProjectRoot }
function Invoke-NativeCommand { throw 'Test must not install anything' }
function Read-Host { param($Prompt) return $script:choice }
foreach ($case in @(
    @{ Target='CopilotCli'; Skip=$true; Approved=$true; Expected='register:CopilotCli' },
    @{ Target='ClaudeCode'; Skip=$false; Approved=$true; Expected='register:ClaudeCode,project' },
    @{ Target='Codex'; Skip=$false; Approved=$false; Expected='register:Codex' }
)) {
    $script:TargetPlatform = $case.Target
    $SkipProjectSetup = $case.Skip
    $script:approved = $case.Approved
    $events = [System.Collections.Generic.List[string]]::new()
    $null = & $main
    if (($events -join ',') -ne $case.Expected) { throw "Incorrect setup ordering: $($events -join ',')" }
}
foreach ($case in @(@{Choice='1'; Target='CopilotCli'}, @{Choice='2'; Target='ClaudeCode'}, @{Choice='3'; Target='Codex'})) {
    $script:choice = $case.Choice
    if ((Select-TargetPlatform) -ne $case.Target) { throw 'Platform prompt returned wrong target' }
}
""")

    def test_each_host_installs_the_plugin_from_the_repository_marketplace(self):
        self.run_powershell(PLUGIN_INSTALL_PRELUDE + r"""
function Invoke-NativeCommand {
    param($FilePath, $Arguments, [switch]$CaptureOutput)
    $calls.Add("$FilePath $($Arguments -join ' ')")
    if ($Arguments[1] -eq 'marketplace') {
        if ($Arguments[2] -eq 'list') {
            if (-not $CaptureOutput) { throw 'Marketplace JSON must be captured' }
            if ($script:registered) { return $localListings[$script:target] }
            return $emptyListings[$script:target]
        }
        if ($Arguments[2] -eq 'add') { $script:registered = $true }
    }
    if ($script:failInstall -and $Arguments[1] -in @('install', 'add')) { throw 'network failure' }
}
$expected = @{
    CopilotCli = 'copilot plugin install lisa@lisa'
    ClaudeCode = 'claude plugin marketplace update lisa|claude plugin install lisa@lisa|claude plugin update lisa@lisa'
    Codex = 'codex plugin add lisa@lisa'
}
foreach ($target in $expected.Keys) {
    $script:target = $target
    $executable = (Get-HostInfo -TargetPlatform $target).Executable
    foreach ($alreadyRegistered in @($false, $true)) {
        $script:registered = $alreadyRegistered
        $script:failInstall = $false
        $calls = [System.Collections.Generic.List[string]]::new()
        if (-not (Install-LisaPlugin -TargetPlatform $target)) { throw "$target registration was not reported" }
        $prefix = "$executable plugin marketplace list --json|"
        if (-not $alreadyRegistered) {
            $prefix += "$executable plugin marketplace add C:\LISA|$executable plugin marketplace list --json|"
        }
        if (($calls -join '|') -ne ($prefix + $expected[$target])) {
            throw "Unexpected $target commands: $($calls -join '|')"
        }
    }
    $script:failInstall = $true
    $calls = [System.Collections.Generic.List[string]]::new()
    $rejected = $false
    try { $null = Install-LisaPlugin -TargetPlatform $target } catch { $rejected = $true }
    if (-not $rejected) { throw "$target hid a plugin installation failure" }
}
""")

    def test_conflicting_local_and_remote_marketplaces_block_all_plugin_writes(self):
        self.run_powershell(PLUGIN_INSTALL_PRELUDE + r"""
function Invoke-NativeCommand {
    param($FilePath, $Arguments, [switch]$CaptureOutput)
    $calls.Add("$FilePath $($Arguments -join ' ')")
    if (($Arguments -join ' ') -ne 'plugin marketplace list --json') { throw 'Unexpected write' }
    return $script:listing
}
$conflicts = @{
    CopilotCli = @(
        '[{"name":"lisa","source":"Local: C:\\LISA-old"}]',
        '[{"name":"lisa","source":"GitHub: rahulsi386/LISA"}]'
    )
    ClaudeCode = @(
        '[{"name":"lisa","source":"directory","path":"C:\\LISA-old"}]',
        '[{"name":"lisa","source":"github","path":"C:\\LISA"}]'
    )
    Codex = @(
        '{"marketplaces":[{"name":"lisa","root":"C:\\LISA-old","marketplaceSource":{"sourceType":"local","source":"C:\\LISA-old"}}]}',
        '{"marketplaces":[{"name":"lisa","root":"C:\\LISA","marketplaceSource":{"sourceType":"git","source":"https://github.com/rahulsi386/LISA.git"}}]}'
    )
}
foreach ($target in $conflicts.Keys) {
    foreach ($listing in $conflicts[$target]) {
        $script:listing = $listing
        $calls = [System.Collections.Generic.List[string]]::new()
        $failure = ''
        try { $null = Install-LisaPlugin -TargetPlatform $target } catch { $failure = $_.Exception.Message }
        if ($failure -notlike '*Registered source:*Expected local source: C:\LISA*') {
            throw "Missing source conflict diagnostic for ${target}: $failure"
        }
        if ($calls.Count -ne 1 -or $script:InstalledPackages.Count -ne 0) { throw 'Conflict caused a write or success record' }
    }
}
""")

    def test_unreadable_marketplace_lists_stop_before_registration(self):
        self.run_powershell(PLUGIN_INSTALL_PRELUDE + r"""
function Invoke-NativeCommand {
    param($FilePath, $Arguments, [switch]$CaptureOutput)
    $calls.Add("$FilePath $($Arguments -join ' ')")
    if ($script:listing -eq 'command failure') { throw 'marketplace inspection failed' }
    return $script:listing
}
foreach ($target in $localListings.Keys) {
    foreach ($listing in @('command failure', 'not JSON', '{}', 'null', '[null]')) {
        $script:listing = $listing
        $calls = [System.Collections.Generic.List[string]]::new()
        $rejected = $false
        try { $null = Install-LisaPlugin -TargetPlatform $target } catch { $rejected = $true }
        if (-not $rejected -or $calls.Count -ne 1 -or $script:InstalledPackages.Count -ne 0) {
            throw "Inspection failure was not closed for $target / $listing"
        }
    }
}
""")

    def test_new_registration_is_verified_and_add_errors_are_not_ignored(self):
        self.run_powershell(PLUGIN_INSTALL_PRELUDE + r"""
function Invoke-NativeCommand {
    param($FilePath, $Arguments, [switch]$CaptureOutput)
    $calls.Add("$FilePath $($Arguments -join ' ')")
    if ($Arguments[2] -eq 'list') {
        $script:reads++
        if ($script:reads -eq 1) { return $emptyListings[$script:target] }
        return $script:afterAdd
    }
    if ($script:addFails) { throw 'Marketplace already registered during inspection' }
}
foreach ($target in $emptyListings.Keys) {
    $script:target = $target
    foreach ($mode in @('missing', 'conflicting', 'add-failure')) {
        $calls = [System.Collections.Generic.List[string]]::new()
        $script:reads = 0
        $script:addFails = $mode -eq 'add-failure'
        $script:afterAdd = $emptyListings[$target]
        if ($mode -eq 'conflicting') {
            $script:afterAdd = $localListings[$target].Replace('lisa\\.', 'lisa-other')
        }
        $rejected = $false
        try { $null = Install-LisaPlugin -TargetPlatform $target } catch { $rejected = $true }
        $expectedCount = if ($script:addFails) { 2 } else { 3 }
        if (-not $rejected -or $calls.Count -ne $expectedCount -or $script:InstalledPackages.Count -ne 0) {
            throw "Unverified registration was accepted for $target"
        }
    }
}
""")

    def test_codex_repo_discovered_marketplace_uses_its_root(self):
        self.run_powershell(PLUGIN_INSTALL_PRELUDE + r"""
function Invoke-NativeCommand {
    param($FilePath, $Arguments, [switch]$CaptureOutput)
    $calls.Add("$FilePath $($Arguments -join ' ')")
    if ($Arguments[1] -eq 'marketplace') {
        return '{"marketplaces":[{"name":"lisa","root":"c:\\lisa\\."}]}'
    }
}
$calls = [System.Collections.Generic.List[string]]::new()
if (-not (Install-LisaPlugin -TargetPlatform Codex)) { throw 'Repo marketplace was not reused' }
if (($calls -join '|') -ne 'codex plugin marketplace list --json|codex plugin add lisa@lisa') {
    throw "Unexpected repo marketplace commands: $($calls -join '|')"
}
""")

    def test_project_setup_preserves_data_and_refuses_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            escaped = temporary.replace("'", "''")
            self.run_powershell("$fixture = '" + escaped + "'\n" + r"""
$ErrorActionPreference = 'Stop'
$DistributionRoot = $PWD.Path
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PWD 'Install-LISA-Prerequisites.ps1'), [ref]$tokens, [ref]$parseErrors)
foreach ($definition in $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Initialize-LisaProject'
}, $false)) { . ([scriptblock]::Create($definition.Extent.Text)) }
$project = Join-Path $fixture 'project with spaces'
$null = Initialize-LisaProject -ProjectRoot $project
$config = Join-Path $project 'lisa-config.json'
if ((Get-FileHash $config).Hash -ne (Get-FileHash ./lisa-config.json).Hash) { throw 'Shared config was not copied' }
Set-Content $config '{"basePath":".","custName":"Do not overwrite"}'
$expected = @{}
foreach ($folder in @('requirements','output','evalData','.lisa')) {
    $directory = Join-Path $project $folder
    $null = New-Item -ItemType Directory $directory -Force
    $file = Join-Path $directory 'existing.txt'
    Set-Content $file "Existing data in $folder"
    $expected[$file] = (Get-FileHash $file).Hash
}
$expected[$config] = (Get-FileHash $config).Hash
$null = Initialize-LisaProject -ProjectRoot $project
foreach ($file in $expected.Keys) {
    if ((Get-FileHash $file).Hash -ne $expected[$file]) { throw "Existing file changed: $file" }
}
$preview = Join-Path $fixture 'whatif'
$null = Initialize-LisaProject -ProjectRoot $preview -WhatIf
if (Test-Path $preview) { throw 'WhatIf created a project' }
$unsafe = Join-Path $fixture 'unsafe'
$null = New-Item -ItemType Directory $unsafe
Set-Content (Join-Path $unsafe 'requirements') 'not a folder'
$rejected = $false
try { $null = Initialize-LisaProject -ProjectRoot $unsafe } catch { $rejected = $true }
if (-not $rejected) { throw 'A file was accepted as a required folder' }
if (Test-Path (Join-Path $unsafe 'output')) { throw 'Unsafe path caused partial project creation' }
if ($IsWindows) {
    $linked = Join-Path $fixture 'linked'
    $outside = Join-Path $fixture 'outside'
    $null = New-Item -ItemType Directory $linked,$outside
    $junction = Join-Path $linked 'output'
    $null = New-Item -ItemType Junction -Path $junction -Target $outside
    try {
        $rejected = $false
        try { $null = Initialize-LisaProject -ProjectRoot $linked } catch { $rejected = $true }
        if (-not $rejected) { throw 'Project output junction was accepted' }
    }
    finally { (Get-Item $junction).Delete() }
}
""")

    def run_powershell(self, source: str) -> str:
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", source],
            cwd=ROOT, capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def test_shared_runtime_rejects_node18_and_missing_npx(self):
        self.run_powershell(r"""
$ErrorActionPreference = 'Stop'
. ./plugin/scripts/Get-LisaRuntimePrerequisites.ps1
function Get-VersionFromCommand {
    param($Command, $Arguments, $Pattern)
    $versions = @{ python='3.13.15'; node=$script:nodeVersion; pwsh='7.6.0' }
    [pscustomobject]@{ Version=[version]$versions[$Command]; Path="mock:$Command" }
}
function Get-Command {
    param($Name, $ErrorAction)
    if ($Name -ne $script:missingCommand) { [pscustomobject]@{ Source="mock:$Name" } }
}
foreach ($case in @(
    @{ Version='18.20.0'; Missing=''; Expected=$false },
    @{ Version='20.0.0'; Missing='npx'; Expected=$false },
    @{ Version='20.0.0'; Missing='npm'; Expected=$false },
    @{ Version='20.0.0'; Missing=''; Expected=$true }
)) {
    $script:nodeVersion = $case.Version
    $script:missingCommand = $case.Missing
    $node = Get-LisaRuntimePrerequisites | Where-Object { $_.Key -eq 'Node' }
    if ($node.Installed -ne $case.Expected) { throw "Unexpected detection: $($case | ConvertTo-Json -Compress)" }
}
""")

    def test_root_installer_uses_shared_runtime_check(self):
        self.run_powershell(r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PWD 'Install-LISA-Prerequisites.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw ($parseErrors.Message -join '; ') }
foreach ($definition in $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-PrerequisiteState'
}, $false)) { . ([scriptblock]::Create($definition.Extent.Text)) }
. ./plugin/scripts/Get-LisaRuntimePrerequisites.ps1
$script:TargetPlatform = 'CopilotCli'
$SourceSkillsRoot = Join-Path $PWD 'plugin/skills'
$RequirementsPath = Join-Path $PWD 'requirements.txt'
function Get-VersionFromCommand { param($Command,$Arguments,$Pattern) [pscustomobject]@{ Version=[version]'20.0.0'; Path="mock:$Command" } }
function Test-PythonLibraries { param($PythonPath) [pscustomobject]@{ Installed=$true; Details='fixture' } }
function Test-RendererPrerequisite { [pscustomobject]@{ Installed=$true; Details='fixture' } }
function Get-HostInfo { param($TargetPlatform) [pscustomobject]@{ Name='Fixture CLI'; Executable='lisa-missing-fixture-cli'; WinGetId='Fixture.Cli'; SignIn='sign in' } }
function Test-ModernPac { $true }
function Get-LisaRuntimePrerequisites { [pscustomobject]@{ Key='Node'; Installed=$false; Details='shared sentinel' } }
$node = Get-PrerequisiteState | Where-Object { $_.Key -eq 'Node' }
if ($node.Details -ne 'shared sentinel' -or $node.Installed) { throw 'Root installer bypassed the shared check' }
""")


if __name__ == "__main__":
    unittest.main()