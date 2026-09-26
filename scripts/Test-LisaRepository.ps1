#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('Plugin', 'Scout', 'Gepa')]
    [string]$Suite = 'Plugin'
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent $PSScriptRoot

function Invoke-RepositoryCheck {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    Write-Host "> $Executable $($Arguments -join ' ')"
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Repository check failed with exit code ${LASTEXITCODE}: $Executable $($Arguments -join ' ')"
    }
}

Push-Location $RepositoryRoot
try {
    $SkillsRoot = Join-Path $RepositoryRoot 'github-copilot/skills'
    if ($Suite -eq 'Plugin') {
        Invoke-RepositoryCheck python @('-m', 'unittest', 'discover', '-s', 'github-copilot/tests', '-p', 'test_*.py', '-q')
        $TestFiles = @(Get-ChildItem -LiteralPath $SkillsRoot -File -Filter 'test*.py')
        foreach ($Skill in Get-ChildItem -LiteralPath $SkillsRoot -Directory) {
            $Tests = Join-Path $Skill.FullName 'tests'
            if (Test-Path -LiteralPath $Tests -PathType Container) {
                $TestFiles += Get-ChildItem -LiteralPath $Tests -File -Filter 'test*.py'
            }
        }
        foreach ($TestFile in $TestFiles | Sort-Object FullName) {
            Invoke-RepositoryCheck python @($TestFile.FullName, '-q')
        }
        Invoke-RepositoryCheck node @('github-copilot/skills/artifact-publisher/tests/test_fast_publisher.js')
        Invoke-RepositoryCheck npm @('--prefix', 'github-copilot/skills/solution-designer/renderer', 'test')
    }
    elseif ($Suite -eq 'Scout') {
        foreach ($Test in @('test_sync_skills_metadata.py', 'test_workflow_checkpoint.py', 'test_evidence_pipeline_contracts.py')) {
            Invoke-RepositoryCheck python @((Join-Path 'scout/m-skills' $Test), '-q')
        }
    }
    else {
        Invoke-RepositoryCheck python @('-c', 'from importlib.metadata import version; assert version("gepa") == "0.1.4", "Install requirements-gepa.txt before the engine check"')
        Invoke-RepositoryCheck python @('github-copilot/skills/agent-optimizer/tests/test_gepa.py', '-v')
    }
    Write-Host "$Suite checks passed. No live tenant behavior was tested."
}
finally {
    Pop-Location
}