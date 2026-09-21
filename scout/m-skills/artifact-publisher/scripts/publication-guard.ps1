[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('BuildManifest', 'VerifyRemote')]
    [string]$Mode,

    [string]$ConfigPath,
    [string]$AgentDescription,
    [string]$ManifestPath,
    [string]$RemoteInventoryPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$skillRoot = Split-Path $PSScriptRoot -Parent
$skillsRoot = Split-Path $skillRoot -Parent
$contractValidator = Join-Path $skillsRoot 'validate_artifact_contracts.py'
$contractResult = & python $contractValidator --skill 'artifact-publisher' 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Artifact publisher contract validation failed: $contractResult"
}

function Read-JsonFile {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required JSON file does not exist: $Path"
    }

    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    catch {
        throw "Invalid JSON file '$Path': $($_.Exception.Message)"
    }
}

function Require-Text {
    param(
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string]$Name
    )

    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        throw "Required value is missing or empty: $Name"
    }

    return $text.Trim()
}

function Get-NormalizedPath {
    param([Parameter(Mandatory)][string]$Path)

    return [IO.Path]::GetFullPath($Path).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
}

function Resolve-BaseRelativePath {
    param(
        [Parameter(Mandatory)][string]$BasePath,
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][string]$Name
    )

    if ([IO.Path]::IsPathRooted($RelativePath)) {
        throw "$Name must be relative to lisa-config.json.basePath."
    }
    $resolved = Get-NormalizedPath -Path (Join-Path $BasePath $RelativePath)
    if (-not (Test-PathWithin -Parent $BasePath -Child $resolved)) {
        throw "$Name escapes lisa-config.json.basePath."
    }
    return $resolved
}

function Test-PathWithin {
    param(
        [Parameter(Mandatory)][string]$Parent,
        [Parameter(Mandatory)][string]$Child
    )

    $parentPath = Get-NormalizedPath -Path $Parent
    $childPath = Get-NormalizedPath -Path $Child
    return $childPath.StartsWith(
        $parentPath + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Get-WordCount {
    param([Parameter(Mandatory)][string]$Text)

    return @($Text -split '\s+' | Where-Object { $_ }).Count
}

function Assert-SharePointFolderName {
    param([Parameter(Mandatory)][string]$Name)

    if (
        $Name -in @('.', '..') -or
        $Name.EndsWith(' ') -or
        $Name.EndsWith('.') -or
        $Name -match '[~"#%&*:<>?/\\{|}]'
    ) {
        throw "Agent name cannot be used unchanged as a SharePoint folder name: $Name"
    }
}

function Get-FileManifestEntry {
    param(
        [Parameter(Mandatory)][IO.FileInfo]$File,
        [Parameter(Mandatory)][string]$ArtifactKey,
        [Parameter(Mandatory)][string]$ArtifactCategory,
        [Parameter(Mandatory)][string]$Library,
        [Parameter(Mandatory)][string]$RemotePath,
        [Parameter(Mandatory)][int]$UploadSequence
    )

    return [ordered]@{
        uploadSequence = $UploadSequence
        artifactKey    = $ArtifactKey
        artifactCategory = $ArtifactCategory
        localPath      = $File.FullName
        bytes          = [long]$File.Length
        sha256         = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        library        = $Library
        remotePath     = $RemotePath.Replace('\', '/')
        fileName       = $File.Name
    }
}

function Resolve-ContainedRelativePath {
    param(
        [Parameter(Mandatory)][string]$ParentPath,
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][string]$Name
    )

    if ([IO.Path]::IsPathRooted($RelativePath)) {
        throw "$Name must be relative."
    }
    $resolved = Get-NormalizedPath -Path (Join-Path $ParentPath $RelativePath)
    if (-not (Test-PathWithin -Parent $ParentPath -Child $resolved)) {
        throw "$Name escapes its lifecycle stage folder."
    }
    return $resolved
}

function Test-HiddenRelativePath {
    param([Parameter(Mandatory)][string]$RelativePath)

    $segments = $RelativePath.Replace('\', '/').Split('/')
    return @($segments | Where-Object { $_.StartsWith('.') }).Count -gt 0
}

function Build-ManifestFromLifecycle {
    param(
        [Parameter(Mandatory)]$Config,
        [Parameter(Mandatory)][string]$BasePath,
        [Parameter(Mandatory)][string]$OutputPath
    )

    $customerName = Require-Text -Value $Config.custName -Name 'lisa-config.json.custName'
    $siteUrl = Require-Text -Value $Config.agentRegistry.sharepoint.siteUrl -Name 'agentRegistry.sharepoint.siteUrl'
    $agentLibrary = Require-Text -Value $Config.agentRegistry.sharepoint.deployableAgentLibraryName -Name 'agentRegistry.sharepoint.deployableAgentLibraryName'
    $artifactLibrary = Require-Text -Value $Config.agentRegistry.sharepoint.agentArtifactLibraryName -Name 'agentRegistry.sharepoint.agentArtifactLibraryName'

    $buildRoot = Join-Path $OutputPath 'build'
    $buildManifestPath = Join-Path $buildRoot 'build-manifest.json'
    $handoffPath = Join-Path $buildRoot 'agent-build-handoff.json'
    $buildManifest = Read-JsonFile -Path $buildManifestPath
    $handoff = Read-JsonFile -Path $handoffPath

    if ([string]$buildManifest.stage -cne 'build') {
        throw "Current build manifest has an invalid stage: $($buildManifest.stage)"
    }
    if ([string]$buildManifest.status -notin @('complete', 'blocked')) {
        throw "Current build manifest status is not publishable: $($buildManifest.status)"
    }

    $runId = Require-Text -Value $buildManifest.runId -Name 'build-manifest.json.runId'
    $agentName = Require-Text -Value $handoff.agent.name -Name 'agent-build-handoff.json.agent.name'
    Assert-SharePointFolderName -Name $agentName
    $agentIdText = Require-Text -Value $handoff.agent.agentId -Name 'agent-build-handoff.json.agent.agentId'
    $agentId = [guid]::Empty
    if (-not [guid]::TryParseExact($agentIdText, 'D', [ref]$agentId)) {
        throw "Agent ID is not a canonical UUID: $agentIdText"
    }
    if (
        -not [string]::IsNullOrWhiteSpace([string]$buildManifest.agent.agentId) -and
        [string]$buildManifest.agent.agentId -cne $agentIdText
    ) {
        throw 'Build manifest and handoff identify different agents.'
    }

    $description = $AgentDescription
    if (
        [string]::IsNullOrWhiteSpace($description) -and
        $handoff.agent.PSObject.Properties.Name -contains 'description'
    ) {
        $description = [string]$handoff.agent.description
    }
    if ([string]::IsNullOrWhiteSpace($description)) {
        $specificationPath = Join-Path $buildRoot 'build-specification.json'
        if (Test-Path -LiteralPath $specificationPath -PathType Leaf) {
            $specification = Read-JsonFile -Path $specificationPath
            $description = [string]$specification.agent.description
        }
    }
    $description = Require-Text -Value $description -Name 'agent description'
    $description = ($description -replace '\s+', ' ').Trim()
    $descriptionWordCount = Get-WordCount -Text $description
    if ($descriptionWordCount -gt 80) {
        throw "Agent description exceeds 80 words: $descriptionWordCount"
    }

    $packages = @($handoff.artifacts.packages)
    if ($packages.Count -eq 0) {
        throw 'Agent build handoff contains no deployable package.'
    }
    $primaryPackages = @($packages | Where-Object {
        (
            $_.PSObject.Properties.Name -contains 'primary' -and
            $_.primary -eq $true
        ) -or (
            $_.PSObject.Properties.Name -contains 'deployable' -and
            $_.deployable -eq $true
        )
    })
    $selectedPackages = if ($primaryPackages.Count -gt 0) { $primaryPackages } else { $packages }
    if ($selectedPackages.Count -ne 1) {
        throw 'Agent build handoff must identify exactly one deployable package; mark one package primary when multiple packages exist.'
    }
    $packageRecord = $selectedPackages[0]
    $packageRelativePath = Require-Text -Value $packageRecord.relativePath -Name 'agent-build-handoff.json.artifacts.packages[].relativePath'
    $deployablePath = Resolve-ContainedRelativePath `
        -ParentPath $buildRoot `
        -RelativePath $packageRelativePath `
        -Name 'deployable package'
    if (-not (Test-Path -LiteralPath $deployablePath -PathType Leaf)) {
        throw "Deployable package does not exist: $deployablePath"
    }
    $zip = Get-Item -LiteralPath $deployablePath
    if (-not $zip.Extension.Equals('.zip', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Deployable artifact is not a ZIP file: $deployablePath"
    }
    if ($zip.Length -le 0) {
        throw "Deployable ZIP is empty: $deployablePath"
    }
    if (
        $null -ne $packageRecord.bytes -and
        [long]$packageRecord.bytes -ne [long]$zip.Length
    ) {
        throw 'Deployable ZIP byte size does not match the builder handoff.'
    }
    $zipHash = (Get-FileHash -LiteralPath $zip.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if (
        -not [string]::IsNullOrWhiteSpace([string]$packageRecord.sha256) -and
        $zipHash -ne ([string]$packageRecord.sha256).ToLowerInvariant()
    ) {
        throw 'Deployable ZIP hash does not match the builder handoff.'
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zip.FullName)
    try {
        if ($archive.Entries.Count -eq 0) {
            throw "Deployable ZIP contains no entries: $deployablePath"
        }
    }
    finally {
        $archive.Dispose()
    }

    $candidateByPath = [Collections.Generic.Dictionary[string, object]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    function Add-LifecycleFile {
        param(
            [Parameter(Mandatory)][string]$Path,
            [Parameter(Mandatory)][string]$ArtifactCategory,
            [string]$ExpectedSha256,
            $ExpectedBytes
        )

        $resolved = Get-NormalizedPath -Path $Path
        if (-not (Test-PathWithin -Parent $OutputPath -Child $resolved)) {
            throw "Lifecycle artifact escapes the output folder: $resolved"
        }
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            throw "Lifecycle artifact does not exist: $resolved"
        }
        if ($resolved -eq $zip.FullName) {
            return
        }
        $relative = $resolved.Substring($OutputPath.Length + 1).Replace('\', '/')
        if (
            $relative.StartsWith('publication/', [StringComparison]::OrdinalIgnoreCase) -or
            (Test-HiddenRelativePath -RelativePath $relative) -or
            $relative -match '(?i)(browser[-_ ]?profile|browser[-_ ]?storage|cookies?|credentials?|tokens?|secrets?)' -or
            $relative -match '\.(tmp|temp|partial)$'
        ) {
            return
        }
        $file = Get-Item -LiteralPath $resolved
        if ($null -ne $ExpectedBytes -and [string]$ExpectedBytes -ne '') {
            if ([long]$ExpectedBytes -ne [long]$file.Length) {
                throw "Lifecycle artifact byte size does not match its manifest: $relative"
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256)) {
            $actualHash = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualHash -ne $ExpectedSha256.ToLowerInvariant()) {
                throw "Lifecycle artifact hash does not match its manifest: $relative"
            }
        }
        $candidateByPath[$resolved] = [ordered]@{
            file = $file
            relativePath = $relative
            artifactCategory = $ArtifactCategory
        }
    }

    function Add-LifecycleManifest {
        param(
            [Parameter(Mandatory)][string]$StageName,
            [Parameter(Mandatory)][string]$ManifestFile
        )

        $stageRoot = Join-Path $OutputPath $StageName
        $manifestPath = Join-Path $stageRoot $ManifestFile
        $manifest = Read-JsonFile -Path $manifestPath
        if ([string]$manifest.stage -cne $StageName) {
            throw "Lifecycle manifest '$ManifestFile' has an invalid stage."
        }
        Add-LifecycleFile -Path $manifestPath -ArtifactCategory 'declaredArtifact'
        foreach ($artifact in @($manifest.artifacts)) {
            if ([string]$artifact.kind -eq 'directory') {
                continue
            }
            $artifactPath = Resolve-ContainedRelativePath `
                -ParentPath $stageRoot `
                -RelativePath (Require-Text -Value $artifact.relativePath -Name "$ManifestFile.artifacts[].relativePath") `
                -Name "$ManifestFile artifact"
            $category = if ($StageName -eq 'evaluation') {
                if (([string]$artifact.relativePath).Replace('\', '/').StartsWith('evidence/', [StringComparison]::OrdinalIgnoreCase)) {
                    'evaluationEvidence'
                }
                else {
                    'evaluationArtifact'
                }
            }
            else {
                'declaredArtifact'
            }
            Add-LifecycleFile `
                -Path $artifactPath `
                -ArtifactCategory $category `
                -ExpectedSha256 ([string]$artifact.sha256) `
                -ExpectedBytes $artifact.bytes
        }
    }

    $analysisRoot = Join-Path $OutputPath 'analysis'
    $latestAnalysisMarkdown = Get-ChildItem -LiteralPath $analysisRoot -File |
        Where-Object Name -Match '^requirement-analysis_[0-9]{8}_[0-9]{6}(?:_[0-9]{3})?\.md$' |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($null -eq $latestAnalysisMarkdown) {
        throw 'No current requirement-analysis Markdown was found.'
    }
    $analysisStem = $latestAnalysisMarkdown.BaseName
    foreach ($file in @(Get-ChildItem -LiteralPath $analysisRoot -File |
        Where-Object {
            $_.BaseName -eq $analysisStem -or
            $_.BaseName -eq "$analysisStem-manifest"
        } |
        Sort-Object Name)) {
        Add-LifecycleFile -Path $file.FullName -ArtifactCategory 'declaredArtifact'
    }

    $classificationRoot = Join-Path $OutputPath 'classification'
    $latestClassificationMarkdown = Get-ChildItem -LiteralPath $classificationRoot -File |
        Where-Object Name -Match '^complexity-classification_[0-9]{8}_[0-9]{6}(?:_[0-9]{3})?\.md$' |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($null -eq $latestClassificationMarkdown) {
        throw 'No current complexity-classification Markdown was found.'
    }
    $classificationStem = $latestClassificationMarkdown.BaseName
    foreach ($file in @(Get-ChildItem -LiteralPath $classificationRoot -File |
        Where-Object { $_.BaseName -eq $classificationStem } |
        Sort-Object Name)) {
        Add-LifecycleFile -Path $file.FullName -ArtifactCategory 'declaredArtifact'
    }

    $designRoot = Join-Path $OutputPath 'design'
    $designPointerPath = Join-Path $designRoot 'current-design.json'
    $designPointer = Read-JsonFile -Path $designPointerPath
    if ([string]$designPointer.validation -cne 'passed') {
        throw 'Current design pointer is not validated.'
    }
    Add-LifecycleFile -Path $designPointerPath -ArtifactCategory 'declaredArtifact'
    $designArtifactDirectory = Resolve-BaseRelativePath `
        -BasePath $BasePath `
        -RelativePath (Require-Text -Value $designPointer.artifact_directory -Name 'current-design.json.artifact_directory') `
        -Name 'current-design.json.artifact_directory'
    if (-not (Test-PathWithin -Parent $designRoot -Child $designArtifactDirectory)) {
        throw 'Current design artifact directory must remain beneath output/design.'
    }
    foreach ($property in $designPointer.artifacts.PSObject.Properties) {
        $designFile = Join-Path $designArtifactDirectory $property.Name
        Add-LifecycleFile `
            -Path $designFile `
            -ArtifactCategory 'declaredArtifact' `
            -ExpectedSha256 ([string]$property.Value)
    }

    Add-LifecycleManifest -StageName 'build' -ManifestFile 'build-manifest.json'
    Add-LifecycleManifest -StageName 'evaluation' -ManifestFile 'evaluation-manifest.json'
    Add-LifecycleManifest -StageName 'optimization' -ManifestFile 'optimization-manifest.json'

    $artifactOutputRoot = Join-Path $OutputPath 'artifacts'
    foreach ($file in @(Get-ChildItem -LiteralPath $artifactOutputRoot -File | Sort-Object Name)) {
        Add-LifecycleFile -Path $file.FullName -ArtifactCategory 'declaredArtifact'
    }

    $sitePath = ([uri]$siteUrl).AbsolutePath.TrimEnd('/')
    $agentRemotePath = "$sitePath/$agentLibrary/$($zip.Name)"
    $artifactLibraryRoot = "$sitePath/$artifactLibrary"
    $artifactRoot = "$artifactLibraryRoot/$agentName"
    $entries = [Collections.Generic.List[object]]::new()
    $entries.Add((
        Get-FileManifestEntry `
            -File $zip `
            -ArtifactKey 'deployableAgent' `
            -ArtifactCategory 'deployablePackage' `
            -Library $agentLibrary `
            -RemotePath $agentRemotePath `
            -UploadSequence 1
    ))

    $uploadSequence = 2
    foreach ($candidate in @($candidateByPath.Values | Sort-Object { [string]$_.relativePath })) {
        $entries.Add((
            Get-FileManifestEntry `
                -File $candidate.file `
                -ArtifactKey "$($candidate.artifactCategory):$($candidate.relativePath)" `
                -ArtifactCategory $candidate.artifactCategory `
                -Library $artifactLibrary `
                -RemotePath "$artifactRoot/$($candidate.relativePath)" `
                -UploadSequence $uploadSequence
        ))
        $uploadSequence++
    }

    $duplicates = $entries |
        Group-Object { "$($_.library)|$($_.remotePath)".ToLowerInvariant() } |
        Where-Object Count -gt 1
    if ($duplicates) {
        throw 'Manifest contains duplicate destination paths.'
    }
    $categoryCounts = [ordered]@{}
    foreach ($group in $entries | Group-Object { [string]$_['artifactCategory'] } | Sort-Object Name) {
        $categoryCounts[$group.Name] = $group.Count
    }

    $publicationRoot = Join-Path $OutputPath 'publication'
    $manifest = [ordered]@{
        schemaVersion = '3.0'
        runId = $runId
        runFolder = $OutputPath
        discoveryMode = 'lifecycle-manifests'
        siteUrl = $siteUrl
        destinations = [ordered]@{
            agentLibrary = $agentLibrary
            artifactLibrary = $artifactLibrary
            agentLibraryRoot = "$sitePath/$agentLibrary"
            artifactLibraryRoot = $artifactLibraryRoot
            artifactAgentFolder = $artifactRoot
        }
        agentLibraryMetadata = [ordered]@{
            agentId = $agentId.ToString('D').ToLowerInvariant()
            agentName = $agentName
            agentDescription = $description
            agentDescriptionWordCount = $descriptionWordCount
            customerName = $customerName
        }
        expected = [ordered]@{
            totalCount = $entries.Count
            agentLibraryCount = 1
            artifactLibraryCount = $candidateByPath.Count
            categoryCounts = $categoryCounts
        }
        entries = @($entries)
    }

    New-Item -ItemType Directory -Path $publicationRoot -Force | Out-Null
    $publicationManifest = Join-Path $publicationRoot 'publication-manifest.json'
    $temporaryManifest = "$publicationManifest.tmp"
    $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporaryManifest -Encoding utf8
    Move-Item -LiteralPath $temporaryManifest -Destination $publicationManifest -Force
    return $manifest
}

function Build-Manifest {
    if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
        throw 'BuildManifest requires -ConfigPath.'
    }

    $config = Read-JsonFile -Path $ConfigPath
    $lisaResolver = Join-Path $skillsRoot 'lisa_path_resolver.py'
    $resolvedJson = & python $lisaResolver --config $ConfigPath 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "lisa-config.json path resolution failed: $resolvedJson"
    }
    $resolvedPaths = $resolvedJson | ConvertFrom-Json
    $basePath = Get-NormalizedPath -Path ([string]$resolvedPaths.basePath)
    $outputPath = Get-NormalizedPath -Path ([string]$resolvedPaths.output)
    return Build-ManifestFromLifecycle `
        -Config $config `
        -BasePath $basePath `
        -OutputPath $outputPath
}

function Verify-Remote {
    if ([string]::IsNullOrWhiteSpace($ManifestPath) -or [string]::IsNullOrWhiteSpace($RemoteInventoryPath)) {
        throw 'VerifyRemote requires -ManifestPath and -RemoteInventoryPath.'
    }

    $manifest = Read-JsonFile -Path $ManifestPath
    $inventory = Read-JsonFile -Path $RemoteInventoryPath
    $expected = @($manifest.entries)
    $remote = @($inventory.items)
    $executionOrder = @($inventory.executionOrder)
    $uploadOrderValid = (
        $expected.Count -gt 0 -and
        $expected[0].artifactKey -eq 'deployableAgent' -and
        [int]$expected[0].uploadSequence -eq 1 -and
        $executionOrder.Count -eq $expected.Count -and
        [string]$executionOrder[0] -ceq [string]$expected[0].remotePath
    )

    $remoteByKey = @{}
    $duplicates = [Collections.Generic.List[string]]::new()
    foreach ($item in $remote) {
        $key = "$($item.library)|$($item.remotePath)".ToLowerInvariant()
        if ($remoteByKey.ContainsKey($key)) {
            $duplicates.Add($key)
        }
        else {
            $remoteByKey[$key] = $item
        }
    }

    $missing = [Collections.Generic.List[string]]::new()
    $sizeMismatch = [Collections.Generic.List[string]]::new()
    $hashMismatch = [Collections.Generic.List[string]]::new()
    $artifactAgentIdMismatch = [Collections.Generic.List[string]]::new()
    $agentLibraryMetadata = $inventory.agentLibraryMetadata
    $agentLibraryAgentId = [string]$agentLibraryMetadata.agentId
    foreach ($entry in $expected) {
        $key = "$($entry.library)|$($entry.remotePath)".ToLowerInvariant()
        if (-not $remoteByKey.ContainsKey($key)) {
            $missing.Add($entry.remotePath)
            continue
        }

        $item = $remoteByKey[$key]
        $comparableHashMatches = (
            -not [string]::IsNullOrWhiteSpace([string]$item.sha256) -and
            ([string]$item.sha256).ToLowerInvariant() -eq ([string]$entry.sha256).ToLowerInvariant()
        )
        $isSharePointPromotedHtml = (
            ([string]$entry.fileName).EndsWith('.html', [StringComparison]::OrdinalIgnoreCase) -and
            $comparableHashMatches
        )
        if (
            [long]$item.bytes -ne [long]$entry.bytes -and
            -not $isSharePointPromotedHtml
        ) {
            $sizeMismatch.Add($entry.remotePath)
        }
        if (
            -not [string]::IsNullOrWhiteSpace([string]$item.sha256) -and
            ([string]$item.sha256).ToLowerInvariant() -ne ([string]$entry.sha256).ToLowerInvariant()
        ) {
            $hashMismatch.Add($entry.remotePath)
        }
        if (
            $entry.library -eq $manifest.destinations.artifactLibrary -and
            [string]$item.agentId -cne $agentLibraryAgentId
        ) {
            $artifactAgentIdMismatch.Add($entry.remotePath)
        }
    }

    $artifactLibrary = [string]$manifest.destinations.artifactLibrary
    $artifactFolder = ([string]$manifest.destinations.artifactAgentFolder).TrimEnd('/')
    $artifactRoot = $artifactFolder + '/'
    $artifactLibraryRoot = ([string]$manifest.destinations.artifactLibraryRoot).TrimEnd('/')
    $artifactFolderAtRoot = (
        $artifactFolder.StartsWith(
            $artifactLibraryRoot + '/',
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        $artifactFolder.Substring($artifactLibraryRoot.Length + 1) -notmatch '/' -and
        $artifactFolder.Substring($artifactLibraryRoot.Length + 1) -ceq [string]$manifest.agentLibraryMetadata.agentName
    )
    $expectedArtifactKeys = @{}
    foreach ($entry in $expected | Where-Object library -eq $artifactLibrary) {
        $expectedArtifactKeys[([string]$entry.remotePath).ToLowerInvariant()] = $true
    }
    $extraArtifacts = @(
        $remote |
            Where-Object {
                $_.library -eq $artifactLibrary -and
                ([string]$_.remotePath).StartsWith($artifactRoot, [StringComparison]::OrdinalIgnoreCase) -and
                -not $expectedArtifactKeys.ContainsKey(([string]$_.remotePath).ToLowerInvariant())
            } |
            ForEach-Object remotePath
    )

    $zipEntry = @($expected | Where-Object library -eq $manifest.destinations.agentLibrary)
    $zipAtRoot = (
        $zipEntry.Count -eq 1 -and
        ([string]$zipEntry[0].remotePath).StartsWith(
            ([string]$manifest.destinations.agentLibraryRoot).TrimEnd('/') + '/',
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        ([string]$zipEntry[0].remotePath).Substring(
            ([string]$manifest.destinations.agentLibraryRoot).TrimEnd('/').Length + 1
        ) -notmatch '/'
    )

    $metadata = $agentLibraryMetadata
    $metadataMatches = (
        [string]$metadata.agentId -ceq [string]$manifest.agentLibraryMetadata.agentId -and
        [string]$metadata.agentName -ceq [string]$manifest.agentLibraryMetadata.agentName -and
        [string]$metadata.agentDescription -ceq [string]$manifest.agentLibraryMetadata.agentDescription -and
        [string]$metadata.customerName -ceq [string]$manifest.agentLibraryMetadata.customerName
    )
    $artifactFolderMetadata = $inventory.artifactFolderMetadata
    $artifactFolderAgentIdMatches = (
        [string]$artifactFolderMetadata.agentId -ceq $agentLibraryAgentId
    )

    $passed = (
        $uploadOrderValid -and
        $duplicates.Count -eq 0 -and
        $missing.Count -eq 0 -and
        $sizeMismatch.Count -eq 0 -and
        $hashMismatch.Count -eq 0 -and
        $artifactAgentIdMismatch.Count -eq 0 -and
        $extraArtifacts.Count -eq 0 -and
        $zipAtRoot -and
        $metadataMatches -and
        $artifactFolderAtRoot -and
        $artifactFolderAgentIdMatches
    )

    return [ordered]@{
        passed = $passed
        expectedCount = $expected.Count
        verifiedCount = $expected.Count - $missing.Count - $sizeMismatch.Count - $hashMismatch.Count
        missing = @($missing)
        sizeMismatch = @($sizeMismatch)
        hashMismatch = @($hashMismatch)
        duplicateRemotePaths = @($duplicates)
        extraArtifactFiles = @($extraArtifacts)
        uploadOrderValid = $uploadOrderValid
        deployableZipAtLibraryRoot = $zipAtRoot
        agentLibraryMetadataVerified = $metadataMatches
        artifactAgentFolderAtLibraryRoot = $artifactFolderAtRoot
        artifactFolderAgentIdVerified = $artifactFolderAgentIdMatches
        artifactItemAgentIdMismatches = @($artifactAgentIdMismatch)
    }
}

try {
    $result = if ($Mode -eq 'BuildManifest') {
        Build-Manifest
    }
    else {
        Verify-Remote
    }

    $result | ConvertTo-Json -Depth 12
    if ($Mode -eq 'VerifyRemote' -and -not $result.passed) {
        exit 2
    }
}
catch {
    [ordered]@{
        passed = $false
        error = $_.Exception.Message
    } | ConvertTo-Json -Depth 6
    exit 1
}
