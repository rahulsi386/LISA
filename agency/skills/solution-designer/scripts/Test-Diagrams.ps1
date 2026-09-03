[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SolutionArchitecture,
    [Parameter(Mandatory = $true)][string]$SequenceDiagram,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Invariant = [System.Globalization.CultureInfo]::InvariantCulture
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$issues = New-Object System.Collections.Generic.List[string]

$outputDirectory = Split-Path ([IO.Path]::GetFullPath($OutputPath)) -Parent
if ((Split-Path $outputDirectory -Leaf) -cne 'design') {
    throw "OutputPath must be stored directly under tempOutputPath\design: $OutputPath"
}
foreach ($diagramPath in @($SolutionArchitecture, $SequenceDiagram)) {
    if ((Split-Path ([IO.Path]::GetFullPath($diagramPath)) -Parent) -ne $outputDirectory) {
        throw "Diagram must be stored in the same Design directory as the validation report: $diagramPath"
    }
}

function Add-Issue([string]$Message) {
    if (-not $issues.Contains($Message)) { $issues.Add($Message) }
}

function Get-Number($Node, [string]$Name) {
    $raw = $Node.GetAttribute($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) { throw "Missing $Name on $($Node.Name)." }
    return [double]::Parse($raw, $Invariant)
}

function Test-Svg([string]$Path, [string]$ExpectedPrefix) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Add-Issue "Missing diagram: $Path"
        return $null
    }
    if ([IO.Path]::GetFileName($Path) -notmatch ('^' + [regex]::Escape($ExpectedPrefix) + '[A-Za-z0-9_]+\.svg$')) {
        Add-Issue "Invalid filename: $([IO.Path]::GetFileName($Path))"
    }
    try {
        [xml]$xml = Get-Content -LiteralPath $Path -Raw
    } catch {
        Add-Issue "XML parse failed for $Path`: $($_.Exception.Message)"
        return $null
    }
    $root = $xml.DocumentElement
    if ($null -eq $root -or $root.LocalName -ne 'svg') {
        Add-Issue "Root element is not svg: $Path"
        return $null
    }
    $viewBox = $root.GetAttribute('viewBox')
    $parts = @($viewBox -split '[,\s]+' | Where-Object { $_ })
    if ($parts.Count -ne 4) {
        Add-Issue "Invalid viewBox in $Path"
        return $xml
    }
    try {
        $canvasX = [double]::Parse($parts[0], $Invariant)
        $canvasY = [double]::Parse($parts[1], $Invariant)
        $canvasWidth = [double]::Parse($parts[2], $Invariant)
        $canvasHeight = [double]::Parse($parts[3], $Invariant)
    } catch {
        Add-Issue "Non-numeric viewBox in $Path"
        return $xml
    }
    if ($canvasWidth -le 0 -or $canvasHeight -le 0) { Add-Issue "Non-positive canvas size in $Path" }

    $idNodes = @($xml.SelectNodes('//*[@id]'))
    $seenIds = @{}
    foreach ($node in $idNodes) {
        $id = $node.GetAttribute('id')
        if ($seenIds.ContainsKey($id)) { Add-Issue "Duplicate id '$id' in $Path" } else { $seenIds[$id] = $true }
    }

    foreach ($image in @($xml.SelectNodes("//*[local-name()='image']"))) {
        $href = $image.GetAttribute('href')
        if ($href -notmatch '^data:image/svg\+xml;base64,[A-Za-z0-9+/=]+$') {
            Add-Issue "Image without an embedded SVG data URI in $Path"
        }
    }
    if (@($xml.SelectNodes("//*[@data-kind='legend']")).Count -ne 1) {
        Add-Issue "Diagram must contain exactly one legend: $Path"
    }
    foreach ($pathNode in @($xml.SelectNodes("//*[@data-kind='connector']/*[local-name()='path'] | //*[@data-kind='message']/*[local-name()='path']"))) {
        if ([string]::IsNullOrWhiteSpace($pathNode.GetAttribute('marker-end'))) {
            Add-Issue "Connector without arrowhead in $Path"
        }
    }

    $containers = @{}
    foreach ($container in @($xml.SelectNodes("//*[@data-kind='container']"))) {
        try {
            $box = [pscustomobject]@{
                Id = $container.GetAttribute('data-id')
                X = Get-Number $container 'data-x'
                Y = Get-Number $container 'data-y'
                Width = Get-Number $container 'data-width'
                Height = Get-Number $container 'data-height'
                Header = Get-Number $container 'data-header-height'
            }
            $containers[$box.Id] = $box
            if ($box.X -lt ($canvasX + 24) -or $box.Y -lt ($canvasY + 24) -or ($box.X + $box.Width) -gt ($canvasX + $canvasWidth - 24) -or ($box.Y + $box.Height) -gt ($canvasY + $canvasHeight - 24)) {
                Add-Issue "Container '$($box.Id)' is outside canvas margins in $Path"
            }
        } catch {
            Add-Issue "Invalid container geometry in $Path`: $($_.Exception.Message)"
        }
    }

    $nodes = New-Object System.Collections.Generic.List[object]
    foreach ($node in @($xml.SelectNodes("//*[@data-kind='node']"))) {
        try {
            $box = [pscustomobject]@{
                Id = $node.GetAttribute('data-component-id')
                Parent = $node.GetAttribute('data-parent')
                X = Get-Number $node 'data-x'
                Y = Get-Number $node 'data-y'
                Width = Get-Number $node 'data-width'
                Height = Get-Number $node 'data-height'
            }
            $nodes.Add($box)
            $componentKind = $node.GetAttribute('data-component-kind')
            $implementationStatus = $node.GetAttribute('data-implementation-status')
            if ($implementationStatus -notin @('build', 'configure', 'simulate', 'static-sample-data', 'manual-handoff', 'defer', 'block', 'existing')) {
                Add-Issue "Node '$($box.Id)' has invalid or missing implementation status in $Path"
            }
            if ($componentKind -eq 'actor' -and $box.Parent -ne 'users') {
                Add-Issue "Actor '$($box.Id)' must be in the users layer in $Path"
            }
            if ($componentKind -eq 'channel' -and $box.Parent -ne 'channels') {
                Add-Issue "Channel '$($box.Id)' must be in the channels layer in $Path"
            }
            $memberCountRaw = $node.GetAttribute('data-members-count')
            $memberCount = 0
            if (-not [int]::TryParse($memberCountRaw, [ref]$memberCount)) {
                Add-Issue "Node '$($box.Id)' has invalid data-members-count in $Path"
            } else {
                $memberNodes = @($node.SelectNodes(".//*[@data-kind='member']"))
                if ($memberNodes.Count -ne $memberCount) {
                    Add-Issue "Node '$($box.Id)' does not visibly render all grouped members in $Path"
                }
                foreach ($memberNode in $memberNodes) {
                    if ([string]::IsNullOrWhiteSpace($memberNode.GetAttribute('data-name'))) {
                        Add-Issue "Node '$($box.Id)' contains an unnamed grouped member in $Path"
                    }
                }
            }
            if (-not $containers.ContainsKey($box.Parent)) {
                Add-Issue "Node '$($box.Id)' has unknown parent '$($box.Parent)' in $Path"
            } else {
                $parent = $containers[$box.Parent]
                if ($box.X -lt ($parent.X + 24) -or $box.Y -lt ($parent.Y + $parent.Header) -or ($box.X + $box.Width) -gt ($parent.X + $parent.Width - 24) -or ($box.Y + $box.Height) -gt ($parent.Y + $parent.Height - 16)) {
                    Add-Issue "Node '$($box.Id)' is outside parent bounds in $Path"
                }
            }
        } catch {
            Add-Issue "Invalid node geometry in $Path`: $($_.Exception.Message)"
        }
    }
    for ($i = 0; $i -lt $nodes.Count; $i++) {
        for ($j = $i + 1; $j -lt $nodes.Count; $j++) {
            $a = $nodes[$i]
            $b = $nodes[$j]
            if ($a.Parent -ne $b.Parent) { continue }
            $overlap = $a.X -lt ($b.X + $b.Width) -and ($a.X + $a.Width) -gt $b.X -and $a.Y -lt ($b.Y + $b.Height) -and ($a.Y + $a.Height) -gt $b.Y
            if ($overlap) { Add-Issue "Nodes '$($a.Id)' and '$($b.Id)' overlap in $Path" }
        }
    }
    $connectorRoutes = New-Object System.Collections.Generic.List[object]
    foreach ($connector in @($xml.SelectNodes("//*[@data-kind='connector']"))) {
        $fromId = $connector.GetAttribute('data-from')
        $toId = $connector.GetAttribute('data-to')
        $routeText = $connector.GetAttribute('data-route')
        $implementationMode = $connector.GetAttribute('data-implementation-mode')
        if ($implementationMode -notin @('real', 'simulated', 'manual', 'deferred', 'blocked')) {
            Add-Issue "Connector '$fromId -> $toId' has invalid or missing implementation mode in $Path"
        }
        $points = New-Object System.Collections.Generic.List[object]
        try {
            foreach ($pointText in @($routeText -split ';' | Where-Object { $_ })) {
                $coordinates = @($pointText -split ',')
                if ($coordinates.Count -ne 2) { throw "Invalid route point '$pointText'." }
                $points.Add([pscustomobject]@{
                    X = [double]::Parse($coordinates[0], $Invariant)
                    Y = [double]::Parse($coordinates[1], $Invariant)
                })
            }
        } catch {
            Add-Issue "Invalid connector route in $Path`: $($_.Exception.Message)"
            continue
        }
        $connectorRoutes.Add([pscustomobject]@{
            From = $fromId
            To = $toId
            Points = $points
        })
        for ($segmentIndex = 0; $segmentIndex -lt ($points.Count - 1); $segmentIndex++) {
            $p1 = $points[$segmentIndex]
            $p2 = $points[$segmentIndex + 1]
            foreach ($nodeBox in $nodes) {
                if ($nodeBox.Id -eq $fromId -or $nodeBox.Id -eq $toId) { continue }
                $left = $nodeBox.X + 1
                $right = $nodeBox.X + $nodeBox.Width - 1
                $top = $nodeBox.Y + 1
                $bottom = $nodeBox.Y + $nodeBox.Height - 1
                $intersects = $false
                if ([Math]::Abs($p1.X - $p2.X) -lt 0.01) {
                    $minY = [Math]::Min($p1.Y, $p2.Y)
                    $maxY = [Math]::Max($p1.Y, $p2.Y)
                    $intersects = $p1.X -gt $left -and $p1.X -lt $right -and $maxY -gt $top -and $minY -lt $bottom
                } elseif ([Math]::Abs($p1.Y - $p2.Y) -lt 0.01) {
                    $minX = [Math]::Min($p1.X, $p2.X)
                    $maxX = [Math]::Max($p1.X, $p2.X)
                    $intersects = $p1.Y -gt $top -and $p1.Y -lt $bottom -and $maxX -gt $left -and $minX -lt $right
                } else {
                    Add-Issue "Connector '$fromId -> $toId' contains a non-orthogonal route segment in $Path"
                }
                if ($intersects) { Add-Issue "Connector '$fromId -> $toId' crosses node '$($nodeBox.Id)' in $Path" }
            }
        }

        $labels = New-Object System.Collections.Generic.List[object]
        foreach ($label in @($xml.SelectNodes("//*[@data-kind='connector-label']"))) {
            try {
                $box = [pscustomobject]@{
                    X = Get-Number $label 'data-x'
                    Y = Get-Number $label 'data-y'
                    Width = Get-Number $label 'data-width'
                    Height = Get-Number $label 'data-height'
                }
                $labels.Add($box)
                if (
                    $box.X -lt ($canvasX + 8) -or
                    $box.Y -lt ($canvasY + 8) -or
                    ($box.X + $box.Width) -gt ($canvasX + $canvasWidth - 8) -or
                    ($box.Y + $box.Height) -gt ($canvasY + $canvasHeight - 8)
                ) {
                    Add-Issue "Connector label is outside canvas bounds in $Path"
                }
                foreach ($nodeBox in $nodes) {
                    $overlap = (
                        $box.X -lt ($nodeBox.X + $nodeBox.Width) -and
                        ($box.X + $box.Width) -gt $nodeBox.X -and
                        $box.Y -lt ($nodeBox.Y + $nodeBox.Height) -and
                        ($box.Y + $box.Height) -gt $nodeBox.Y
                    )
                    if ($overlap) {
                        Add-Issue "Connector label overlaps node '$($nodeBox.Id)' in $Path"
                    }
                }
            } catch {
                Add-Issue "Invalid connector-label geometry in $Path`: $($_.Exception.Message)"
            }
        }
        for ($i = 0; $i -lt $labels.Count; $i++) {
            for ($j = $i + 1; $j -lt $labels.Count; $j++) {
                $a = $labels[$i]
                $b = $labels[$j]
                $overlap = (
                    $a.X -lt ($b.X + $b.Width) -and
                    ($a.X + $a.Width) -gt $b.X -and
                    $a.Y -lt ($b.Y + $b.Height) -and
                    ($a.Y + $a.Height) -gt $b.Y
                )
                if ($overlap) { Add-Issue "Connector labels overlap in $Path" }
            }
        }

        $bridgePoints = @(
            $xml.SelectNodes("//*[@data-kind='connector-bridge']") | ForEach-Object {
                [pscustomobject]@{
                    X = Get-Number $_ 'data-x'
                    Y = Get-Number $_ 'data-y'
                }
            }
        )
        for ($routeIndex = 0; $routeIndex -lt $connectorRoutes.Count; $routeIndex++) {
            $first = $connectorRoutes[$routeIndex]
            for ($otherIndex = $routeIndex + 1; $otherIndex -lt $connectorRoutes.Count; $otherIndex++) {
                $second = $connectorRoutes[$otherIndex]
                if (
                    $first.From -eq $second.From -or
                    $first.From -eq $second.To -or
                    $first.To -eq $second.From -or
                    $first.To -eq $second.To
                ) {
                    continue
                }
                for ($aIndex = 0; $aIndex -lt ($first.Points.Count - 1); $aIndex++) {
                    $a1 = $first.Points[$aIndex]
                    $a2 = $first.Points[$aIndex + 1]
                    for ($bIndex = 0; $bIndex -lt ($second.Points.Count - 1); $bIndex++) {
                        $b1 = $second.Points[$bIndex]
                        $b2 = $second.Points[$bIndex + 1]
                        $aVertical = [Math]::Abs($a1.X - $a2.X) -lt 0.01
                        $bVertical = [Math]::Abs($b1.X - $b2.X) -lt 0.01
                        if ($aVertical -eq $bVertical) { continue }
                        $vertical1 = if ($aVertical) { $a1 } else { $b1 }
                        $vertical2 = if ($aVertical) { $a2 } else { $b2 }
                        $horizontal1 = if ($aVertical) { $b1 } else { $a1 }
                        $horizontal2 = if ($aVertical) { $b2 } else { $a2 }
                        $crossX = $vertical1.X
                        $crossY = $horizontal1.Y
                        if (
                            $crossX -gt [Math]::Min($horizontal1.X, $horizontal2.X) -and
                            $crossX -lt [Math]::Max($horizontal1.X, $horizontal2.X) -and
                            $crossY -gt [Math]::Min($vertical1.Y, $vertical2.Y) -and
                            $crossY -lt [Math]::Max($vertical1.Y, $vertical2.Y)
                        ) {
                            $resolvedByBridge = @(
                                $bridgePoints | Where-Object {
                                    [Math]::Abs($_.X - $crossX) -lt 0.1 -and
                                    [Math]::Abs($_.Y - $crossY) -lt 0.1
                                }
                            ).Count -gt 0
                            if (-not $resolvedByBridge) {
                                Add-Issue "Connectors '$($first.From) -> $($first.To)' and '$($second.From) -> $($second.To)' cross without a bridge in $Path"
                            }
                        }
                    }
                }
            }
        }

        foreach ($textNode in @($xml.SelectNodes("//*[local-name()='text']"))) {
            $visibleText = [string]$textNode.InnerText
            if ([string]::IsNullOrWhiteSpace($visibleText)) {
                Add-Issue "Diagram contains an empty visible text element in $Path"
            } elseif ($visibleText.Trim() -match '(\.\.\.|…)$') {
                Add-Issue "Visible text is truncated with an ellipsis in $Path`: $($visibleText.Trim())"
            }
            $fontSize = 0.0
            if (
                -not [double]::TryParse(
                    $textNode.GetAttribute('font-size'),
                    [Globalization.NumberStyles]::Float,
                    $Invariant,
                    [ref]$fontSize
                ) -or $fontSize -lt 9
            ) {
                Add-Issue "Visible text uses an invalid or sub-9px font size in $Path`: $visibleText"
            }
        }
    }

    $lifelines = New-Object System.Collections.Generic.List[object]
    foreach ($node in @($xml.SelectNodes("//*[@data-kind='lifeline']"))) {
        try {
            $box = [pscustomobject]@{
                Id = $node.GetAttribute('data-component-id')
                X = Get-Number $node 'data-x'
                Y = Get-Number $node 'data-y'
                Width = Get-Number $node 'data-width'
                Height = Get-Number $node 'data-height'
            }
            $lifelines.Add($box)
            if ($box.X -lt ($canvasX + 24) -or ($box.X + $box.Width) -gt ($canvasX + $canvasWidth - 24)) {
                Add-Issue "Lifeline '$($box.Id)' is outside canvas margins in $Path"
            }
        } catch {
            Add-Issue "Invalid lifeline geometry in $Path`: $($_.Exception.Message)"
        }
    }
    foreach ($message in @($xml.SelectNodes("//*[@data-kind='message']"))) {
        $implementationMode = $message.GetAttribute('data-implementation-mode')
        if ($implementationMode -notin @('real', 'simulated', 'manual', 'deferred', 'blocked')) {
            Add-Issue "Sequence message has invalid or missing implementation mode in $Path"
        }
        if ($implementationMode -eq 'simulated' -and $message.InnerText -notmatch '(?i)simulat') {
            Add-Issue "Simulated sequence message is not visibly disclosed in $Path"
        }
    }
    for ($i = 0; $i -lt $lifelines.Count; $i++) {
        for ($j = $i + 1; $j -lt $lifelines.Count; $j++) {
            $a = $lifelines[$i]
            $b = $lifelines[$j]
            $overlap = $a.X -lt ($b.X + $b.Width) -and ($a.X + $a.Width) -gt $b.X -and $a.Y -lt ($b.Y + $b.Height) -and ($a.Y + $a.Height) -gt $b.Y
            if ($overlap) { Add-Issue "Lifeline headers '$($a.Id)' and '$($b.Id)' overlap in $Path" }
        }
    }
    return $xml
}

$saXml = Test-Svg $SolutionArchitecture 'SA_'
$sdXml = Test-Svg $SequenceDiagram 'SD_'

$saSlug = [IO.Path]::GetFileNameWithoutExtension($SolutionArchitecture) -replace '^SA_', ''
$sdSlug = [IO.Path]::GetFileNameWithoutExtension($SequenceDiagram) -replace '^SD_', ''
if ($saSlug -ne $sdSlug) { Add-Issue "Diagram slugs do not match: '$saSlug' and '$sdSlug'" }

if ($null -ne $saXml -and $null -ne $sdXml) {
    $saIds = @($saXml.SelectNodes("//*[@data-kind='node']") | ForEach-Object { $_.GetAttribute('data-component-id') })
    $sdIds = @($sdXml.SelectNodes("//*[@data-kind='lifeline']") | ForEach-Object { $_.GetAttribute('data-component-id') })
    foreach ($id in $sdIds) {
        if ($saIds -notcontains $id) { Add-Issue "Sequence lifeline '$id' has no matching architecture component." }
    }
}

$report = [ordered]@{
    validation = if ($issues.Count -eq 0) { 'passed' } else { 'failed' }
    issues = @($issues)
    solutionArchitecture = $SolutionArchitecture
    sequenceDiagram = $SequenceDiagram
    checkedAt = [DateTimeOffset]::Now.ToString('o')
}
[IO.File]::WriteAllText($OutputPath, ($report | ConvertTo-Json -Depth 6), $Utf8)
if ($issues.Count -gt 0) { throw "Diagram validation failed with $($issues.Count) issue(s). See $OutputPath" }
$report
