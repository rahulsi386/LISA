[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ModelPath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$IconManifestPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'resources\icon-manifest.json'),
    [string]$ReferenceManifestPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'resources\reference-manifest.json'),
    [ValidateSet('Balanced', 'Spacious', 'Wide')][string]$LayoutProfile = 'Balanced'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Invariant = [System.Globalization.CultureInfo]::InvariantCulture
$Utf8 = New-Object System.Text.UTF8Encoding($false)

$OutputDirectory = [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory))
if ((Split-Path $OutputDirectory -Leaf) -cne 'design') {
    throw "OutputDirectory must be the Design child of tempOutputPath: $OutputDirectory"
}

function Escape-Xml([AllowNull()][string]$Value) {
    if ($null -eq $Value) { return '' }
    return [System.Security.SecurityElement]::Escape($Value)
}

function Format-Number([double]$Value) {
    return $Value.ToString('0.##', $Invariant)
}

function Get-WrappedLines([string]$Text, [int]$MaxCharacters, [int]$MaxLines) {
    if ([string]::IsNullOrWhiteSpace($Text)) { return @() }
    $words = @($Text -split '\s+')
    $lines = New-Object System.Collections.Generic.List[string]
    $current = ''
    $truncated = $false
    for ($wordIndex = 0; $wordIndex -lt $words.Count; $wordIndex++) {
        $word = $words[$wordIndex]
        $candidate = if ($current) { "$current $word" } else { $word }
        if ($candidate.Length -le $MaxCharacters) {
            $current = $candidate
            continue
        }

        if ($current) {
            $lines.Add($current)
            if ($lines.Count -ge $MaxLines) {
                $truncated = $true
                $current = ''
                break
            }
        }
        $current = $word
    }
    if ($current -and $lines.Count -lt $MaxLines) { $lines.Add($current) }
    if (($lines -join ' ').Length -lt $Text.Length) { $truncated = $true }
    if ($truncated -and $lines.Count -gt 0) {
        $last = $lines[$lines.Count - 1]
        $lines[$lines.Count - 1] = $last.Substring(0, [Math]::Min($last.Length, $MaxCharacters - 3)).TrimEnd() + '...'
    }
    return @($lines)
}

function Get-ComponentMembers($Component) {
    if ($Component.PSObject.Properties.Name -notcontains 'members') { return @() }
    return @($Component.members | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-MemberLineCount($Component, [int]$MaxCharacters) {
    $count = 0
    foreach ($member in @(Get-ComponentMembers $Component)) {
        $count += @(Get-WrappedLines $member ([Math]::Max(18, $MaxCharacters - 2)) 32).Count
    }
    return $count
}

function Get-OrderedDataItems($Items, $Relationships, $ComponentById) {
    $itemList = @($Items)
    if ($itemList.Count -lt 2) { return $itemList }
    $ids = @($itemList | ForEach-Object { [string]$_.id })
    $idSet = @{}
    $originalIndex = @{}
    for ($index = 0; $index -lt $ids.Count; $index++) {
        $idSet[$ids[$index]] = $true
        $originalIndex[$ids[$index]] = $index
    }
    $edges = @(
        $Relationships | Where-Object {
            $idSet.ContainsKey([string]$_.from) -and
            $idSet.ContainsKey([string]$_.to) -and
            [string]$_.from -ne [string]$_.to
        }
    )
    $rank = @{}
    foreach ($id in $ids) { $rank[$id] = 0 }
    for ($pass = 0; $pass -lt $ids.Count; $pass++) {
        $changed = $false
        foreach ($edge in $edges) {
            $source = [string]$edge.from
            $target = [string]$edge.to
            $candidate = [Math]::Min(4, [int]$rank[$source] + 1)
            if ($candidate -gt [int]$rank[$target]) {
                $rank[$target] = $candidate
                $changed = $true
            }
        }
        if (-not $changed) { break }
    }
    $orderedIds = New-Object System.Collections.Generic.List[string]
    $maxRank = ($rank.Values | Measure-Object -Maximum).Maximum
    for ($currentRank = 0; $currentRank -le $maxRank; $currentRank++) {
        $rankIds = @($ids | Where-Object { [int]$rank[$_] -eq $currentRank })
        if ($currentRank -eq 0) {
            $rankIds = @(
                $rankIds | Sort-Object `
                    @{ Expression = {
                        $source = $_
                        $targets = @(
                            $edges |
                                Where-Object { [string]$_.from -eq $source } |
                                ForEach-Object { [string]$_.to }
                        )
                        if ($targets.Count -eq 0) { return 1000 + [int]$originalIndex[$source] }
                        return ($targets | ForEach-Object { [int]$originalIndex[$_] } | Measure-Object -Average).Average
                    } },
                    @{ Expression = { [int]$originalIndex[$_] } }
            )
        } else {
            $rankIds = @(
                $rankIds | Sort-Object `
                    @{ Expression = {
                        $target = $_
                        $predecessors = @(
                            $edges |
                                Where-Object { [string]$_.to -eq $target } |
                                ForEach-Object { [string]$_.from } |
                                Where-Object { $orderedIds.Contains($_) }
                        )
                        if ($predecessors.Count -eq 0) { return 1000 + [int]$originalIndex[$target] }
                        return ($predecessors | ForEach-Object { $orderedIds.IndexOf($_) } | Measure-Object -Average).Average
                    } },
                    @{ Expression = { [int]$originalIndex[$_] } }
            )
        }
        foreach ($id in $rankIds) { $orderedIds.Add($id) }
    }
    return @($orderedIds | ForEach-Object { $ComponentById[$_] })
}

if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) { throw "Model not found: $ModelPath" }
if (-not (Test-Path -LiteralPath $IconManifestPath -PathType Leaf)) { throw "Icon manifest not found: $IconManifestPath" }
if (-not (Test-Path -LiteralPath $ReferenceManifestPath -PathType Leaf)) { throw "Reference manifest not found: $ReferenceManifestPath" }

$model = Get-Content -LiteralPath $ModelPath -Raw | ConvertFrom-Json
$iconManifest = Get-Content -LiteralPath $IconManifestPath -Raw | ConvertFrom-Json
$referenceManifest = Get-Content -LiteralPath $ReferenceManifestPath -Raw | ConvertFrom-Json
$components = @($model.components)
$relationships = @($model.relationships)
$sequence = @($model.sequence)

if ([string]$model.scenarioSlug -notmatch '^[A-Za-z0-9_]+$') { throw 'scenarioSlug must contain only letters, digits, and underscores.' }
if ($components.Count -lt 2 -or $components.Count -gt 30) { throw 'components must contain 2-30 entries.' }
if ($relationships.Count -gt 60) { throw 'relationships cannot exceed 60 entries.' }
if ($sequence.Count -lt 1 -or $sequence.Count -gt 30) { throw 'sequence must contain 1-30 entries.' }

$componentById = @{}
foreach ($component in $components) {
    $id = [string]$component.id
    if ($id -notmatch '^[A-Za-z][A-Za-z0-9_-]*$') { throw "Invalid component id: $id" }
    if ($componentById.ContainsKey($id)) { throw "Duplicate component id: $id" }
    $componentById[$id] = $component
}
for ($edgeIndex = 0; $edgeIndex -lt $relationships.Count; $edgeIndex++) {
    $edge = $relationships[$edgeIndex]
    if (-not $componentById.ContainsKey([string]$edge.from) -or -not $componentById.ContainsKey([string]$edge.to)) {
        throw "Relationship references an unknown component: $($edge.from) -> $($edge.to)"
    }
    if ([string]$edge.from -eq [string]$edge.to) { throw "Architecture relationships cannot be self-referential: $($edge.from)" }
    if (([string]$edge.label).Length -gt 42) { throw "Architecture relationship labels cannot exceed 42 characters: $($edge.label)" }
}
foreach ($message in $sequence) {
    if (-not $componentById.ContainsKey([string]$message.from) -or -not $componentById.ContainsKey([string]$message.to)) {
        throw "Sequence message references an unknown component: $($message.from) -> $($message.to)"
    }
    if (([string]$message.label).Length -gt 56) { throw "Sequence message labels cannot exceed 56 characters: $($message.label)" }
    if ($message.PSObject.Properties.Name -contains 'fragment' -and ([string]$message.fragment).Length -gt 40) {
        throw "Sequence fragment labels cannot exceed 40 characters: $($message.fragment)"
    }
}

$iconRoot = Split-Path $IconManifestPath -Parent
$iconByKey = @{}
foreach ($entry in @($iconManifest.icons)) { $iconByKey[[string]$entry.key] = $entry }
$iconDataCache = @{}
$usedIcons = @{}

function Resolve-Icon([string]$RequestedKey) {
    $key = $RequestedKey
    if (-not $iconByKey.ContainsKey($key)) {
        $normalized = $key.ToLowerInvariant()
        $alias = $iconManifest.aliases.PSObject.Properties | Where-Object { $_.Name.ToLowerInvariant() -eq $normalized } | Select-Object -First 1
        if ($alias) { $key = [string]$alias.Value }
    }
    if (-not $iconByKey.ContainsKey($key)) { $key = 'generic-component' }
    $entry = $iconByKey[$key]
    $path = Join-Path $iconRoot ([string]$entry.file)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Cached icon is missing: $path" }
    if (-not $iconDataCache.ContainsKey($key)) {
        $base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($path))
        $iconDataCache[$key] = "data:image/svg+xml;base64,$base64"
    }
    return [pscustomobject]@{
        Key = $key
        DataUri = $iconDataCache[$key]
        File = [string]$entry.file
        Source = [string]$entry.sourcePack
        Verified = [bool]$entry.official
    }
}

foreach ($component in $components) {
    $resolved = Resolve-Icon ([string]$component.iconKey)
    $usedIcons[[string]$component.id] = $resolved
}

$referenceKeys = @($model.referenceKeys | ForEach-Object { [string]$_ })
$referenceByKey = @{}
foreach ($source in @($referenceManifest.sources)) { $referenceByKey[[string]$source.key] = $source }
$selectedReferences = New-Object System.Collections.Generic.List[object]
foreach ($key in $referenceKeys) {
    if (-not $referenceByKey.ContainsKey($key)) { throw "Unknown reference key: $key" }
    $selectedReferences.Add($referenceByKey[$key])
}
if ($referenceKeys -notcontains 'architecture-diagrams') { throw 'referenceKeys must include architecture-diagrams.' }

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$slug = [string]$model.scenarioSlug
$saPath = Join-Path $OutputDirectory "SA_$slug.svg"
$sdPath = Join-Path $OutputDirectory "SD_$slug.svg"
$manifestPath = Join-Path $OutputDirectory 'diagram-manifest.json'

$layerOrder = @('users', 'channels', 'agent-platform', 'data-integration', 'governance', 'monitoring')
$layerTitles = @{
    'users' = 'Users and requesters'
    'channels' = 'Conversation channels'
    'agent-platform' = 'Agent platform'
    'data-integration' = 'Data, automation, and integration'
    'governance' = 'Identity, security, and governance (cross-cutting)'
    'monitoring' = 'Monitoring and lifecycle (cross-cutting)'
}
if (@($components | Where-Object { [string]$_.iconKey -eq 'copilot-studio' }).Count -gt 0) {
    $layerTitles['agent-platform'] = 'Agent platform | Microsoft Copilot Studio'
}
$layerColors = @{
    'users' = '#0ea5e9'
    'channels' = '#2563eb'
    'agent-platform' = '#7c3aed'
    'data-integration' = '#0891b2'
    'governance' = '#d97706'
    'monitoring' = '#059669'
}

$profileSettings = switch ($LayoutProfile) {
    'Spacious' { [pscustomobject]@{ CanvasWidth = 1920; ContainerWidth = 1660; ContainerX = 130; DataColumns = 4 } }
    'Wide' { [pscustomobject]@{ CanvasWidth = 2240; ContainerWidth = 1960; ContainerX = 140; DataColumns = 5 } }
    default { [pscustomobject]@{ CanvasWidth = 1600; ContainerWidth = 1380; ContainerX = 110; DataColumns = 4 } }
}
$canvasWidth = $profileSettings.CanvasWidth
$outerMargin = 40
$containerWidth = $profileSettings.ContainerWidth
$containerX = $profileSettings.ContainerX
$contentTop = 132
$containerGap = 40
$geometry = @{}
$containerGeometry = @{}
$currentY = $contentTop
$primaryAgent = @($components | Where-Object { [string]$_.layer -eq 'agent-platform' -and [string]$_.kind -eq 'agent' } | Select-Object -First 1)
$primaryAgentId = if ($primaryAgent.Count -gt 0) { [string]$primaryAgent[0].id } else { '' }
$sameLayerEdgeCounts = @{}
foreach ($layer in $layerOrder) { $sameLayerEdgeCounts[$layer] = 0 }
for ($edgeIndex = 0; $edgeIndex -lt $relationships.Count; $edgeIndex++) {
    $edge = $relationships[$edgeIndex]
    $fromLayer = [string]$componentById[[string]$edge.from].layer
    $toLayer = [string]$componentById[[string]$edge.to].layer
    $usesPrimaryAgent = $fromLayer -eq 'agent-platform' -and (@([string]$edge.from, [string]$edge.to) -contains $primaryAgentId)
    if ($fromLayer -eq $toLayer -and -not $usesPrimaryAgent) { $sameLayerEdgeCounts[$fromLayer]++ }
}

foreach ($layer in $layerOrder) {
    $items = @($components | Where-Object { [string]$_.layer -eq $layer })
    if ($layer -eq 'data-integration') {
        $items = @(Get-OrderedDataItems $items $relationships $componentById)
    }
    if ($items.Count -eq 0) { continue }
    $connectorLaneHeight = if ($sameLayerEdgeCounts[$layer] -gt 0) { 12 } else { 0 }
    if ($layer -eq 'agent-platform' -and $primaryAgentId) {
        $satellites = @($items | Where-Object { [string]$_.id -ne $primaryAgentId })
        $satelliteColumns = [Math]::Min(3, [Math]::Max(1, $satellites.Count))
        $satelliteRows = if ($satellites.Count -gt 0) { [Math]::Ceiling($satellites.Count / [double]$satelliteColumns) } else { 0 }
        $heroWidth = 560
        $heroComponent = $componentById[$primaryAgentId]
        $heroTitleLineCount = @(Get-WrappedLines ([string]$heroComponent.name) 46 10).Count
        $heroDescriptionLineCount = @(Get-WrappedLines ([string]$heroComponent.description) 58 32).Count
        $heroMemberLines = Get-MemberLineCount $heroComponent 58
        $heroBadgeBottom = 52 + ($heroTitleLineCount * 20) + 28
        $heroDescriptionBottom = 92 + ($heroDescriptionLineCount * 16)
        $heroMemberHeading = [Math]::Max($heroBadgeBottom, $heroDescriptionBottom) + 18
        $heroHeight = [Math]::Max(
            160,
            $heroMemberHeading + $(if ($heroMemberLines -gt 0) { 24 + ($heroMemberLines * 14) } else { 20 })
        )
        $satelliteHeight = 118
        $cardGap = 28
        $cardWidth = 400
        if ($satellites.Count -gt 0) {
            $cardWidth = [Math]::Min(400, [Math]::Floor((($containerWidth - 96) - (($satelliteColumns - 1) * $cardGap)) / $satelliteColumns))
            $satelliteMemberLines = 0
            foreach ($satellite in $satellites) {
                $memberLines = Get-MemberLineCount $satellite ([Math]::Max(24, [Math]::Floor(($cardWidth - 100) / 7)))
                if ($memberLines -gt $satelliteMemberLines) { $satelliteMemberLines = $memberLines }
            }
            if ($satelliteMemberLines -gt 0) { $satelliteHeight += 20 + ($satelliteMemberLines * 14) }
        }
        $containerHeight = 86 + $heroHeight + $(if ($satelliteRows -gt 0) { 86 + ($satelliteRows * $satelliteHeight) + (($satelliteRows - 1) * 24) } else { 24 }) + 24 + $connectorLaneHeight
        $containerGeometry[$layer] = [pscustomobject]@{ X = $containerX; Y = $currentY; Width = $containerWidth; Height = $containerHeight; Layout = 'hero' }
        $geometry[$primaryAgentId] = [pscustomobject]@{
            X = $containerX + (($containerWidth - $heroWidth) / 2); Y = $currentY + 68; Width = $heroWidth; Height = $heroHeight; Parent = $layer; Role = 'hero'
        }
        if ($satellites.Count -gt 0) {
            $rowWidth = ($satelliteColumns * $cardWidth) + (($satelliteColumns - 1) * $cardGap)
            $innerX = $containerX + (($containerWidth - $rowWidth) / 2)
            for ($index = 0; $index -lt $satellites.Count; $index++) {
                $row = [Math]::Floor($index / $satelliteColumns)
                $column = $index % $satelliteColumns
                $x = $innerX + ($column * ($cardWidth + $cardGap))
                $y = $currentY + 68 + $heroHeight + 86 + ($row * ($satelliteHeight + 24))
                $geometry[[string]$satellites[$index].id] = [pscustomobject]@{
                    X = $x; Y = $y; Width = $cardWidth; Height = $satelliteHeight; Parent = $layer; Role = 'satellite'
                }
            }
        }
    } else {
        $isBand = @('governance', 'monitoring') -contains $layer
        $columns = [Math]::Min(
            $(if ($isBand) { 3 } elseif ($layer -eq 'data-integration') { $profileSettings.DataColumns } else { 4 }),
            $items.Count
        )
        $rows = [Math]::Ceiling($items.Count / [double]$columns)
        $baseCardHeight = if ($isBand) { 92 } else { 112 }
        $maxCardWidth = switch ($layer) { 'users' { 460 } 'channels' { 460 } 'data-integration' { 520 } 'governance' { 540 } 'monitoring' { 760 } default { 420 } }
        $cardGap = 32
        $rowGap = if ($layer -eq 'data-integration') { 88 } else { 24 }
        $availableWidth = $containerWidth - 96
        $cardWidth = [Math]::Min($maxCardWidth, [Math]::Floor(($availableWidth - (($columns - 1) * $cardGap)) / $columns))
        $maxRequiredHeight = $baseCardHeight
        foreach ($item in $items) {
            $titleMax = [Math]::Max(20, [Math]::Floor(($cardWidth - 182) / 7))
            $descriptionMax = [Math]::Max(24, [Math]::Floor(($cardWidth - 100) / 7))
            $titleLineCount = @(Get-WrappedLines ([string]$item.name) $titleMax 10).Count
            $descriptionLineCount = @(Get-WrappedLines ([string]$item.description) $descriptionMax 32).Count
            $descriptionStart = if ($titleLineCount -gt 1) { 75 } else { 62 }
            $requiredHeight = $descriptionStart + ($descriptionLineCount * 15) + 20
            $itemMembers = @(Get-ComponentMembers $item)
            if ($itemMembers.Count -gt 0) {
                $memberLineCount = 0
                $memberMax = [Math]::Max(18, $descriptionMax - 2)
                foreach ($member in $itemMembers) {
                    $memberLineCount += @(Get-WrappedLines $member $memberMax 32).Count
                }
                $requiredHeight += 26 + ($memberLineCount * 14)
            }
            if ($requiredHeight -gt $maxRequiredHeight) { $maxRequiredHeight = $requiredHeight }
        }
        $cardHeight = $maxRequiredHeight
        $rowWidth = ($columns * $cardWidth) + (($columns - 1) * $cardGap)
        $innerX = $containerX + (($containerWidth - $rowWidth) / 2)
        $containerHeight = 76 + ($rows * $cardHeight) + (($rows - 1) * $rowGap) + 26 + $connectorLaneHeight
        $containerGeometry[$layer] = [pscustomobject]@{ X = $containerX; Y = $currentY; Width = $containerWidth; Height = $containerHeight; Layout = if ($isBand) { 'band' } else { 'standard' } }
        for ($index = 0; $index -lt $items.Count; $index++) {
            $row = [Math]::Floor($index / $columns)
            $column = $index % $columns
            $x = $innerX + ($column * ($cardWidth + $cardGap))
            $y = $currentY + 62 + ($row * ($cardHeight + $rowGap))
            $geometry[[string]$items[$index].id] = [pscustomobject]@{
                X = $x; Y = $y; Width = $cardWidth; Height = $cardHeight; Parent = $layer; Role = if ($isBand) { 'compact' } else { 'standard' }
            }
        }
    }
    $currentY += $containerHeight + $containerGap
}

$legendHeight = 92
$canvasHeight = $currentY + $legendHeight + $outerMargin
$layoutEngine = Join-Path (Split-Path $PSScriptRoot -Parent) 'resources\layout-engine\SolutionDesigner.LayoutEngine.exe'
if (-not (Test-Path -LiteralPath $layoutEngine -PathType Leaf)) {
    throw "Packaged MSAGL layout engine was not found: $layoutEngine"
}
$layoutNodes = @(
    foreach ($component in $components) {
        $box = $geometry[[string]$component.id]
        [ordered]@{
            id = [string]$component.id
            x = [double]$box.X
            y = [double]$box.Y
            width = [double]$box.Width
            height = [double]$box.Height
        }
    }
)
$layoutEdges = New-Object System.Collections.Generic.List[object]
$layoutEdgeIds = @{}
for ($edgeIndex = 0; $edgeIndex -lt $relationships.Count; $edgeIndex++) {
    $edge = $relationships[$edgeIndex]
    $sourceLayer = [string]$componentById[[string]$edge.from].layer
    $targetLayer = [string]$componentById[[string]$edge.to].layer
    if (
        @('governance', 'monitoring') -contains $sourceLayer -or
        @('governance', 'monitoring') -contains $targetLayer
    ) {
        continue
    }
    $routeId = 'edge-' + $edgeIndex.ToString('D3', $Invariant)
    $layoutEdgeIds[$edgeIndex] = $routeId
    $label = [string]$edge.label
    $layoutEdges.Add([ordered]@{
        id = $routeId
        sourceId = [string]$edge.from
        targetId = [string]$edge.to
        label = $label
        labelWidth = [Math]::Min(270, [Math]::Max(88, ($label.Length * 7) + 18))
        labelHeight = 24
    })
}
$labelExclusions = @(
    [ordered]@{ x = 0; y = 0; width = $canvasWidth; height = $contentTop - 6 }
    [ordered]@{ x = 0; y = $canvasHeight - $legendHeight - 8; width = $canvasWidth; height = $legendHeight + 8 }
    foreach ($layer in $layerOrder) {
        if (-not $containerGeometry.ContainsKey($layer)) { continue }
        $container = $containerGeometry[$layer]
        [ordered]@{
            x = [double]$container.X
            y = [double]$container.Y
            width = [double]$container.Width
            height = 52
        }
    }
)
$layoutInputPath = Join-Path $OutputDirectory '.msagl-input.json'
$layoutOutputPath = Join-Path $OutputDirectory '.msagl-output.json'
$layoutInput = [ordered]@{
    canvasWidth = $canvasWidth
    canvasHeight = $canvasHeight
    routePadding = 8
    nodes = $layoutNodes
    edges = @($layoutEdges | ForEach-Object { $_ })
    labelExclusions = $labelExclusions
}
[IO.File]::WriteAllText($layoutInputPath, ($layoutInput | ConvertTo-Json -Depth 8), $Utf8)
try {
    & $layoutEngine $layoutInputPath $layoutOutputPath
    $layoutExitCode = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $layoutOutputPath -PathType Leaf)) {
        throw 'MSAGL did not produce a routing result.'
    }
    $layoutResult = Get-Content -LiteralPath $layoutOutputPath -Raw | ConvertFrom-Json
    if ($layoutExitCode -ne 0 -or @($layoutResult.issues).Count -gt 0) {
        throw "MSAGL routing failed: $(@($layoutResult.issues) -join '; ')"
    }
    $optimizedRoutes = @{}
    foreach ($route in @($layoutResult.routes)) {
        $optimizedRoutes[[string]$route.id] = $route
    }
    $routeBridges = @{}
    $routedEdges = @($layoutResult.routes)
    for ($routeIndex = 0; $routeIndex -lt $routedEdges.Count; $routeIndex++) {
        $first = $routedEdges[$routeIndex]
        for ($otherIndex = $routeIndex + 1; $otherIndex -lt $routedEdges.Count; $otherIndex++) {
            $second = $routedEdges[$otherIndex]
            if (
                [string]$first.sourceId -eq [string]$second.sourceId -or
                [string]$first.sourceId -eq [string]$second.targetId -or
                [string]$first.targetId -eq [string]$second.sourceId -or
                [string]$first.targetId -eq [string]$second.targetId
            ) {
                continue
            }
            for ($firstSegment = 0; $firstSegment -lt (@($first.points).Count - 1); $firstSegment++) {
                $a1 = @($first.points)[$firstSegment]
                $a2 = @($first.points)[$firstSegment + 1]
                $aVertical = [Math]::Abs([double]$a1.x - [double]$a2.x) -lt 0.01
                for ($secondSegment = 0; $secondSegment -lt (@($second.points).Count - 1); $secondSegment++) {
                    $b1 = @($second.points)[$secondSegment]
                    $b2 = @($second.points)[$secondSegment + 1]
                    $bVertical = [Math]::Abs([double]$b1.x - [double]$b2.x) -lt 0.01
                    if ($aVertical -eq $bVertical) { continue }
                    $vertical1 = if ($aVertical) { $a1 } else { $b1 }
                    $vertical2 = if ($aVertical) { $a2 } else { $b2 }
                    $horizontal1 = if ($aVertical) { $b1 } else { $a1 }
                    $horizontal2 = if ($aVertical) { $b2 } else { $a2 }
                    $crossX = [double]$vertical1.x
                    $crossY = [double]$horizontal1.y
                    if (
                        $crossX -gt [Math]::Min([double]$horizontal1.x, [double]$horizontal2.x) -and
                        $crossX -lt [Math]::Max([double]$horizontal1.x, [double]$horizontal2.x) -and
                        $crossY -gt [Math]::Min([double]$vertical1.y, [double]$vertical2.y) -and
                        $crossY -lt [Math]::Max([double]$vertical1.y, [double]$vertical2.y)
                    ) {
                        $bridgeRoute = $second
                        $orientation = if ($bVertical) { 'vertical' } else { 'horizontal' }
                        if (-not $routeBridges.ContainsKey([string]$bridgeRoute.id)) {
                            $routeBridges[[string]$bridgeRoute.id] = New-Object System.Collections.Generic.List[object]
                        }
                        $routeBridges[[string]$bridgeRoute.id].Add([pscustomobject]@{
                            X = $crossX
                            Y = $crossY
                            Orientation = $orientation
                        })
                    }
                }
            }
        }
    }
} finally {
    if ($env:SOLUTION_DESIGNER_KEEP_LAYOUT_DEBUG -ne '1') {
        Remove-Item -LiteralPath $layoutInputPath, $layoutOutputPath -Force -ErrorAction SilentlyContinue
    }
}
$sa = New-Object System.Collections.Generic.List[string]
$sa.Add('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 ' + $canvasWidth + ' ' + $canvasHeight + '" role="img" aria-labelledby="title desc">')
$sa.Add('<title id="title">' + (Escape-Xml ([string]$model.title)) + ' - Solution Architecture</title>')
$sa.Add('<desc id="desc">' + (Escape-Xml ([string]$model.summary)) + '</desc>')
$sa.Add('<defs>')
$sa.Add('<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#081426"/><stop offset="1" stop-color="#172554"/></linearGradient>')
$sa.Add('<linearGradient id="agent-panel" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#17152f"/><stop offset="1" stop-color="#111c3d"/></linearGradient>')
$sa.Add('<linearGradient id="hero-card" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#eef2ff"/></linearGradient>')
$sa.Add('<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#020617" flood-opacity=".28"/></filter>')
$sa.Add('<marker id="arrow-blue" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#60a5fa"/></marker>')
$sa.Add('<marker id="arrow-amber" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#f59e0b"/></marker>')
$sa.Add('<marker id="arrow-red" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#ef4444"/></marker>')
$sa.Add('<marker id="arrow-gray" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"/></marker>')
$sa.Add('</defs>')
$sa.Add('<rect width="' + $canvasWidth + '" height="' + $canvasHeight + '" fill="url(#bg)"/>')
$sa.Add('<circle cx="' + ($canvasWidth - 210) + '" cy="80" r="210" fill="#7c3aed" fill-opacity=".08"/><circle cx="' + ($canvasWidth - 80) + '" cy="20" r="130" fill="#38bdf8" fill-opacity=".07"/>')
$sa.Add('<text x="40" y="50" fill="#f8fafc" font-family="Inter,Arial,sans-serif" font-size="28" font-weight="700">' + (Escape-Xml ([string]$model.title)) + '</text>')
$sa.Add('<text x="40" y="80" fill="#bfdbfe" font-family="Inter,Arial,sans-serif" font-size="15">Solution Architecture | ' + (Escape-Xml ([string]$model.complexity)) + ' complexity | Native ' + (Escape-Xml ([string]$model.coverage.nativeBuildPercent)) + '% | PoC ' + (Escape-Xml ([string]$model.coverage.pocDemonstrationPercent)) + '%</text>')
$sa.Add('<rect x="' + ($canvasWidth - 220) + '" y="34" width="164" height="38" rx="19" fill="#7c3aed" fill-opacity=".18" stroke="#a78bfa"/><text x="' + ($canvasWidth - 138) + '" y="58" text-anchor="middle" fill="#ddd6fe" font-family="Inter,Arial,sans-serif" font-size="12" font-weight="700">EVIDENCE-GROUNDED</text>')
$summaryLines = @(Get-WrappedLines ([string]$model.summary) ([Math]::Floor(($canvasWidth - 80) / 10)) 8)
for ($i = 0; $i -lt $summaryLines.Count; $i++) {
    $sa.Add('<text x="40" y="' + (100 + ($i * 17)) + '" fill="#cbd5e1" font-family="Inter,Arial,sans-serif" font-size="12">' + (Escape-Xml $summaryLines[$i]) + '</text>')
}

foreach ($layer in $layerOrder) {
    if (-not $containerGeometry.ContainsKey($layer)) { continue }
    $g = $containerGeometry[$layer]
    $containerFill = if ($g.Layout -eq 'hero') { 'url(#agent-panel)' } elseif ($g.Layout -eq 'band') { '#0b1f2a' } else { '#0f172a' }
    $containerStrokeWidth = if ($g.Layout -eq 'hero') { 3 } else { 2 }
    $sa.Add('<g data-kind="container" data-id="' + $layer + '" data-x="' + $g.X + '" data-y="' + $g.Y + '" data-width="' + $g.Width + '" data-height="' + $g.Height + '" data-header-height="52">')
    $sa.Add('<rect x="' + $g.X + '" y="' + $g.Y + '" width="' + $g.Width + '" height="' + $g.Height + '" rx="20" fill="' + $containerFill + '" fill-opacity=".94" stroke="' + $layerColors[$layer] + '" stroke-width="' + $containerStrokeWidth + '"/>')
    $sa.Add('<rect x="' + ($g.X + 1) + '" y="' + ($g.Y + 1) + '" width="10" height="' + ($g.Height - 2) + '" rx="5" fill="' + $layerColors[$layer] + '"/>')
    $sa.Add('<text x="' + ($g.X + 28) + '" y="' + ($g.Y + 34) + '" fill="#f8fafc" font-family="Inter,Arial,sans-serif" font-size="17" font-weight="700">' + (Escape-Xml $layerTitles[$layer]) + '</text>')
    if ($g.Layout -eq 'hero') {
        $sa.Add('<text x="' + ($g.X + $g.Width - 28) + '" y="' + ($g.Y + 34) + '" text-anchor="end" fill="#c4b5fd" font-family="Inter,Arial,sans-serif" font-size="11">Instructions | orchestration | knowledge | tools | human handoff</text>')
    } elseif ($g.Layout -eq 'band') {
        $sa.Add('<text x="' + ($g.X + $g.Width - 28) + '" y="' + ($g.Y + 34) + '" text-anchor="end" fill="#94a3b8" font-family="Inter,Arial,sans-serif" font-size="11">Applies across every solution layer</text>')
    }
    $sa.Add('</g>')
}

$sameLayerLaneIndex = @{}
foreach ($layer in $layerOrder) { $sameLayerLaneIndex[$layer] = 0 }
$layerIndex = @{}
for ($i = 0; $i -lt $layerOrder.Count; $i++) { $layerIndex[$layerOrder[$i]] = $i }
$leftGutterCount = 0
$rightGutterCount = 0
$crossLayerLaneIndex = @{}
$crossLayerLaneCount = @{}
foreach ($candidateEdge in $relationships) {
    $candidateFromLayer = [string]$componentById[[string]$candidateEdge.from].layer
    $candidateToLayer = [string]$componentById[[string]$candidateEdge.to].layer
    if ($candidateFromLayer -eq $candidateToLayer -or (@('governance', 'monitoring') -contains $candidateFromLayer) -or (@('governance', 'monitoring') -contains $candidateToLayer)) { continue }
    $candidateBlockedByHero = (([string]$candidateEdge.from -eq $primaryAgentId -and $layerIndex[$candidateToLayer] -gt $layerIndex[$candidateFromLayer]) -or
        ([string]$candidateEdge.to -eq $primaryAgentId -and $layerIndex[$candidateFromLayer] -gt $layerIndex[$candidateToLayer]))
    if ([Math]::Abs($layerIndex[$candidateFromLayer] - $layerIndex[$candidateToLayer]) -eq 1 -and -not $candidateBlockedByHero) {
        $pair = @($candidateFromLayer, $candidateToLayer) | Sort-Object
        $pairKey = $pair -join '|'
        if (-not $crossLayerLaneCount.ContainsKey($pairKey)) { $crossLayerLaneCount[$pairKey] = 0; $crossLayerLaneIndex[$pairKey] = 0 }
        $crossLayerLaneCount[$pairKey]++
    }
}
for ($edgeIndex = 0; $edgeIndex -lt $relationships.Count; $edgeIndex++) {
    $edge = $relationships[$edgeIndex]
    $from = $geometry[[string]$edge.from]
    $to = $geometry[[string]$edge.to]
    $crossCuttingLayers = @('governance', 'monitoring')
    if ($from.Parent -ne $to.Parent -and (($crossCuttingLayers -contains $from.Parent) -or ($crossCuttingLayers -contains $to.Parent))) {
        continue
    }
    $label = [string]$edge.label
    $implementationMode = [string]$edge.implementationMode
    $isDashed = @('response', 'optional', 'tbd') -contains [string]$edge.style -or $implementationMode -ne 'real'
    $color = switch ($implementationMode) {
        'blocked' { '#ef4444' }
        'deferred' { '#94a3b8' }
        'manual' { '#f59e0b' }
        'simulated' { '#22d3ee' }
        default { if (@('optional', 'tbd') -contains [string]$edge.style) { '#f59e0b' } else { '#60a5fa' } }
    }
    $marker = switch ($implementationMode) {
        'blocked' { 'arrow-red' }
        'deferred' { 'arrow-gray' }
        'manual' { 'arrow-amber' }
        default { if ($color -eq '#f59e0b') { 'arrow-amber' } else { 'arrow-blue' } }
    }
    $rotatedLabel = $false
    $labelAngle = 0
    $routePoints = New-Object System.Collections.Generic.List[object]
    $primaryBlockedCrossLayer = (($from.Parent -ne $to.Parent) -and
        (([string]$edge.from -eq $primaryAgentId -and $layerIndex[$to.Parent] -gt $layerIndex[$from.Parent]) -or
        ([string]$edge.to -eq $primaryAgentId -and $layerIndex[$from.Parent] -gt $layerIndex[$to.Parent])))
    $primaryAgentRelationship = $from.Parent -eq 'agent-platform' -and $to.Parent -eq 'agent-platform' -and (@([string]$edge.from, [string]$edge.to) -contains $primaryAgentId)
    $optimizedRoute = $null
    if ($layoutEdgeIds.ContainsKey($edgeIndex)) {
        $optimizedRoute = $optimizedRoutes[[string]$layoutEdgeIds[$edgeIndex]]
    }
    if ($null -ne $optimizedRoute) {
        foreach ($point in @($optimizedRoute.points)) {
            $routePoints.Add(@([double]$point.x, [double]$point.y))
        }
        $pathParts = New-Object System.Collections.Generic.List[string]
        for ($pointIndex = 0; $pointIndex -lt $routePoints.Count; $pointIndex++) {
            $point = $routePoints[$pointIndex]
            if ($pointIndex -eq 0) {
                $pathParts.Add('M ' + (Format-Number ([double]$point[0])) + ' ' + (Format-Number ([double]$point[1])))
            } else {
                $previous = $routePoints[$pointIndex - 1]
                if ([Math]::Abs([double]$point[0] - [double]$previous[0]) -lt 0.01) {
                    $pathParts.Add('V ' + (Format-Number ([double]$point[1])))
                } elseif ([Math]::Abs([double]$point[1] - [double]$previous[1]) -lt 0.01) {
                    $pathParts.Add('H ' + (Format-Number ([double]$point[0])))
                } else {
                    throw "MSAGL returned a non-orthogonal segment for $([string]$edge.from) -> $([string]$edge.to)."
                }
            }
        }
        $path = $pathParts -join ' '
        $midX = [double]$optimizedRoute.labelX
        $midY = [double]$optimizedRoute.labelY
    } elseif ($primaryAgentRelationship) {
        $lane = $sameLayerLaneIndex[$from.Parent]
        $sameLayerLaneIndex[$from.Parent]++
        if ([string]$edge.from -eq $primaryAgentId) {
            $sx = [Math]::Max($from.X + 70, [Math]::Min($to.X + ($to.Width / 2), $from.X + $from.Width - 70))
            $sy = $from.Y + $from.Height
            $tx = $to.X + ($to.Width / 2)
            $ty = $to.Y
        } else {
            $sx = $from.X + ($from.Width / 2)
            $sy = $from.Y
            $tx = [Math]::Max($to.X + 70, [Math]::Min($from.X + ($from.Width / 2), $to.X + $to.Width - 70))
            $ty = $to.Y + $to.Height
        }
        $midY = [Math]::Min($sy, $ty) + 22 + ($lane * 20)
        $midX = ($sx + $tx) / 2
        $path = 'M ' + (Format-Number $sx) + ' ' + (Format-Number $sy) + ' V ' + (Format-Number $midY) + ' H ' + (Format-Number $tx) + ' V ' + (Format-Number $ty)
        $routePoints.Add(@($sx, $sy)); $routePoints.Add(@($sx, $midY)); $routePoints.Add(@($tx, $midY)); $routePoints.Add(@($tx, $ty))
    } elseif ($from.Parent -eq $to.Parent) {
        $lane = $sameLayerLaneIndex[$from.Parent]
        $sameLayerLaneIndex[$from.Parent]++
        $sx = $from.X + ($from.Width / 2)
        $sy = $from.Y + $from.Height
        $tx = $to.X + ($to.Width / 2)
        $ty = $to.Y + $to.Height
        $sourceLaneY = $sy + 18 + (($lane % 3) * 24)
        $targetLaneY = $ty + 18 + (($lane % 3) * 24)
        $averageX = ($sx + $tx) / 2
        if ($averageX -lt ($canvasWidth / 2)) {
            $gutterX = 90 - (($leftGutterCount % 5) * 14)
            $leftGutterCount++
        } else {
            $gutterX = 1510 + (($rightGutterCount % 4) * 14)
            $rightGutterCount++
        }
        $midX = ($sx + $gutterX) / 2
        $midY = $sourceLaneY
        $path = 'M ' + (Format-Number $sx) + ' ' + (Format-Number $sy) + ' V ' + (Format-Number $sourceLaneY) + ' H ' + (Format-Number $gutterX) + ' V ' + (Format-Number $targetLaneY) + ' H ' + (Format-Number $tx) + ' V ' + (Format-Number $ty)
        $routePoints.Add(@($sx, $sy)); $routePoints.Add(@($sx, $sourceLaneY)); $routePoints.Add(@($gutterX, $sourceLaneY)); $routePoints.Add(@($gutterX, $targetLaneY)); $routePoints.Add(@($tx, $targetLaneY)); $routePoints.Add(@($tx, $ty))
    } elseif ([Math]::Abs($layerIndex[$from.Parent] - $layerIndex[$to.Parent]) -gt 1 -or $primaryBlockedCrossLayer) {
        $movingDown = $to.Y -gt $from.Y
        $sx = $from.X + ($from.Width / 2)
        $tx = $to.X + ($to.Width / 2)
        if ($movingDown) {
            $sy = $from.Y + $from.Height
            $sourceLaneY = $sy + 24
            $ty = $to.Y
            $targetLaneY = $ty - 24
        } else {
            $sy = $from.Y
            $sourceLaneY = $sy - 24
            $ty = $to.Y + $to.Height
            $targetLaneY = $ty + 24
        }
        $preferLeft = if ($primaryBlockedCrossLayer) { $false } else { (($sx + $tx) / 2) -lt 800 }
        if (($preferLeft -and $leftGutterCount -lt 3) -or $rightGutterCount -ge 3) {
            $gutterX = 82 - ($leftGutterCount * 28)
            $leftGutterCount++
            $labelAngle = -90
        } else {
            $gutterX = 1518 + ($rightGutterCount * 28)
            $rightGutterCount++
            $labelAngle = 90
        }
        $midX = ($gutterX + $tx) / 2
        $midY = $targetLaneY
        $rotatedLabel = $false
        $path = 'M ' + (Format-Number $sx) + ' ' + (Format-Number $sy) + ' V ' + (Format-Number $sourceLaneY) + ' H ' + (Format-Number $gutterX) + ' V ' + (Format-Number $targetLaneY) + ' H ' + (Format-Number $tx) + ' V ' + (Format-Number $ty)
        $routePoints.Add(@($sx, $sy)); $routePoints.Add(@($sx, $sourceLaneY)); $routePoints.Add(@($gutterX, $sourceLaneY)); $routePoints.Add(@($gutterX, $targetLaneY)); $routePoints.Add(@($tx, $targetLaneY)); $routePoints.Add(@($tx, $ty))
    } else {
        $simpleAdjacent = (
            ($from.Parent -eq 'users' -and $to.Parent -eq 'channels') -or
            ($from.Parent -eq 'channels' -and $to.Parent -eq 'agent-platform') -or
            ($to.Parent -eq 'users' -and $from.Parent -eq 'channels') -or
            ($to.Parent -eq 'channels' -and $from.Parent -eq 'agent-platform')
        )
        $sx = $from.X + ($from.Width / 2)
        $tx = $to.X + ($to.Width / 2)
        if ($simpleAdjacent) {
            $sy = $from.Y + $from.Height
            $ty = $to.Y
            if ($to.Y -lt $from.Y) {
                $sy = $from.Y
                $ty = $to.Y + $to.Height
            }
            $pair = @($from.Parent, $to.Parent) | Sort-Object
            $pairKey = $pair -join '|'
            $lane = $crossLayerLaneIndex[$pairKey]
            $crossLayerLaneIndex[$pairKey]++
            $laneCount = $crossLayerLaneCount[$pairKey]
            $gapStart = [Math]::Min($sy, $ty)
            $gapEnd = [Math]::Max($sy, $ty)
            $midY = $gapStart + (($lane + 1) * (($gapEnd - $gapStart) / ($laneCount + 1)))
            $midX = ($sx + $tx) / 2
            $path = 'M ' + (Format-Number $sx) + ' ' + (Format-Number $sy) + ' V ' + (Format-Number $midY) + ' H ' + (Format-Number $tx) + ' V ' + (Format-Number $ty)
            $routePoints.Add(@($sx, $sy)); $routePoints.Add(@($sx, $midY)); $routePoints.Add(@($tx, $midY)); $routePoints.Add(@($tx,$ty))
        } else {
            $movingDown = $to.Y -gt $from.Y
            if ($movingDown) {
                $sy = $from.Y + $from.Height
                $sourceLaneY = $sy + 24
                $ty = $to.Y
                $targetLaneY = $ty - 24
            } else {
                $sy = $from.Y
                $sourceLaneY = $sy - 24
                $ty = $to.Y + $to.Height
                $targetLaneY = $ty + 24
            }
            if ((($sx + $tx) / 2) -lt ($canvasWidth / 2)) {
                $gutterX = 90 - (($leftGutterCount % 5) * 14)
                $leftGutterCount++
            } else {
                $gutterX = 1510 + (($rightGutterCount % 4) * 14)
                $rightGutterCount++
            }
            $midX = ($sx + $gutterX) / 2
            $midY = $sourceLaneY
            $path = 'M ' + (Format-Number $sx) + ' ' + (Format-Number $sy) + ' V ' + (Format-Number $sourceLaneY) + ' H ' + (Format-Number $gutterX) + ' V ' + (Format-Number $targetLaneY) + ' H ' + (Format-Number $tx) + ' V ' + (Format-Number $ty)
            $routePoints.Add(@($sx, $sy)); $routePoints.Add(@($sx,$sourceLaneY)); $routePoints.Add(@($gutterX,$sourceLaneY)); $routePoints.Add(@($gutterX,$targetLaneY)); $routePoints.Add(@($tx,$targetLaneY)); $routePoints.Add(@($tx,$ty))
        }
    }
    $dash = if ($isDashed) { ' stroke-dasharray="9 7"' } else { '' }
    $labelWidth = [Math]::Min(270, [Math]::Max(88, ($label.Length * 7) + 18))
    $route = @($routePoints | ForEach-Object { (Format-Number ([double]$_[0])) + ',' + (Format-Number ([double]$_[1])) }) -join ';'
    if ($rotatedLabel) {
        $labelSvg = '<g data-kind="connector-label" data-x="' + (Format-Number ($midX - 12)) + '" data-y="' + (Format-Number ($midY - ($labelWidth / 2))) + '" data-width="24" data-height="' + $labelWidth + '" transform="translate(' + (Format-Number $midX) + ' ' + (Format-Number $midY) + ') rotate(' + $labelAngle + ')"><rect x="' + (Format-Number (-1 * $labelWidth / 2)) + '" y="-12" width="' + $labelWidth + '" height="24" rx="12" fill="#0f172a" stroke="#334155"/><text x="0" y="4" text-anchor="middle" fill="#e2e8f0" font-family="Inter,Arial,sans-serif" font-size="11">' + (Escape-Xml $label) + '</text></g>'
    } else {
        $labelSvg = '<g data-kind="connector-label" data-x="' + (Format-Number ($midX - ($labelWidth / 2))) + '" data-y="' + (Format-Number ($midY - 15)) + '" data-width="' + $labelWidth + '" data-height="24"><rect x="' + (Format-Number ($midX - ($labelWidth / 2))) + '" y="' + (Format-Number ($midY - 15)) + '" width="' + $labelWidth + '" height="24" rx="12" fill="#0f172a" stroke="#334155"/><text x="' + (Format-Number $midX) + '" y="' + (Format-Number ($midY + 2)) + '" text-anchor="middle" fill="#e2e8f0" font-family="Inter,Arial,sans-serif" font-size="11">' + (Escape-Xml $label) + '</text></g>'
    }
    $bridgeSvg = ''
    if ($null -ne $optimizedRoute -and $routeBridges.ContainsKey([string]$optimizedRoute.id)) {
        foreach ($bridge in ($routeBridges[[string]$optimizedRoute.id] | ForEach-Object { $_ })) {
            $bridgeX = [double]$bridge.X
            $bridgeY = [double]$bridge.Y
            $bridgePath = if ([string]$bridge.Orientation -eq 'vertical') {
                'M ' + (Format-Number $bridgeX) + ' ' + (Format-Number ($bridgeY - 7)) + ' Q ' + (Format-Number ($bridgeX + 10)) + ' ' + (Format-Number $bridgeY) + ' ' + (Format-Number $bridgeX) + ' ' + (Format-Number ($bridgeY + 7))
            } else {
                'M ' + (Format-Number ($bridgeX - 7)) + ' ' + (Format-Number $bridgeY) + ' Q ' + (Format-Number $bridgeX) + ' ' + (Format-Number ($bridgeY - 10)) + ' ' + (Format-Number ($bridgeX + 7)) + ' ' + (Format-Number $bridgeY)
            }
            $bridgeSvg += '<g data-kind="connector-bridge" data-x="' + (Format-Number $bridgeX) + '" data-y="' + (Format-Number $bridgeY) + '"><circle cx="' + (Format-Number $bridgeX) + '" cy="' + (Format-Number $bridgeY) + '" r="8" fill="#0f172a"/><path d="' + $bridgePath + '" fill="none" stroke="' + $color + '" stroke-width="2.5"' + $dash + '/></g>'
        }
    }
    $sa.Add('<g data-kind="connector" data-from="' + [string]$edge.from + '" data-to="' + [string]$edge.to + '" data-implementation-mode="' + $implementationMode + '" data-route="' + $route + '"><path d="' + $path + '" fill="none" stroke="' + $color + '" stroke-width="2.5"' + $dash + ' marker-end="url(#' + $marker + ')"/>' + $bridgeSvg + $labelSvg + '</g>')
}

foreach ($component in $components) {
    $id = [string]$component.id
    $g = $geometry[$id]
    $icon = $usedIcons[$id]
    $members = @(Get-ComponentMembers $component)
    $role = if ($g.PSObject.Properties.Name -contains 'Role') { [string]$g.Role } else { 'standard' }
    $implementationStatus = [string]$component.implementationStatus
    $statusColor = switch ($implementationStatus) { 'existing' { '#22c55e' } 'build' { '#60a5fa' } 'configure' { '#60a5fa' } 'simulate' { '#06b6d4' } 'static-sample-data' { '#06b6d4' } 'manual-handoff' { '#f59e0b' } 'defer' { '#94a3b8' } 'block' { '#ef4444' } default { '#f59e0b' } }
    $statusLabel = switch ($implementationStatus) { 'static-sample-data' { 'SAMPLE DATA' } 'manual-handoff' { 'MANUAL' } default { $implementationStatus.ToUpperInvariant() } }
    $nodeDash = if (@('simulate', 'static-sample-data', 'manual-handoff', 'defer', 'block') -contains $implementationStatus) { ' stroke-dasharray="8 6"' } else { '' }
    $sa.Add('<g id="node-' + $id + '" data-kind="node" data-component-id="' + $id + '" data-component-kind="' + (Escape-Xml ([string]$component.kind)) + '" data-implementation-status="' + $implementationStatus + '" data-parent="' + $g.Parent + '" data-members-count="' + $members.Count + '" data-x="' + $g.X + '" data-y="' + $g.Y + '" data-width="' + $g.Width + '" data-height="' + $g.Height + '">')
    if ($role -eq 'hero') {
        $sa.Add('<rect x="' + $g.X + '" y="' + $g.Y + '" width="' + $g.Width + '" height="' + $g.Height + '" rx="18" fill="url(#hero-card)" stroke="' + $statusColor + '" stroke-width="2.5"' + $nodeDash + ' filter="url(#shadow)"/><rect x="' + $g.X + '" y="' + $g.Y + '" width="' + $g.Width + '" height="7" rx="4" fill="' + $statusColor + '"/>')
        $sa.Add('<image href="' + $icon.DataUri + '" xlink:href="' + $icon.DataUri + '" x="' + ($g.X + 24) + '" y="' + ($g.Y + 38) + '" width="66" height="66" preserveAspectRatio="xMidYMid meet"/>')
        $titleLines = @(Get-WrappedLines ([string]$component.name) 46 10)
        for ($i = 0; $i -lt $titleLines.Count; $i++) {
            $sa.Add('<text x="' + ($g.X + 112) + '" y="' + ($g.Y + 44 + ($i * 20)) + '" fill="#111827" font-family="Inter,Arial,sans-serif" font-size="17" font-weight="700">' + (Escape-Xml $titleLines[$i]) + '</text>')
        }
        $badgeY = $g.Y + 52 + ($titleLines.Count * 20)
        $sa.Add('<rect x="' + ($g.X + 112) + '" y="' + $badgeY + '" width="116" height="22" rx="11" fill="#7c3aed" fill-opacity=".13"/><text x="' + ($g.X + 170) + '" y="' + ($badgeY + 15) + '" text-anchor="middle" fill="#6d28d9" font-family="Inter,Arial,sans-serif" font-size="10" font-weight="700">PRIMARY AGENT</text>')
        $descriptionLines = @(Get-WrappedLines ([string]$component.description) 58 32)
        for ($i = 0; $i -lt $descriptionLines.Count; $i++) {
            $sa.Add('<text x="' + ($g.X + 244) + '" y="' + ($g.Y + 91 + ($i * 16)) + '" fill="#475569" font-family="Inter,Arial,sans-serif" font-size="11">' + (Escape-Xml $descriptionLines[$i]) + '</text>')
        }
        if ($members.Count -gt 0) {
            $memberHeadingY = [Math]::Max($badgeY + 40, $g.Y + 91 + ($descriptionLines.Count * 16)) + 18
            $memberY = $memberHeadingY + 17
            $sa.Add('<text x="' + ($g.X + 112) + '" y="' + $memberHeadingY + '" fill="#6d28d9" font-family="Inter,Arial,sans-serif" font-size="10" font-weight="700">CAPABILITIES</text>')
            foreach ($member in $members) {
                $memberLines = @(Get-WrappedLines $member 56 32)
                $sa.Add('<g data-kind="member" data-name="' + (Escape-Xml $member) + '">')
                for ($memberIndex = 0; $memberIndex -lt $memberLines.Count; $memberIndex++) {
                    $prefix = if ($memberIndex -eq 0) { '- ' } else { '  ' }
                    $sa.Add('<text x="' + ($g.X + 112) + '" y="' + $memberY + '" fill="#334155" font-family="Inter,Arial,sans-serif" font-size="9.5">' + (Escape-Xml ($prefix + $memberLines[$memberIndex])) + '</text>')
                    $memberY += 14
                }
                $sa.Add('</g>')
            }
        }
    } else {
        $nodeFill = if ($role -eq 'compact') { '#f1f5f9' } else { '#f8fafc' }
        $nodeStroke = $statusColor
        $sa.Add('<rect x="' + $g.X + '" y="' + $g.Y + '" width="' + $g.Width + '" height="' + $g.Height + '" rx="15" fill="' + $nodeFill + '" stroke="' + $nodeStroke + '" stroke-width="' + $(if ($role -eq 'satellite') { '2' } else { '1.5' }) + '"' + $nodeDash + ' filter="url(#shadow)"/>')
        $iconSize = if ($role -eq 'compact') { 42 } else { 48 }
        $iconY = $g.Y + (($g.Height - $iconSize) / 2)
        $sa.Add('<image href="' + $icon.DataUri + '" xlink:href="' + $icon.DataUri + '" x="' + ($g.X + 18) + '" y="' + (Format-Number $iconY) + '" width="' + $iconSize + '" height="' + $iconSize + '" preserveAspectRatio="xMidYMid meet"/>')
        $textX = $g.X + 78
        $titleMax = [Math]::Max(20, [Math]::Floor(($g.Width - 182) / 7))
        $titleLines = @(Get-WrappedLines ([string]$component.name) $titleMax 10)
        for ($i = 0; $i -lt $titleLines.Count; $i++) {
            $sa.Add('<text x="' + $textX + '" y="' + ($g.Y + 35 + ($i * 17)) + '" fill="#0f172a" font-family="Inter,Arial,sans-serif" font-size="14" font-weight="700">' + (Escape-Xml $titleLines[$i]) + '</text>')
        }
        $descriptionMax = [Math]::Max(24, [Math]::Floor(($g.Width - 100) / 7))
        $descriptionLines = @(Get-WrappedLines ([string]$component.description) $descriptionMax 32)
        $descriptionStart = if ($titleLines.Count -gt 1) { $g.Y + 75 } else { $g.Y + 62 }
        for ($i = 0; $i -lt $descriptionLines.Count; $i++) {
            $sa.Add('<text x="' + $textX + '" y="' + ($descriptionStart + ($i * 15)) + '" fill="#475569" font-family="Inter,Arial,sans-serif" font-size="10.5">' + (Escape-Xml $descriptionLines[$i]) + '</text>')
        }
        if ($members.Count -gt 0) {
            $memberHeadingY = $descriptionStart + ($descriptionLines.Count * 15) + 10
            $memberY = $memberHeadingY + 16
            $sa.Add('<text x="' + $textX + '" y="' + $memberHeadingY + '" fill="#475569" font-family="Inter,Arial,sans-serif" font-size="9.5" font-weight="700">INCLUDED COMPONENTS</text>')
            $memberMax = [Math]::Max(18, $descriptionMax - 2)
            foreach ($member in $members) {
                $memberLines = @(Get-WrappedLines $member $memberMax 32)
                $sa.Add('<g data-kind="member" data-name="' + (Escape-Xml $member) + '">')
                for ($memberIndex = 0; $memberIndex -lt $memberLines.Count; $memberIndex++) {
                    $prefix = if ($memberIndex -eq 0) { '- ' } else { '  ' }
                    $sa.Add('<text x="' + $textX + '" y="' + $memberY + '" fill="#334155" font-family="Inter,Arial,sans-serif" font-size="9.5">' + (Escape-Xml ($prefix + $memberLines[$memberIndex])) + '</text>')
                    $memberY += 14
                }
                $sa.Add('</g>')
            }
        }
    }
    $sa.Add('<rect x="' + ($g.X + $g.Width - 124) + '" y="' + ($g.Y + 10) + '" width="112" height="20" rx="10" fill="' + $statusColor + '" fill-opacity=".16"/><text x="' + ($g.X + $g.Width - 68) + '" y="' + ($g.Y + 24) + '" text-anchor="middle" fill="' + $statusColor + '" font-family="Inter,Arial,sans-serif" font-size="10" font-weight="700">' + (Escape-Xml $statusLabel) + '</text>')
    if (-not $icon.Verified) {
        $sa.Add('<text x="' + ($g.X + 18) + '" y="' + ($g.Y + $g.Height - 10) + '" fill="#64748b" font-family="Inter,Arial,sans-serif" font-size="9">generic</text>')
    }
    $sa.Add('</g>')
}

$legendY = $canvasHeight - $legendHeight
$genericIcon = Resolve-Icon 'generic-component'
$verifiedExample = @($usedIcons.Values | Where-Object { $_.Verified } | Select-Object -First 1)
if ($verifiedExample.Count -eq 0) { $verifiedExample = @(Resolve-Icon 'copilot-studio') }
$sa.Add('<g data-kind="legend" data-x="40" data-y="' + $legendY + '" data-width="' + ($canvasWidth - 80) + '" data-height="68"><rect x="40" y="' + $legendY + '" width="' + ($canvasWidth - 80) + '" height="68" rx="14" fill="#0f172a" stroke="#334155"/><text x="64" y="' + ($legendY + 25) + '" fill="#f8fafc" font-family="Inter,Arial,sans-serif" font-size="14" font-weight="700">Legend</text>')
$sa.Add('<image href="' + $verifiedExample[0].DataUri + '" xlink:href="' + $verifiedExample[0].DataUri + '" x="150" y="' + ($legendY + 15) + '" width="28" height="28"/><text x="188" y="' + ($legendY + 35) + '" fill="#cbd5e1" font-family="Inter,Arial,sans-serif" font-size="11">Verified Microsoft product icon</text>')
$sa.Add('<image href="' + $genericIcon.DataUri + '" xlink:href="' + $genericIcon.DataUri + '" x="430" y="' + ($legendY + 15) + '" width="28" height="28"/><text x="468" y="' + ($legendY + 35) + '" fill="#cbd5e1" font-family="Inter,Arial,sans-serif" font-size="11">Generic style (no cached verified icon)</text>')
$sa.Add('<line x1="760" y1="' + ($legendY + 29) + '" x2="820" y2="' + ($legendY + 29) + '" stroke="#60a5fa" stroke-width="3" marker-end="url(#arrow-blue)"/><text x="835" y="' + ($legendY + 35) + '" fill="#cbd5e1" font-family="Inter,Arial,sans-serif" font-size="11">Call or dependency</text>')
$sa.Add('<line x1="1040" y1="' + ($legendY + 29) + '" x2="1100" y2="' + ($legendY + 29) + '" stroke="#f59e0b" stroke-width="3" stroke-dasharray="9 7" marker-end="url(#arrow-amber)"/><text x="1115" y="' + ($legendY + 35) + '" fill="#cbd5e1" font-family="Inter,Arial,sans-serif" font-size="11">Manual, simulated, deferred, or blocked</text></g>')
$sa.Add('</svg>')
[IO.File]::WriteAllText($saPath, ($sa -join [Environment]::NewLine), $Utf8)

$participantIds = New-Object System.Collections.Generic.List[string]
foreach ($message in $sequence) {
    foreach ($candidate in @([string]$message.from, [string]$message.to)) {
        if (-not $participantIds.Contains($candidate)) { $participantIds.Add($candidate) }
    }
}
if ($participantIds.Count -gt 8) { throw "Sequence has $($participantIds.Count) participants; maximum is 8." }
if ($participantIds.Count -lt 2) { throw 'Sequence requires at least two participants.' }

$sdWidth = 1600
$messageGap = 72
$sdLegendHeight = 92
$maxLifelineNameLines = 1
foreach ($participantId in $participantIds) {
    $lineCount = @(Get-WrappedLines ([string]$componentById[$participantId].name) 23 8).Count
    if ($lineCount -gt $maxLifelineNameLines) { $maxLifelineNameLines = $lineCount }
}
$lifelineHeaderY = 104
$lifelineHeaderHeight = 110 + ($maxLifelineNameLines * 15)
$lifelineHeaderBottom = $lifelineHeaderY + $lifelineHeaderHeight
$sequenceTop = $lifelineHeaderBottom + 58
$sdHeight = $sequenceTop + ($sequence.Count * $messageGap) + $sdLegendHeight + 50
$lifelineX = @{}
$spacing = ($sdWidth - 240) / [double]($participantIds.Count - 1)
for ($i = 0; $i -lt $participantIds.Count; $i++) { $lifelineX[$participantIds[$i]] = 120 + ($i * $spacing) }
$kindColors = @{
    'actor' = '#2563eb'; 'channel' = '#4f46e5'; 'agent' = '#7c3aed'; 'knowledge' = '#0891b2'
    'tool' = '#0f766e'; 'flow' = '#059669'; 'data' = '#0369a1'; 'integration' = '#0284c7'
    'external' = '#475569'; 'human' = '#d97706'; 'security' = '#b45309'; 'monitoring' = '#059669'; 'alm' = '#0f766e'
}
$phaseGroups = New-Object System.Collections.Generic.List[object]
$currentPhaseGroup = $null
for ($i = 0; $i -lt $sequence.Count; $i++) {
    $phaseName = if ($sequence[$i].PSObject.Properties.Name -contains 'phase' -and -not [string]::IsNullOrWhiteSpace([string]$sequence[$i].phase)) { [string]$sequence[$i].phase } else { 'Interaction' }
    if ($null -eq $currentPhaseGroup -or $currentPhaseGroup.Name -ne $phaseName) {
        if ($null -ne $currentPhaseGroup) { $currentPhaseGroup.End = $i - 1 }
        $currentPhaseGroup = [pscustomobject]@{ Name = $phaseName; Start = $i; End = $i }
        $phaseGroups.Add($currentPhaseGroup)
    }
}
if ($null -ne $currentPhaseGroup) { $currentPhaseGroup.End = $sequence.Count - 1 }

$sd = New-Object System.Collections.Generic.List[string]
$sd.Add('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 1600 ' + $sdHeight + '" role="img" aria-labelledby="title desc">')
$sd.Add('<title id="title">' + (Escape-Xml ([string]$model.title)) + ' - Sequence Diagram</title><desc id="desc">Sequence derived from the solution architecture.</desc>')
$sd.Add('<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#081426"/><stop offset="1" stop-color="#172554"/></linearGradient><filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#020617" flood-opacity=".28"/></filter><marker id="arrow-blue" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#60a5fa"/></marker><marker id="arrow-green" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#22c55e"/></marker><marker id="arrow-purple" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#a78bfa"/></marker></defs>')
$sd.Add('<rect width="1600" height="' + $sdHeight + '" fill="url(#bg)"/>')
$sd.Add('<circle cx="1420" cy="70" r="200" fill="#7c3aed" fill-opacity=".08"/><text x="40" y="50" fill="#f8fafc" font-family="Inter,Arial,sans-serif" font-size="28" font-weight="700">' + (Escape-Xml ([string]$model.title)) + '</text><text x="40" y="80" fill="#bfdbfe" font-family="Inter,Arial,sans-serif" font-size="15">Sequence Diagram | Native ' + (Escape-Xml ([string]$model.coverage.nativeBuildPercent)) + '% | PoC ' + (Escape-Xml ([string]$model.coverage.pocDemonstrationPercent)) + '%</text><rect x="1362" y="34" width="182" height="38" rx="19" fill="#7c3aed" fill-opacity=".18" stroke="#a78bfa"/><text x="1453" y="58" text-anchor="middle" fill="#ddd6fe" font-family="Inter,Arial,sans-serif" font-size="12" font-weight="700">PHASE-STRUCTURED</text>')

$phaseIndex = 0
foreach ($phaseGroup in $phaseGroups) {
    $phaseY = $sequenceTop + ($phaseGroup.Start * $messageGap) - 42
    $phaseHeight = (($phaseGroup.End - $phaseGroup.Start + 1) * $messageGap) + 52
    $phaseFill = if (($phaseIndex % 2) -eq 0) { '#0f2747' } else { '#13233b' }
    $phaseAccent = if (($phaseIndex % 2) -eq 0) { '#38bdf8' } else { '#a78bfa' }
    $sd.Add('<g data-kind="phase"><rect x="30" y="' + $phaseY + '" width="1540" height="' + $phaseHeight + '" rx="14" fill="' + $phaseFill + '" fill-opacity=".5" stroke="#334155"/><rect x="30" y="' + $phaseY + '" width="8" height="' + $phaseHeight + '" rx="4" fill="' + $phaseAccent + '"/><rect x="48" y="' + ($phaseY + 12) + '" width="132" height="24" rx="12" fill="' + $phaseAccent + '" fill-opacity=".16"/><text x="114" y="' + ($phaseY + 29) + '" text-anchor="middle" fill="' + $phaseAccent + '" font-family="Inter,Arial,sans-serif" font-size="11" font-weight="700">' + (Escape-Xml ([string]$phaseGroup.Name)) + '</text></g>')
    $phaseIndex++
}

$lifelineEnd = $sdHeight - $sdLegendHeight - 24
foreach ($participantId in $participantIds) {
    $component = $componentById[$participantId]
    $x = [double]$lifelineX[$participantId]
    $icon = $usedIcons[$participantId]
    $accent = $kindColors[[string]$component.kind]
    if (-not $accent) { $accent = '#64748b' }
    $headerX = $x - 88
    $sd.Add('<g id="lifeline-' + $participantId + '" data-kind="lifeline" data-component-id="' + $participantId + '" data-x="' + (Format-Number $headerX) + '" data-y="' + $lifelineHeaderY + '" data-width="176" data-height="' + $lifelineHeaderHeight + '"><rect x="' + (Format-Number $headerX) + '" y="' + $lifelineHeaderY + '" width="176" height="' + $lifelineHeaderHeight + '" rx="16" fill="#f8fafc" stroke="' + $accent + '" stroke-width="2" filter="url(#shadow)"/><rect x="' + (Format-Number $headerX) + '" y="' + $lifelineHeaderY + '" width="176" height="7" rx="4" fill="' + $accent + '"/><image href="' + $icon.DataUri + '" xlink:href="' + $icon.DataUri + '" x="' + (Format-Number ($x - 20)) + '" y="120" width="40" height="40"/>')
    $nameLines = @(Get-WrappedLines ([string]$component.name) 23 8)
    for ($i = 0; $i -lt $nameLines.Count; $i++) {
        $sd.Add('<text x="' + (Format-Number $x) + '" y="' + (176 + ($i * 15)) + '" text-anchor="middle" fill="#0f172a" font-family="Inter,Arial,sans-serif" font-size="12" font-weight="700">' + (Escape-Xml $nameLines[$i]) + '</text>')
    }
    $kindY = 178 + ($nameLines.Count * 15) + 10
    $sd.Add('<rect x="' + (Format-Number ($x - 38)) + '" y="' + $kindY + '" width="76" height="16" rx="8" fill="' + $accent + '" fill-opacity=".13"/><text x="' + (Format-Number $x) + '" y="' + ($kindY + 12) + '" text-anchor="middle" fill="' + $accent + '" font-family="Inter,Arial,sans-serif" font-size="9" font-weight="700">' + (Escape-Xml (([string]$component.kind).ToUpperInvariant())) + '</text><line x1="' + (Format-Number $x) + '" y1="' + $lifelineHeaderBottom + '" x2="' + (Format-Number $x) + '" y2="' + $lifelineEnd + '" stroke="' + $accent + '" stroke-opacity=".65" stroke-width="2" stroke-dasharray="7 7"/></g>')
}

$agentParticipant = @($participantIds | Where-Object { [string]$componentById[$_].kind -eq 'agent' } | Select-Object -First 1)
$agentId = ''
if ($agentParticipant.Count -gt 0) {
    $agentId = [string]$agentParticipant[0]
    $agentX = [double]$lifelineX[$agentId]
    $activationY = $lifelineHeaderBottom + 8
    $sd.Add('<rect x="' + (Format-Number ($agentX - 5)) + '" y="' + $activationY + '" width="10" height="' + ($lifelineEnd - $activationY) + '" rx="5" fill="#7c3aed" fill-opacity=".78" stroke="#ddd6fe"/>')
}

for ($index = 0; $index -lt $sequence.Count; $index++) {
    $message = $sequence[$index]
    $number = $index + 1
    $fromId = [string]$message.from
    $toId = [string]$message.to
    $fromX = [double]$lifelineX[$fromId]
    $toX = [double]$lifelineX[$toId]
    $y = $sequenceTop + ($index * $messageGap)
    $label = "$number. $([string]$message.label)"
    $type = [string]$message.type
    $implementationMode = [string]$message.implementationMode
    $color = switch ($implementationMode) { 'blocked' { '#ef4444' } 'deferred' { '#94a3b8' } 'manual' { '#f59e0b' } 'simulated' { '#22d3ee' } default { if ($type -eq 'approval') { '#22c55e' } elseif ($type -eq 'self') { '#a78bfa' } else { '#60a5fa' } } }
    $marker = if ($type -eq 'approval') { 'arrow-green' } elseif ($type -eq 'self') { 'arrow-purple' } else { 'arrow-blue' }
    $dash = if ($type -eq 'response' -or $implementationMode -ne 'real') { ' stroke-dasharray="9 7"' } else { '' }
    $fragment = if ($message.PSObject.Properties.Name -contains 'fragment') { [string]$message.fragment } else { '' }
    if (-not [string]::IsNullOrWhiteSpace($fragment)) {
        $fragmentWidth = [Math]::Min(300, [Math]::Max(130, ($fragment.Length * 7) + 20))
        $sd.Add('<g data-kind="fragment"><rect x="190" y="' + ($y - 38) + '" width="1370" height="58" rx="10" fill="#f59e0b" fill-opacity=".035" stroke="#f59e0b" stroke-dasharray="8 6"/><rect x="204" y="' + ($y - 38) + '" width="' + $fragmentWidth + '" height="24" rx="6" fill="#292524" stroke="#f59e0b"/><text x="216" y="' + ($y - 21) + '" fill="#fbbf24" font-family="Inter,Arial,sans-serif" font-size="11" font-weight="700">' + (Escape-Xml $fragment) + '</text></g>')
    }
    if ($fromId -eq $toId -or $type -eq 'self') {
        $right = $fromX + 86
        $path = 'M ' + (Format-Number $fromX) + ' ' + $y + ' H ' + (Format-Number $right) + ' V ' + ($y + 26) + ' H ' + (Format-Number ($fromX + 8))
        $midX = $fromX + 55
        $labelY = $y - 10
    } else {
        $path = 'M ' + (Format-Number $fromX) + ' ' + $y + ' H ' + (Format-Number $toX)
        $midX = ($fromX + $toX) / 2
        $labelY = $y - 10
    }
    $labelWidth = [Math]::Min(360, [Math]::Max(120, ($label.Length * 7) + 22))
    $sd.Add('<g data-kind="message" data-implementation-mode="' + $implementationMode + '"><path d="' + $path + '" fill="none" stroke="' + $color + '" stroke-width="2.5"' + $dash + ' marker-end="url(#' + $marker + ')"/><rect x="' + (Format-Number ($midX - ($labelWidth / 2))) + '" y="' + ($labelY - 18) + '" width="' + $labelWidth + '" height="25" rx="12.5" fill="#081426" fill-opacity=".96" stroke="' + $color + '" stroke-opacity=".55"/><text x="' + (Format-Number $midX) + '" y="' + $labelY + '" text-anchor="middle" fill="#f1f5f9" font-family="Inter,Arial,sans-serif" font-size="11.5">' + (Escape-Xml $label) + '</text></g>')
    if ($toId -ne $agentId) {
        $targetAccent = $kindColors[[string]$componentById[$toId].kind]
        if (-not $targetAccent) { $targetAccent = $color }
        $sd.Add('<rect x="' + (Format-Number ($toX - 4)) + '" y="' + ($y - 8) + '" width="8" height="34" rx="4" fill="' + $targetAccent + '" fill-opacity=".82"/>')
    }
}

$sdLegendY = $sdHeight - $sdLegendHeight
$sdGeneric = Resolve-Icon 'generic-component'
$sdVerified = @($usedIcons.Values | Where-Object { $_.Verified } | Select-Object -First 1)
if ($sdVerified.Count -eq 0) { $sdVerified = @(Resolve-Icon 'copilot-studio') }
$sd.Add('<g data-kind="legend" data-x="40" data-y="' + $sdLegendY + '" data-width="1520" data-height="68"><rect x="40" y="' + $sdLegendY + '" width="1520" height="68" rx="14" fill="#0f172a" stroke="#334155"/><text x="64" y="' + ($sdLegendY + 25) + '" fill="#f8fafc" font-family="Inter,Arial,sans-serif" font-size="14" font-weight="700">Legend</text><image href="' + $sdVerified[0].DataUri + '" xlink:href="' + $sdVerified[0].DataUri + '" x="150" y="' + ($sdLegendY + 15) + '" width="28" height="28"/><text x="188" y="' + ($sdLegendY + 35) + '" fill="#cbd5e1" font-family="Inter,Arial,sans-serif" font-size="11">Verified Microsoft product icon</text><image href="' + $sdGeneric.DataUri + '" xlink:href="' + $sdGeneric.DataUri + '" x="430" y="' + ($sdLegendY + 15) + '" width="28" height="28"/><text x="468" y="' + ($sdLegendY + 35) + '" fill="#cbd5e1" font-family="Inter,Arial,sans-serif" font-size="11">Generic style</text><line x1="700" y1="' + ($sdLegendY + 29) + '" x2="760" y2="' + ($sdLegendY + 29) + '" stroke="#60a5fa" stroke-width="3" marker-end="url(#arrow-blue)"/><text x="775" y="' + ($sdLegendY + 35) + '" fill="#cbd5e1" font-family="Inter,Arial,sans-serif" font-size="11">Call or action</text><line x1="970" y1="' + ($sdLegendY + 29) + '" x2="1030" y2="' + ($sdLegendY + 29) + '" stroke="#60a5fa" stroke-width="3" stroke-dasharray="9 7" marker-end="url(#arrow-blue)"/><text x="1045" y="' + ($sdLegendY + 35) + '" fill="#cbd5e1" font-family="Inter,Arial,sans-serif" font-size="11">Response</text><line x1="1190" y1="' + ($sdLegendY + 29) + '" x2="1250" y2="' + ($sdLegendY + 29) + '" stroke="#22c55e" stroke-width="3" marker-end="url(#arrow-green)"/><text x="1265" y="' + ($sdLegendY + 35) + '" fill="#cbd5e1" font-family="Inter,Arial,sans-serif" font-size="11">Human approval</text></g>')
$sd.Add('</svg>')
[IO.File]::WriteAllText($sdPath, ($sd -join [Environment]::NewLine), $Utf8)

$iconOutput = @()
foreach ($component in $components) {
    $icon = $usedIcons[[string]$component.id]
    $iconOutput += [ordered]@{
        component = [string]$component.name
        componentId = [string]$component.id
        icon = [IO.Path]::GetFileName([string]$icon.File)
        source = [string]$icon.Source
        verified = [bool]$icon.Verified
    }
}
$manifest = [ordered]@{
    scenarioSlug = $slug
    layoutProfile = $LayoutProfile
    layoutEngine = [string]$layoutResult.engine
    solutionArchitecture = $saPath
    sequenceDiagram = $sdPath
    icons = $iconOutput
    referenceSources = @($selectedReferences | ForEach-Object { [string]$_.url })
    generatedAt = [DateTimeOffset]::Now.ToString('o')
}
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8), $Utf8)

[pscustomobject]@{
    SolutionArchitecture = $saPath
    SequenceDiagram = $sdPath
    Manifest = $manifestPath
}
