$LisaRuntimeVersions = @{
    Python = [version]'3.11.0'
    Node = [version]'20.0.0'
    PowerShell = [version]'7.0.0'
}
$LisaNodeCommands = @('npm', 'npx')

function Get-VersionFromCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Pattern
    )

    $resolved = Get-Command $Command -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $resolved) { return $null }
    try {
        $output = (& $resolved.Source @Arguments 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $output -notmatch $Pattern) { return $null }
        return [pscustomobject]@{
            Path = $resolved.Source
            Version = [version]$Matches.version
            Output = $output
        }
    }
    catch { return $null }
}

function Get-LisaRuntimePrerequisites {
    $specifications = @(
        @{ Key = 'Python'; Command = 'python'; Pattern = 'Python\s+(?<version>\d+\.\d+\.\d+)'; Requirement = 'Python 3.11+'; Package = 'Python.Python.3.13' },
        @{ Key = 'Node'; Command = 'node'; Pattern = 'v(?<version>\d+\.\d+\.\d+)'; Requirement = 'Node.js 20+, npm and npx'; Package = 'OpenJS.NodeJS.LTS' },
        @{ Key = 'PowerShell'; Command = 'pwsh'; Pattern = 'PowerShell\s+(?<version>\d+\.\d+\.\d+)'; Requirement = 'PowerShell 7+'; Package = 'Microsoft.PowerShell' }
    )
    foreach ($specification in $specifications) {
        $detected = Get-VersionFromCommand -Command $specification.Command -Arguments @('--version') -Pattern $specification.Pattern
        $installed = $null -ne $detected -and $detected.Version -ge $LisaRuntimeVersions[$specification.Key]
        $details = if ($null -ne $detected) { "$($detected.Version) at $($detected.Path)" } else { 'Not found.' }
        if ($specification.Key -eq 'Node') {
            $missing = @($LisaNodeCommands | Where-Object { $null -eq (Get-Command $_ -ErrorAction SilentlyContinue) })
            $installed = $installed -and $missing.Count -eq 0
            if ($missing.Count -gt 0) { $details += "; missing: $($missing -join ', ')" }
        }
        [pscustomobject]@{
            Key = $specification.Key
            Requirement = $specification.Requirement
            Installed = $installed
            Details = $details
            InstallAction = "WinGet package $($specification.Package)."
        }
    }
}