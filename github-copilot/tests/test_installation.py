from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("pwsh")


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
        self.run_powershell(r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PWD 'Install-LISA-Prerequisites.ps1'), [ref]$tokens, [ref]$parseErrors)
foreach ($definition in $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $false)) { . ([scriptblock]::Create($definition.Extent.Text)) }
$entry = $ast.EndBlock.Statements | Where-Object { $_.Extent.Text.StartsWith('if ([Environment]::OSVersion.Platform') } | Select-Object -First 1
$main = [scriptblock]::Create($ast.Extent.Text.Substring($entry.Extent.StartOffset))
$DistributionRoot = $PWD.Path
$PluginRoot = Join-Path $PWD 'github-copilot'
$ScoutSkillsRoot = Join-Path $PWD 'scout/m-skills'
$RequirementsPath = Join-Path $PWD 'requirements.txt'
$userProfile = Join-Path $PWD 'unused-profile'
$ScoutRoot = Join-Path $userProfile '.scout'
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
    @{ Target='Agency'; Skip=$false; Approved=$true; Expected='register:Agency,project' },
    @{ Target='CopilotCli'; Skip=$false; Approved=$false; Expected='register:CopilotCli' }
)) {
    $script:TargetPlatform = $case.Target
    $SkipProjectSetup = $case.Skip
    $script:approved = $case.Approved
    $events = [System.Collections.Generic.List[string]]::new()
    $null = & $main
    if (($events -join ',') -ne $case.Expected) { throw "Incorrect setup ordering: $($events -join ',')" }
}
foreach ($case in @(@{Choice='1'; Target='Scout'}, @{Choice='2'; Target='CopilotCli'}, @{Choice='3'; Target='Agency'})) {
    $script:choice = $case.Choice
    if ((Select-TargetPlatform) -ne $case.Target) { throw 'Platform prompt returned wrong target' }
}
""")

    def test_scout_copy_preserves_installed_registry(self):
        with tempfile.TemporaryDirectory() as temporary:
            escaped = temporary.replace("'", "''")
            self.run_powershell("$fixture = '" + escaped + "'\n" + r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PWD 'Install-LISA-Prerequisites.ps1'), [ref]$tokens, [ref]$parseErrors)
foreach ($definition in $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Install-LisaSkills'
}, $false)) { . ([scriptblock]::Create($definition.Extent.Text)) }
$ScoutRoot = Join-Path $fixture 'scout-profile'
$source = Join-Path $fixture 'source'
$destination = Join-Path $ScoutRoot 'm-skills'
$null = New-Item -ItemType Directory $source,$destination
Set-Content (Join-Path $source 'skills-metadata.json') '[{"name":"source-must-not-replace-target"}]'
Set-Content (Join-Path $source 'new-skill.txt') 'new implementation'
$registry = Join-Path $destination 'skills-metadata.json'
$unrelated = Join-Path $destination 'unrelated.txt'
Set-Content $registry '[{"name":"existing","enabled":false}]'
Set-Content $unrelated 'keep'
$registryHash = (Get-FileHash $registry).Hash
$unrelatedHash = (Get-FileHash $unrelated).Hash
$null = Install-LisaSkills -SourceSkillsPath $source
if ((Get-FileHash $registry).Hash -ne $registryHash) { throw 'Registry was replaced during skill copy' }
if ((Get-FileHash $unrelated).Hash -ne $unrelatedHash) { throw 'Unrelated file changed' }
if (-not (Test-Path (Join-Path $destination 'new-skill.txt'))) { throw 'Skill was not copied' }
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

    def test_scout_source_does_not_require_generated_registry(self):
        self.run_powershell(r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PWD 'Install-LISA-Prerequisites.ps1'), [ref]$tokens, [ref]$parseErrors)
foreach ($definition in $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Resolve-Codebase'
}, $false)) { . ([scriptblock]::Create($definition.Extent.Text)) }
function Read-Host { param($Prompt) $PWD.Path }
$codebase = Resolve-Codebase
if ($codebase.SkillNames.Count -ne 10) { throw 'Expected ten Scout skill directories' }
if ($codebase.SkillsPath -ne (Join-Path $PWD 'scout/m-skills')) { throw 'Wrong source skills root' }
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
. ./github-copilot/scripts/Get-LisaRuntimePrerequisites.ps1
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
. ./github-copilot/scripts/Get-LisaRuntimePrerequisites.ps1
$script:TargetPlatform = 'CopilotCli'
$SourceSkillsRoot = Join-Path $PWD 'github-copilot/skills'
$RequirementsPath = Join-Path $PWD 'requirements.txt'
function Get-VersionFromCommand { param($Command,$Arguments,$Pattern) [pscustomobject]@{ Version=[version]'20.0.0'; Path="mock:$Command" } }
function Test-PythonLibraries { param($PythonPath) [pscustomobject]@{ Installed=$true; Details='fixture' } }
function Test-RendererPrerequisite { [pscustomobject]@{ Installed=$true; Details='fixture' } }
function Get-ScoutExecutable { $null }
function Test-ModernPac { $true }
function Get-LisaRuntimePrerequisites { [pscustomobject]@{ Key='Node'; Installed=$false; Details='shared sentinel' } }
$node = Get-PrerequisiteState | Where-Object { $_.Key -eq 'Node' }
if ($node.Details -ne 'shared sentinel' -or $node.Installed) { throw 'Root installer bypassed the shared check' }
""")


if __name__ == "__main__":
    unittest.main()