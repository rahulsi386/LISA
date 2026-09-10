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
$quality = $null

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

function Convert-Number([string]$Value) {
    $number = [double]::Parse($Value, [Globalization.NumberStyles]::Float, $Invariant)
    if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) { throw "Non-finite number '$Value'." }
    return $number
}

function Get-Number($Node, [string]$Name) {
    $raw = $Node.GetAttribute($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) { throw "Missing $Name on $($Node.Name)." }
    return Convert-Number $raw
}

function Read-UInt32BigEndian([byte[]]$Bytes, [int]$Offset) {
    if ($Offset -lt 0 -or $Offset + 4 -gt $Bytes.Length) { throw 'Truncated image header.' }
    return $Bytes[$Offset] * 16777216.0 + $Bytes[$Offset + 1] * 65536.0 +
        $Bytes[$Offset + 2] * 256.0 + $Bytes[$Offset + 3]
}

function Test-EmbeddedImage($Image, [string]$Path) {
    $href = $Image.GetAttribute('href')
    if ($href -notmatch '^data:image/(svg\+xml|png);base64,([A-Za-z0-9+/=]+)$') {
        Add-Issue "Image without an embedded SVG or PNG data URI in $Path"
        return
    }
    $format = $Matches[1]; $encoded = $Matches[2]
    try {
        if ($encoded.Length -gt 16MB) { throw 'Embedded image exceeds the size limit.' }
        $bytes = [Convert]::FromBase64String($encoded)
        if ((Get-Number $Image 'width') -le 0 -or (Get-Number $Image 'height') -le 0) {
            throw 'Image viewport dimensions must be positive.'
        }
        if ($format -eq 'png') {
            $signature = @(137, 80, 78, 71, 13, 10, 26, 10)
            if ($bytes.Length -lt 33) { throw 'Truncated PNG header.' }
            for ($i = 0; $i -lt $signature.Count; $i++) {
                if ($bytes[$i] -ne $signature[$i]) { throw 'Invalid PNG signature.' }
            }
            if ((Read-UInt32BigEndian $bytes 8) -ne 13 -or [Text.Encoding]::ASCII.GetString($bytes, 12, 4) -cne 'IHDR') {
                throw 'Invalid PNG dimension header.'
            }
            $crc = [uint32]4294967295
            for ($i = 12; $i -lt 29; $i++) {
                $crc = $crc -bxor $bytes[$i]
                for ($bit = 0; $bit -lt 8; $bit++) {
                    if ($crc -band 1) { $crc = ($crc -shr 1) -bxor [uint32]3988292384 }
                    else { $crc = $crc -shr 1 }
                }
            }
            if (($crc -bxor [uint32]4294967295) -ne (Read-UInt32BigEndian $bytes 29)) {
                throw 'PNG dimension header checksum failed.'
            }
            $width = Read-UInt32BigEndian $bytes 16
            $height = Read-UInt32BigEndian $bytes 20
        } else {
            $settings = New-Object System.Xml.XmlReaderSettings
            $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
            $settings.XmlResolver = $null
            $settings.MaxCharactersInDocument = 8MB
            $stream = [IO.MemoryStream]::new($bytes, $false)
            $reader = $null
            try {
                $reader = [Xml.XmlReader]::Create($stream, $settings)
                $document = New-Object System.Xml.XmlDocument
                $document.XmlResolver = $null
                $document.Load($reader)
            } finally {
                if ($null -ne $reader) { $reader.Dispose() }
                $stream.Dispose()
            }
            $root = $document.DocumentElement
            if ($null -eq $root -or $root.LocalName -ne 'svg') { throw 'Embedded SVG has no svg root.' }
            if ($root.HasAttribute('viewBox')) {
                $parts = @($root.GetAttribute('viewBox') -split '[,\s]+' | Where-Object { $_ })
                if ($parts.Count -ne 4) { throw 'Invalid embedded SVG viewBox.' }
                $null = Convert-Number $parts[0]; $null = Convert-Number $parts[1]
                $width = Convert-Number $parts[2]; $height = Convert-Number $parts[3]
            } else {
                $width = Convert-Number ($root.GetAttribute('width') -replace 'px$', '')
                $height = Convert-Number ($root.GetAttribute('height') -replace 'px$', '')
            }
        }
        if ($width -le 0 -or $height -le 0 -or $width -gt 32768 -or $height -gt 32768 -or $width * $height -gt 100000000) {
            throw 'Image intrinsic dimensions are invalid or exceed the supported limit.'
        }
    } catch { Add-Issue "Invalid embedded image in $Path`: $($_.Exception.Message)" }
}

function Get-Identity($Node) {
    foreach ($name in @('data-component-id', 'data-id', 'id')) {
        if ($Node.HasAttribute($name)) { return $Node.GetAttribute($name) }
    }
    return ''
}

function Test-Spacer($Node) {
    return $Node.GetAttribute('data-kind') -eq 'text-box' -and
        $Node.InnerText.Length -gt 0 -and [string]::IsNullOrWhiteSpace($Node.InnerText) -and
        (Get-Number $Node 'data-width') -eq 0 -and (Get-Number $Node 'data-height') -ge 0
}

function Get-Box($Node) {
    $box = [pscustomobject]@{
        Id = Get-Identity $Node
        Owner = $Node.GetAttribute('data-owner')
        Kind = $Node.GetAttribute('data-kind')
        Element = $Node
        X = Get-Number $Node 'data-x'
        Y = Get-Number $Node 'data-y'
        Width = Get-Number $Node 'data-width'
        Height = Get-Number $Node 'data-height'
    }
    if (($box.Width -le 0 -or $box.Height -le 0) -and -not (Test-Spacer $Node)) {
        throw 'Box dimensions must be positive (except zero-width whitespace text).'
    }
    return $box
}

function Test-Overlap($A, $B, [double]$Padding = 0) {
    return $A.X -lt ($B.X + $B.Width + $Padding) -and ($A.X + $A.Width) -gt ($B.X - $Padding) -and
        $A.Y -lt ($B.Y + $B.Height + $Padding) -and ($A.Y + $A.Height) -gt ($B.Y - $Padding)
}

function Test-Contained($Inner, $Outer, [double]$Margin = 0) {
    return $Inner.X -ge ($Outer.X + $Margin) -and $Inner.Y -ge ($Outer.Y + $Margin) -and
        ($Inner.X + $Inner.Width) -le ($Outer.X + $Outer.Width - $Margin) -and
        ($Inner.Y + $Inner.Height) -le ($Outer.Y + $Outer.Height - $Margin)
}

function Test-SegmentBox($A, $B, $Box, [double]$Padding = 0) {
    $left = $Box.X - $Padding; $right = $Box.X + $Box.Width + $Padding
    $top = $Box.Y - $Padding; $bottom = $Box.Y + $Box.Height + $Padding
    if ([Math]::Abs($A.X - $B.X) -lt 0.01) {
        return $A.X -ge $left -and $A.X -le $right -and
            [Math]::Max($A.Y, $B.Y) -ge $top -and [Math]::Min($A.Y, $B.Y) -le $bottom
    }
    if ([Math]::Abs($A.Y - $B.Y) -lt 0.01) {
        return $A.Y -ge $top -and $A.Y -le $bottom -and
            [Math]::Max($A.X, $B.X) -ge $left -and [Math]::Min($A.X, $B.X) -le $right
    }
    return $false
}

function Get-SegmentDistance($A, $B, $Box) {
    $dx = [Math]::Max(0, [Math]::Max($Box.X - [Math]::Max($A.X, $B.X), [Math]::Min($A.X, $B.X) - $Box.X - $Box.Width))
    $dy = [Math]::Max(0, [Math]::Max($Box.Y - [Math]::Max($A.Y, $B.Y), [Math]::Min($A.Y, $B.Y) - $Box.Y - $Box.Height))
    return [Math]::Sqrt($dx * $dx + $dy * $dy)
}

function Test-Anchored($Point, $Box) {
    return (($Point.X -ge ($Box.X - 1) -and $Point.X -le ($Box.X + $Box.Width + 1)) -and
        ([Math]::Min([Math]::Abs($Point.Y - $Box.Y), [Math]::Abs($Point.Y - $Box.Y - $Box.Height)) -le 1)) -or
        (($Point.Y -ge ($Box.Y - 1) -and $Point.Y -le ($Box.Y + $Box.Height + 1)) -and
        ([Math]::Min([Math]::Abs($Point.X - $Box.X), [Math]::Abs($Point.X - $Box.X - $Box.Width)) -le 1))
}

function Test-Descendant($Child, $Parent) {
    for ($current = $Child; $null -ne $current; $current = $current.ParentNode) {
        if ([object]::ReferenceEquals($current, $Parent)) { return $true }
    }
    return $false
}

function Get-Presentation($Node, [string]$Name, [string]$Default = '') {
    for ($current = $Node; $null -ne $current -and $current -is [System.Xml.XmlElement]; $current = $current.ParentNode) {
        $style = $current.GetAttribute('style')
        $pattern = '(?:^|;)\s*' + [regex]::Escape($Name) + '\s*:\s*([^;]+)'
        if ($style -match $pattern) { return $Matches[1].Trim() }
        if ($current.HasAttribute($Name)) { return $current.GetAttribute($Name) }
    }
    return $Default
}

function Test-Visible($Node) {
    for ($current = $Node; $null -ne $current -and $current -is [System.Xml.XmlElement]; $current = $current.ParentNode) {
        if ((Get-Presentation $current 'display') -eq 'none' -or
            (Get-Presentation $current 'visibility') -in @('hidden', 'collapse') -or
            (Get-Presentation $current 'opacity') -match '^0(?:\.0*)?$') { return $false }
    }
    return $true
}

function Read-Route($Node) {
    $points = New-Object System.Collections.Generic.List[object]
    foreach ($pointText in @($Node.GetAttribute('data-route') -split ';' | Where-Object { $_ })) {
        $coordinates = @($pointText -split ',')
        if ($coordinates.Count -ne 2) { throw "Invalid route point '$pointText'." }
        $points.Add([pscustomobject]@{ X = Convert-Number $coordinates[0]; Y = Convert-Number $coordinates[1] })
    }
    if ($points.Count -lt 2) { throw 'Route must contain at least two points.' }
    return ,$points
}

function Test-Arrow($Route, $Xml, [string]$Path) {
    $paths = @($Route.Element.SelectNodes("./*[local-name()='path']"))
    if ($paths.Count -eq 0) { Add-Issue "Route '$($Route.Id)' has no visible path in $Path"; return }
    foreach ($line in $paths) {
        if (-not (Test-Visible $line) -or (Get-Presentation $line 'stroke' 'none') -in @('none', 'transparent') -or
            (Get-Presentation $line 'stroke-opacity' '1') -match '^0(?:\.0*)?$' -or
            (Get-Presentation $line 'stroke-width' '1') -match '^0(?:\.0*)?(?:px)?$') {
            Add-Issue "Route '$($Route.Id)' has an invisible stroke in $Path"
        }
        $bidirectional = $Route.Element.GetAttribute('data-direction') -ceq 'bidirectional'
        $markerAttributes = @('marker-end')
        if ($bidirectional) { $markerAttributes += 'marker-start' }
        elseif ((Get-Presentation $line 'marker-start' 'none') -ne 'none') {
            Add-Issue "Unidirectional route '$($Route.Id)' has an unexpected start arrowhead in $Path"
        }
        foreach ($markerAttribute in $markerAttributes) {
            $reference = Get-Presentation $line $markerAttribute
            if ($reference -notmatch '^url\(#([A-Za-z0-9_.:-]+)\)$') {
                Add-Issue "Route '$($Route.Id)' has no valid arrowhead reference ($markerAttribute) in $Path"; continue
            }
            $marker = $Xml.SelectSingleNode("//*[local-name()='marker' and @id='$($Matches[1])']")
            if ($null -eq $marker) { Add-Issue "Route '$($Route.Id)' references a missing arrowhead in $Path"; continue }
            try {
                if ($markerAttribute -eq 'marker-start') {
                    $reverseShape = @($marker.SelectNodes("./*[local-name()='path']") |
                        Where-Object { ($_.GetAttribute('d') -replace '\s', '') -ceq 'M91L15L99Z' })
                    if ($marker.GetAttribute('orient') -cne 'auto' -or (Get-Number $marker 'refX') -ne 1 -or
                        (Get-Number $marker 'refY') -ne 5 -or $reverseShape.Count -ne 1) {
                        throw 'Start arrowhead does not point toward the source endpoint.'
                    }
                }
                if (-not (Test-Visible $marker) -or (Get-Number $marker 'markerWidth') -le 0 -or
                    (Get-Number $marker 'markerHeight') -le 0) { throw 'Invisible marker dimensions.' }
                $shapes = @($marker.SelectNodes(".//*[local-name()='path' or local-name()='polygon' or local-name()='polyline']"))
                $painted = @($shapes | Where-Object {
                    (Test-Visible $_) -and (
                        ((Get-Presentation $_ 'fill' 'black') -notin @('none', 'transparent') -and (Get-Presentation $_ 'fill-opacity' '1') -notmatch '^0(?:\.0*)?$') -or
                        ((Get-Presentation $_ 'stroke' 'none') -notin @('none', 'transparent') -and (Get-Presentation $_ 'stroke-opacity' '1') -notmatch '^0(?:\.0*)?$'))
                })
                if ($painted.Count -eq 0) { throw 'Arrowhead has no painted shape.' }
            } catch { Add-Issue "Route '$($Route.Id)' has an invisible arrowhead in $Path`: $($_.Exception.Message)" }
        }
        # Straight orthogonal paths must match the metadata actually validated.
        $d = $line.GetAttribute('d')
        if ($d -match '^\s*[Mm][\d\s.,+\-eELl]+$') {
            $numbers = @([regex]::Matches($d, '[-+]?(?:\d*\.?\d+)(?:[eE][-+]?\d+)?') | ForEach-Object { Convert-Number $_.Value })
            if ($d -cmatch '[ml]' -or $numbers.Count -ne ($Route.Points.Count * 2)) {
                Add-Issue "Route '$($Route.Id)' rendered path differs from route metadata in $Path"
            } else {
                for ($i = 0; $i -lt $Route.Points.Count; $i++) {
                    if ([Math]::Abs($numbers[$i * 2] - $Route.Points[$i].X) -gt 0.1 -or
                        [Math]::Abs($numbers[$i * 2 + 1] - $Route.Points[$i].Y) -gt 0.1) {
                        Add-Issue "Route '$($Route.Id)' rendered path differs from route metadata in $Path"
                    }
                }
            }
        } else { Add-Issue "Route '$($Route.Id)' must render an explicit orthogonal M/L path in $Path" }
    }
}

function Test-Svg([string]$Path, [string]$ExpectedPrefix) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Add-Issue "Missing diagram: $Path"; return $null }
    if ([IO.Path]::GetFileName($Path) -notmatch ('^' + [regex]::Escape($ExpectedPrefix) + '[A-Za-z0-9_]+\.svg$')) {
        Add-Issue "Invalid filename: $([IO.Path]::GetFileName($Path))"
    }
    try {
        $xml = New-Object System.Xml.XmlDocument
        $xml.PreserveWhitespace = $true
        $xml.LoadXml((Get-Content -LiteralPath $Path -Encoding UTF8 -Raw))
    } catch { Add-Issue "XML parse failed for $Path`: $($_.Exception.Message)"; return $null }
    $root = $xml.DocumentElement
    if ($null -eq $root -or $root.LocalName -ne 'svg') { Add-Issue "Root element is not svg: $Path"; return $null }
    try {
        $parts = @($root.GetAttribute('viewBox') -split '[,\s]+' | Where-Object { $_ })
        if ($parts.Count -ne 4) { throw 'Invalid viewBox.' }
        $canvas = [pscustomobject]@{
            X = Convert-Number $parts[0]; Y = Convert-Number $parts[1]
            Width = Convert-Number $parts[2]; Height = Convert-Number $parts[3]
        }
        if ($canvas.Width -le 0 -or $canvas.Height -le 0) { throw 'Non-positive canvas size.' }
    } catch { Add-Issue "Invalid canvas in $Path`: $($_.Exception.Message)"; return $xml }
    $seenIds = @{}
    foreach ($node in @($xml.SelectNodes('//*[@id]'))) {
        $id = $node.GetAttribute('id')
        if ($seenIds.ContainsKey($id)) { Add-Issue "Duplicate id '$id' in $Path" } else { $seenIds[$id] = $true }
    }
    foreach ($image in @($xml.SelectNodes("//*[local-name()='image']"))) {
        Test-EmbeddedImage $image $Path
    }
    $legends = @($xml.SelectNodes("//*[@data-kind='legend']"))
    if ($legends.Count -ne 1 -or ($legends.Count -eq 1 -and -not (Test-Visible $legends[0]))) {
        Add-Issue "Diagram must contain exactly one visible legend: $Path"
    } elseif (@($legends[0].SelectNodes(".//*[local-name()='text']") | Where-Object {
        (Test-Visible $_) -and -not [string]::IsNullOrWhiteSpace($_.InnerText)
    }).Count -eq 0) {
        Add-Issue "Diagram legend has no visible explanation: $Path"
    }

    $containers = @{}; $cards = @{}; $regions = @{}
    foreach ($element in @($xml.SelectNodes("//*[@data-kind='container' or @data-kind='semantic-layer' or @data-kind='node' or @data-kind='lifeline' or @data-kind='phase' or @data-kind='fragment']"))) {
        try {
            $box = Get-Box $element
            if ([string]::IsNullOrWhiteSpace($box.Id)) { throw "Missing ID for $($box.Kind)." }
            if (-not (Test-Contained $box $canvas 24)) { Add-Issue "$($box.Kind) '$($box.Id)' is outside canvas margins in $Path" }
            switch ($box.Kind) {
                { $_ -in @('container', 'semantic-layer') } {
                    if ($containers.ContainsKey($box.Id)) { Add-Issue "Duplicate container '$($box.Id)' in $Path" }
                    $containers[$box.Id] = $box
                    if ($box.Kind -eq 'container' -and (Get-Number $element 'data-header-height') -le 0) {
                        throw 'Invalid container header height.'
                    }
                    if ($box.Kind -eq 'semantic-layer' -and $box.Id -notin @('users', 'channels', 'agent-platform', 'data-integration', 'governance', 'monitoring')) {
                        throw 'Invalid semantic layer.'
                    }
                }
                { $_ -in @('node', 'lifeline') } {
                    if ($cards.ContainsKey($box.Id)) { Add-Issue "Duplicate component '$($box.Id)' in $Path" }
                    $cards[$box.Id] = $box
                }
                default { $regions[$box.Id] = $box }
            }
        } catch { Add-Issue "Invalid element geometry in $Path`: $($_.Exception.Message)" }
    }
    $cardList = @($cards.Values)
    foreach ($box in $cardList) {
        $node = $box.Element
        if ($box.Kind -eq 'lifeline') {
            try {
                $line = $node.SelectSingleNode(".//*[@data-kind='lifeline-line']")
                if ($null -eq $line) { $line = $node.SelectSingleNode("./*[local-name()='line']") }
                if ($null -eq $line) { throw 'Missing lifeline line.' }
                $center = $box.X + $box.Width / 2
                $x1 = Get-Number $line 'x1'; $x2 = Get-Number $line 'x2'
                $y1 = Get-Number $line 'y1'; $y2 = Get-Number $line 'y2'
                if ([Math]::Abs($x1 - $center) -gt 1 -or [Math]::Abs($x2 - $center) -gt 1 -or
                    [Math]::Abs($y1 - $box.Y - $box.Height) -gt 1 -or $y2 -le $y1 -or
                    $y2 -gt ($canvas.Y + $canvas.Height - 4)) { throw 'Lifeline does not match its header or canvas bounds.' }
            } catch { Add-Issue "Invalid lifeline '$($box.Id)' geometry in $Path`: $($_.Exception.Message)" }
            continue
        }
        $parentId = $node.GetAttribute('data-parent')
        $kind = $node.GetAttribute('data-component-kind')
        if ($node.GetAttribute('data-implementation-status') -notin @('build', 'configure', 'simulate', 'static-sample-data', 'manual-handoff', 'defer', 'block', 'existing')) {
            Add-Issue "Node '$($box.Id)' has invalid or missing implementation status in $Path"
        }
        if ($kind -eq 'actor' -and $parentId -ne 'users') { Add-Issue "Actor '$($box.Id)' must be in the users layer in $Path" }
        if ($kind -eq 'channel' -and $parentId -ne 'channels') { Add-Issue "Channel '$($box.Id)' must be in the channels layer in $Path" }
        $memberCount = 0
        if (-not [int]::TryParse($node.GetAttribute('data-members-count'), [ref]$memberCount) -or $memberCount -lt 0) {
            Add-Issue "Node '$($box.Id)' has invalid data-members-count in $Path"
        } else {
            $members = @($node.SelectNodes(".//*[@data-kind='member']"))
            if ($members.Count -ne $memberCount) { Add-Issue "Node '$($box.Id)' does not visibly render all grouped members in $Path" }
            foreach ($member in $members) {
                if ([string]::IsNullOrWhiteSpace($member.GetAttribute('data-name')) -or -not (Test-Visible $member) -or
                    [string]::IsNullOrWhiteSpace($member.InnerText)) { Add-Issue "Node '$($box.Id)' contains an unnamed or invisible grouped member in $Path" }
            }
        }
        if (-not $containers.ContainsKey($parentId)) { Add-Issue "Node '$($box.Id)' has unknown parent '$parentId' in $Path" } else {
            $parent = $containers[$parentId]
            try {
                $headerHeight = if ($parent.Kind -eq 'semantic-layer') { 24 } else { Get-Number $parent.Element 'data-header-height' }
                if ($box.X -lt ($parent.X + 24) -or $box.Y -lt ($parent.Y + $headerHeight) -or
                    ($box.X + $box.Width) -gt ($parent.X + $parent.Width - 24) -or ($box.Y + $box.Height) -gt ($parent.Y + $parent.Height - 16)) {
                    Add-Issue "Node '$($box.Id)' is outside parent bounds in $Path"
                }
            } catch { Add-Issue "Invalid parent geometry in $Path" }
        }
    }
    for ($i = 0; $i -lt $cardList.Count; $i++) {
        for ($j = $i + 1; $j -lt $cardList.Count; $j++) {
            if (Test-Overlap $cardList[$i] $cardList[$j]) { Add-Issue "Cards '$($cardList[$i].Id)' and '$($cardList[$j].Id)' overlap in $Path" }
        }
    }

    $routes = New-Object System.Collections.Generic.List[object]
    $routeById = @{}
    foreach ($element in @($xml.SelectNodes("//*[@data-kind='connector' or @data-kind='message']"))) {
        $kind = $element.GetAttribute('data-kind')
        $from = $element.GetAttribute('data-from'); $to = $element.GetAttribute('data-to')
        $mode = $element.GetAttribute('data-implementation-mode')
        if ($mode -notin @('real', 'simulated', 'manual', 'deferred', 'blocked')) {
            Add-Issue "$kind '$from -> $to' has invalid or missing implementation mode in $Path"
        }
        if ($kind -eq 'message' -and $mode -eq 'simulated' -and $element.InnerText -notmatch '(?i)simulat') {
            Add-Issue "Simulated sequence message is not visibly disclosed in $Path"
        }
        try {
            $id = Get-Identity $element
            if (-not $id) { $id = "$kind-$($routes.Count)" }
            $route = [pscustomobject]@{ Id = $id; Kind = $kind; From = $from; To = $to; Element = $element; Points = Read-Route $element }
            $routes.Add($route)
            if ($routeById.ContainsKey($id)) { Add-Issue "Duplicate route '$id' in $Path" }
            $routeById[$id] = $route
            Test-Arrow $route $xml $Path
            foreach ($pair in @(@($from, $route.Points[0]), @($to, $route.Points[$route.Points.Count - 1]))) {
                $componentId = $pair[0]; $point = $pair[1]
                if (-not $cards.ContainsKey($componentId)) { Add-Issue "Route '$id' references unknown component '$componentId' in $Path"; continue }
                $card = $cards[$componentId]
                if ($kind -eq 'connector') {
                    if (-not (Test-Anchored $point $card)) { Add-Issue "Connector '$id' endpoint is not anchored to '$componentId' within 1px in $Path" }
                } else {
                    $lifeline = $card.Element.SelectSingleNode(".//*[@data-kind='lifeline-line']")
                    if ($null -eq $lifeline) { $lifeline = $card.Element.SelectSingleNode("./*[local-name()='line']") }
                    if ($null -eq $lifeline -or [Math]::Abs($point.X - $card.X - $card.Width / 2) -gt 1) {
                        Add-Issue "Message '$id' endpoint is not anchored to lifeline '$componentId' in $Path"
                    } elseif ($point.Y -lt (Get-Number $lifeline 'y1') -or $point.Y -gt (Get-Number $lifeline 'y2')) {
                        Add-Issue "Message '$id' endpoint exceeds lifeline '$componentId' bounds in $Path"
                    }
                }
            }
            if ($kind -eq 'message' -and $from -eq $to -and
                ($route.Points.Count -lt 4 -or $route.Points[$route.Points.Count - 1].Y -le $route.Points[0].Y)) {
                Add-Issue "Self-message '$id' has invalid loop bounds in $Path"
            }
            for ($i = 1; $i -lt $route.Points.Count; $i++) {
                $a = $route.Points[$i - 1]; $b = $route.Points[$i]
                if ([Math]::Abs($a.X - $b.X) -gt 0.01 -and [Math]::Abs($a.Y - $b.Y) -gt 0.01) {
                    Add-Issue "Route '$id' contains a non-orthogonal segment in $Path"
                }
                if ([Math]::Abs($a.X - $b.X) -lt 0.01 -and [Math]::Abs($a.Y - $b.Y) -lt 0.01) {
                    Add-Issue "Route '$id' contains a zero-length segment in $Path"
                }
                foreach ($point in @($a, $b)) {
                    if ($point.X -lt ($canvas.X + 4) -or $point.Y -lt ($canvas.Y + 4) -or
                        $point.X -gt ($canvas.X + $canvas.Width - 4) -or $point.Y -gt ($canvas.Y + $canvas.Height - 4)) {
                        Add-Issue "Route '$id' is outside canvas bounds in $Path"
                    }
                }
                foreach ($card in $cardList) {
                    $padding = if ($kind -eq 'connector' -and $card.Id -in @($from, $to)) { -0.1 } else { 1 }
                    if (Test-SegmentBox $a $b $card $padding) { Add-Issue "Route '$id' crosses card '$($card.Id)' in $Path" }
                }
            }
        } catch { Add-Issue "Invalid $kind route in $Path`: $($_.Exception.Message)" }
    }

    $textBoxes = New-Object System.Collections.Generic.List[object]
    foreach ($element in @($xml.SelectNodes("//*[@data-kind='text-box']"))) {
        if (-not (Test-Visible $element)) { continue }
        try {
            $box = Get-Box $element
            if (Test-Spacer $element) { continue }
            $textBoxes.Add($box)
            if (-not $box.Owner) { Add-Issue "Text box has no owner metadata in $Path" }
            if (-not (Test-Contained $box $canvas 4)) { Add-Issue "Text '$($element.InnerText)' is outside canvas bounds in $Path" }
            if (@($element.SelectNodes(".//*[local-name()='text']")).Count -eq 0) { Add-Issue "Text box has no rendered text in $Path" }
            foreach ($card in $cardList) {
                if ($box.Owner -eq $card.Id -and (Test-Descendant $element $card.Element)) {
                    if (-not (Test-Contained $box $card)) { Add-Issue "Text '$($element.InnerText)' exceeds its own card '$($card.Id)' in $Path" }
                } elseif (Test-Overlap $box $card) { Add-Issue "Text '$($element.InnerText)' overlaps unrelated card '$($card.Id)' in $Path" }
            }
            foreach ($route in $routes) {
                for ($i = 1; $i -lt $route.Points.Count; $i++) {
                    if (Test-SegmentBox $route.Points[$i - 1] $route.Points[$i] $box 2) {
                        Add-Issue "Route '$($route.Id)' crosses text '$($element.InnerText)' in $Path"
                    }
                }
            }
        } catch { Add-Issue "Invalid text-box geometry in $Path`: $($_.Exception.Message)" }
    }
    for ($i = 0; $i -lt $textBoxes.Count; $i++) {
        for ($j = $i + 1; $j -lt $textBoxes.Count; $j++) {
            if (Test-Overlap $textBoxes[$i] $textBoxes[$j]) {
                Add-Issue "Visible text overlaps: '$($textBoxes[$i].Element.InnerText)' / '$($textBoxes[$j].Element.InnerText)' in $Path"
            }
        }
    }
    # Typography must run once for every diagram, including sequences without connectors.
    foreach ($text in @($xml.SelectNodes("//*[local-name()='text' and not(ancestor::*[local-name()='defs'])]"))) {
        if (-not (Test-Visible $text)) { continue }
        $value = [string]$text.InnerText
        $wrapper = $text.SelectSingleNode("ancestor::*[@data-kind='text-box'][1]")
        if ($null -ne $wrapper) {
            try { if (Test-Spacer $wrapper) { continue } } catch { }
        }
        if ([string]::IsNullOrWhiteSpace($value)) { Add-Issue "Diagram contains an empty visible text element in $Path" }
        if ($value.Trim() -match '(\.\.\.|\u2026)$') { Add-Issue "Visible text is truncated with an ellipsis in $Path`: $($value.Trim())" }
        if ($null -eq $wrapper) { Add-Issue "Visible text lacks measured text-box geometry in $Path`: $value" }
        $role = $text.GetAttribute('data-role')
        if (-not $role -and $null -ne $wrapper) { $role = $wrapper.GetAttribute('data-role') }
        $minimum = switch ($role) {
            { $_ -in @('title', 'diagram-title') } { 20; break }
            { $_ -in @('product-title', 'card-title', 'participant-title', 'header', 'role-header', 'section-title', 'phase-title') } { 14; break }
            default { 11 }
        }
        # Legacy cards have no role tag. Their first visible text is the product
        # heading; explicit role tags protect every line in newer renderers.
        $cardElement = $text.SelectSingleNode("ancestor::*[@data-kind='node' or @data-kind='lifeline'][1]")
        if ($null -ne $cardElement) {
            $firstText = @($cardElement.SelectNodes(".//*[local-name()='text']") | Where-Object { Test-Visible $_ }) | Select-Object -First 1
            if ([object]::ReferenceEquals($firstText, $text)) { $minimum = [Math]::Max(14, $minimum) }
        }
        foreach ($span in @($text) + @($text.SelectNodes(".//*[local-name()='tspan']"))) {
            try {
                $size = Convert-Number ((Get-Presentation $span 'font-size') -replace 'px$', '')
                if ($size -lt $minimum) { throw "Font size $size is below $minimum." }
            } catch { Add-Issue "Visible text uses an invalid or sub-${minimum}px font size in $Path`: $value" }
        }
    }

    $labels = New-Object System.Collections.Generic.List[object]
    foreach ($element in @($xml.SelectNodes("//*[@data-kind='connector-label' or @data-kind='message-label']"))) {
        try {
            $box = Get-Box $element; $labels.Add($box)
            if (-not (Test-Contained $box $canvas 8)) { Add-Issue "Connector label is outside canvas bounds in $Path" }
            foreach ($card in $cardList) {
                if (Test-Overlap $box $card 2) { Add-Issue "Connector label overlaps node '$($card.Id)' in $Path" }
            }
            foreach ($textBox in $textBoxes) {
                if (Test-Descendant $textBox.Element $element) {
                    if (-not (Test-Contained $textBox $box)) { Add-Issue "Connector label text exceeds its background bounds in $Path" }
                } elseif (Test-Overlap $box $textBox 1) {
                    Add-Issue "Connector label overlaps unrelated text '$($textBox.Element.InnerText)' in $Path"
                }
            }
            $ownerRoute = $null
            if ($box.Owner -and $routeById.ContainsKey($box.Owner)) { $ownerRoute = $routeById[$box.Owner] }
            if ($null -eq $ownerRoute) {
                foreach ($route in $routes) {
                    if (Test-Descendant $element $route.Element) { $ownerRoute = $route; break }
                }
            }
            if ($null -eq $ownerRoute) { Add-Issue "Connector label '$($box.Id)' has no matching route owner in $Path" }
            $distance = [double]::PositiveInfinity
            foreach ($route in $routes) {
                for ($i = 1; $i -lt $route.Points.Count; $i++) {
                    $a = $route.Points[$i - 1]; $b = $route.Points[$i]
                    if (Test-SegmentBox $a $b $box 3.99) {
                        Add-Issue "Connector label '$($box.Id)' crosses route '$($route.Id)' or its 4px clearance in $Path"
                    }
                    if ($null -ne $ownerRoute -and $ownerRoute.Id -eq $route.Id) {
                        $distance = [Math]::Min($distance, (Get-SegmentDistance $a $b $box))
                    }
                }
            }
            if ($null -ne $ownerRoute -and $distance -gt 24.1) { Add-Issue "Connector label '$($box.Id)' floats more than 24px from its route in $Path" }
        } catch { Add-Issue "Invalid connector-label geometry in $Path`: $($_.Exception.Message)" }
    }
    for ($i = 0; $i -lt $labels.Count; $i++) {
        for ($j = $i + 1; $j -lt $labels.Count; $j++) {
            if (Test-Overlap $labels[$i] $labels[$j] 2) { Add-Issue "Connector labels overlap in $Path" }
        }
    }

    foreach ($region in $regions.Values) {
        $headings = @($textBoxes | Where-Object { $_.Owner -eq $region.Id })
        if ($headings.Count -eq 0) { Add-Issue "$($region.Kind) '$($region.Id)' has no visible heading in $Path"; continue }
        $headerBottom = $region.Y
        foreach ($heading in $headings) {
            if (-not (Test-Contained $heading $region)) { Add-Issue "$($region.Kind) heading exceeds its bounds in $Path" }
            $headerBottom = [Math]::Max($headerBottom, $heading.Y + $heading.Height + 4)
        }
        $reserved = [pscustomobject]@{ X = $region.X; Y = $region.Y; Width = $region.Width; Height = $headerBottom - $region.Y }
        foreach ($label in $labels) {
            if (Test-Overlap $label $reserved) { Add-Issue "Message label overlaps reserved $($region.Kind) heading row in $Path" }
        }
        foreach ($other in $textBoxes) {
            if ($other.Owner -ne $region.Id -and (Test-Overlap $other $reserved)) {
                Add-Issue "Text overlaps reserved $($region.Kind) heading row in $Path"
            }
        }
        foreach ($route in $routes) {
            for ($i = 1; $i -lt $route.Points.Count; $i++) {
                if (Test-SegmentBox $route.Points[$i - 1] $route.Points[$i] $reserved) {
                    Add-Issue "Message overlaps reserved $($region.Kind) heading row in $Path"
                }
            }
        }
    }

    $bridges = New-Object System.Collections.Generic.List[object]
    foreach ($bridge in @($xml.SelectNodes("//*[@data-kind='connector-bridge']"))) {
        try { $bridges.Add([pscustomobject]@{ X = Get-Number $bridge 'data-x'; Y = Get-Number $bridge 'data-y' }) }
        catch { Add-Issue "Invalid connector bridge geometry in $Path" }
    }
    $connectors = @($routes | Where-Object Kind -eq 'connector')
    for ($i = 0; $i -lt $connectors.Count; $i++) {
        for ($j = $i + 1; $j -lt $connectors.Count; $j++) {
            $first = $connectors[$i]; $second = $connectors[$j]
            if ($first.From -in @($second.From, $second.To) -or $first.To -in @($second.From, $second.To)) { continue }
            for ($a = 1; $a -lt $first.Points.Count; $a++) {
                for ($b = 1; $b -lt $second.Points.Count; $b++) {
                    $a1 = $first.Points[$a - 1]; $a2 = $first.Points[$a]
                    $b1 = $second.Points[$b - 1]; $b2 = $second.Points[$b]
                    $av = [Math]::Abs($a1.X - $a2.X) -lt 0.01
                    $bv = [Math]::Abs($b1.X - $b2.X) -lt 0.01
                    if ($av -eq $bv) { continue }
                    $v1 = if ($av) { $a1 } else { $b1 }; $v2 = if ($av) { $a2 } else { $b2 }
                    $h1 = if ($av) { $b1 } else { $a1 }; $h2 = if ($av) { $b2 } else { $a2 }
                    if ($v1.X -gt [Math]::Min($h1.X, $h2.X) -and $v1.X -lt [Math]::Max($h1.X, $h2.X) -and
                        $h1.Y -gt [Math]::Min($v1.Y, $v2.Y) -and $h1.Y -lt [Math]::Max($v1.Y, $v2.Y)) {
                        if (@($bridges | Where-Object { [Math]::Abs($_.X - $v1.X) -lt 0.1 -and [Math]::Abs($_.Y - $h1.Y) -lt 0.1 }).Count -eq 0) {
                            Add-Issue "Connectors '$($first.Id)' and '$($second.Id)' cross without a bridge in $Path"
                        }
                    }
                }
            }
        }
    }
    return $xml
}

function Invoke-Validation([string]$Path, [string]$Prefix) {
    try { return Test-Svg $Path $Prefix }
    catch { Add-Issue "Diagram validation could not complete for $Path`: $($_.Exception.Message)"; return $null }
}

$saXml = Invoke-Validation $SolutionArchitecture 'SA_'
$sdXml = Invoke-Validation $SequenceDiagram 'SD_'
$saSlug = [IO.Path]::GetFileNameWithoutExtension($SolutionArchitecture) -replace '^SA_', ''
$sdSlug = [IO.Path]::GetFileNameWithoutExtension($SequenceDiagram) -replace '^SD_', ''
if ($saSlug -ne $sdSlug) { Add-Issue "Diagram slugs do not match: '$saSlug' and '$sdSlug'" }
if ($null -ne $saXml -and $null -ne $sdXml) {
    $saIds = @($saXml.SelectNodes("//*[@data-kind='node']") | ForEach-Object { $_.GetAttribute('data-component-id') })
    foreach ($annotation in @($saXml.SelectNodes("//*[@data-kind='control-annotation']"))) {
        $from = $annotation.GetAttribute('data-from'); $to = $annotation.GetAttribute('data-to')
        $mode = $annotation.GetAttribute('data-implementation-mode')
        $style = $annotation.GetAttribute('data-style')
        $identity = $annotation.GetAttribute('data-id')
        $visible = ($annotation.InnerText -replace '\s', '')
        if ($from -notin $saIds -or $to -notin $saIds -or -not $identity -or
            $mode -notin @('real', 'simulated', 'manual', 'deferred', 'blocked') -or
            $style -notin @('call', 'response', 'optional', 'tbd') -or -not (Test-Visible $annotation)) {
            Add-Issue "Invalid scoped control relationship '$identity'."
        }
        foreach ($required in @($identity, $from, $to, $mode, $style, $annotation.GetAttribute('data-label'))) {
            if (-not $required -or -not $visible.Contains(($required -replace '\s', ''))) {
                Add-Issue "Control relationship '$identity' does not visibly disclose '$required'."
            }
        }
        $scopeArrow = if ($annotation.GetAttribute('data-direction') -ceq 'bidirectional') { [char]0x2194 } else { [char]0x2192 }
        if (-not $visible.Contains("$from$scopeArrow$to")) {
            Add-Issue "Control relationship '$identity' has no explicit directional scope."
        }
    }
    foreach ($lifeline in @($sdXml.SelectNodes("//*[@data-kind='lifeline']"))) {
        $id = $lifeline.GetAttribute('data-component-id')
        if ($saIds -notcontains $id) { Add-Issue "Sequence lifeline '$id' has no matching architecture component." }
    }
}
$manifestPath = Join-Path $outputDirectory 'diagram-manifest.json'
if (Test-Path -LiteralPath $manifestPath) {
    try {
        $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
        if ($manifest.PSObject.Properties.Name -notcontains 'layoutQuality' -or
            $manifest.layoutQuality.PSObject.Properties.Name -notcontains 'gates') {
            throw 'Manifest is missing its mandatory numerical visual quality gates.'
        } else {
            $quality = $manifest.layoutQuality
            foreach ($name in @('crossings', 'shared-lanes', 'opposite-lanes', 'route-detour', 'content-density',
                'fit-width-readability', 'agent-emphasis', 'geometry-bounds-overlap', 'relationship-coverage')) {
                if (@($quality.gates | Where-Object name -eq $name).Count -ne 1) {
                    Add-Issue "Manifest is missing or duplicates the '$name' visual gate."
                }
            }
            if ($quality.validation -ne 'passed' -or
                @($quality.gates | Where-Object { $_.passed -isnot [bool] -or -not $_.passed }).Count -gt 0) {
                Add-Issue 'Manifest contains a failed visual quality gate.'
            }
            $score = Convert-Number ([string]$quality.score)
            if ($score -lt 0 -or $score -gt 100) { Add-Issue 'Visual quality score must be finite and between 0 and 100.' }
            $represented = @($saXml.SelectNodes("//*[@data-kind='connector' or @data-kind='control-annotation']"))
            $expected = @($quality.relationshipCoverage)
            if ($represented.Count -ne $expected.Count) { Add-Issue 'Architecture relationship coverage count differs from the manifest.' }
            foreach ($edge in $expected) {
                $matching = @($represented | Where-Object { $_.GetAttribute('data-id') -ceq $edge.id })
                if ($matching.Count -ne 1) {
                    Add-Issue "Canonical relationship '$($edge.id)' must appear exactly once."
                    continue
                }
                foreach ($pair in @(@('from', 'data-from'), @('to', 'data-to'), @('style', 'data-style'),
                    @('label', 'data-label'), @('implementationMode', 'data-implementation-mode'),
                    @('relationshipType', 'data-relationship-type'))) {
                    if ($pair[0] -eq 'relationshipType' -and $edge.PSObject.Properties.Name -notcontains 'relationshipType') { continue }
                    if ($matching[0].GetAttribute($pair[1]) -cne [string]$edge.($pair[0])) {
                        Add-Issue "Canonical relationship '$($edge.id)' changed its $($pair[0])."
                    }
                }
                $expectedDirection = if ($edge.PSObject.Properties.Name -contains 'direction' -and $edge.direction) {
                    [string]$edge.direction
                } else { 'unidirectional' }
                $actualDirection = $matching[0].GetAttribute('data-direction')
                if (-not $actualDirection) { $actualDirection = 'unidirectional' }
                if ($actualDirection -cne $expectedDirection) {
                    Add-Issue "Canonical relationship '$($edge.id)' changed its direction."
                }
            }
            $parts = @($saXml.DocumentElement.GetAttribute('viewBox') -split '\s+')
            $scale = [Math]::Min(1, 1800 / (Convert-Number $parts[2]))
            if (19 * $scale -lt 15 -or 14 * $scale -lt 11 -or 11 * $scale -lt 9) {
                Add-Issue 'Architecture fails 1800px fit-width readability (15px names, 11px body, 9px metadata).'
            }
            foreach ($phase in @($sdXml.SelectNodes("//*[@data-kind='phase' and @data-message-count='1']"))) {
                if ($phase.GetAttribute('data-treatment') -ne 'compact-label') {
                    Add-Issue 'A single-message sequence phase must not be a full-width panel.'
                }
            }
        }
    } catch { Add-Issue "Visual quality manifest validation failed: $($_.Exception.Message)" }
}
$report = [ordered]@{
    validation = if ($issues.Count -eq 0) { 'passed' } else { 'failed' }
    issues = @($issues)
    solutionArchitecture = $SolutionArchitecture
    sequenceDiagram = $SequenceDiagram
    layoutQuality = $quality
    checkedAt = [DateTimeOffset]::Now.ToString('o')
}
[IO.File]::WriteAllText($OutputPath, ($report | ConvertTo-Json -Depth 16), $Utf8)
if ($issues.Count -gt 0) { throw "Diagram validation failed with $($issues.Count) issue(s). See $OutputPath" }
$report
