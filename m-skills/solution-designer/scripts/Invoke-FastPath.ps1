[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ModelPath,
    [Parameter(Mandatory = $true)][Alias('OutputDirectory')][string]$TempOutputPath,
    [ValidateRange(60, 7200)][int]$DeadlineSeconds = 3600,
    [ValidateSet('Balanced', 'Spacious', 'Wide')][string]$LayoutProfile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$phase = [ordered]@{ sources = 0; generate = 0; validate = 0; render = 0; total = 0 }
$status = 'failed'
$errors = New-Object System.Collections.Generic.List[string]
$candidateFailures = New-Object System.Collections.Generic.List[string]
$attemptedLayoutProfiles = New-Object System.Collections.Generic.List[string]
$candidates = New-Object System.Collections.Generic.List[object]
$selectedLayoutProfile = ''
$resourceRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'resources'
$referenceManifestPath = Join-Path $resourceRoot 'reference-manifest.json'

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path))
}

function Assert-UnderRoot([string]$Path, [string]$Root, [string]$Label) {
    $fullPath = Get-FullPath $Path
    $fullRoot = (Get-FullPath $Root).TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($fullRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must be stored beneath $Root. Actual path: $fullPath"
    }
}

$tempOutputRoot = Get-FullPath $TempOutputPath
$designDirectory = Join-Path $tempOutputRoot 'design'
New-Item -ItemType Directory -Force -Path $designDirectory | Out-Null
$designDirectory = (Resolve-Path -LiteralPath $designDirectory).Path

if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) { throw "Model not found: $ModelPath" }
$ModelPath = (Resolve-Path -LiteralPath $ModelPath).Path
Assert-UnderRoot $ModelPath $designDirectory 'design-model.json'
$pythonCommand = if ($env:LISA_PYTHON) { $env:LISA_PYTHON } else { 'python' }
$python = Get-Command $pythonCommand -ErrorAction SilentlyContinue
if (-not $python) { throw 'Python is required for design-model schema validation.' }
& ([string]$python.Source) (Join-Path $PSScriptRoot 'solution_designer.py') validate-model --model $ModelPath | Out-Null
if ($LASTEXITCODE -ne 0) { throw "design-model.json failed schema validation: $ModelPath" }

$runReportPath = Join-Path $designDirectory 'run-report.json'

function Assert-Budget {
    if ($stopwatch.Elapsed.TotalSeconds -ge $DeadlineSeconds) {
        throw "The $DeadlineSeconds-second execution budget was exhausted."
    }
}

$model = Get-Content -LiteralPath $ModelPath -Raw | ConvertFrom-Json
$slug = [string]$model.scenarioSlug
$saPath = Join-Path $designDirectory "SA_$slug.svg"
$sdPath = Join-Path $designDirectory "SD_$slug.svg"
$previewPath = Join-Path $designDirectory 'preview.html'
$validationPath = Join-Path $designDirectory 'validation-report.json'
$renderPath = Join-Path $designDirectory 'render-report.json'
$candidateReportPath = Join-Path $designDirectory 'candidate-report.json'
$sourceNames = @("Design_$slug.drawio", "SA_$slug.mmd", "SD_$slug.mmd", 'source-report.json')

$referenceManifest = Get-Content -LiteralPath $referenceManifestPath -Raw | ConvertFrom-Json
$cacheAge = ([DateTimeOffset]::Now - [DateTimeOffset]::Parse([string]$referenceManifest.refreshedAt)).TotalDays
$cacheStatus = if ($cacheAge -le [double]$referenceManifest.maxAgeDays) { 'packaged-fresh' } else { 'packaged-stale' }

try {
    $mark = $stopwatch.ElapsedMilliseconds
    $sourceResult = & ([string]$python.Source) (Join-Path $PSScriptRoot 'source_artifacts.py') generate `
        --model $ModelPath --output $designDirectory 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Draw.io -> Mermaid source validation failed: $($sourceResult -join [Environment]::NewLine)"
    }
    $phase.sources = $stopwatch.ElapsedMilliseconds - $mark
    $layoutProfiles = if ($LayoutProfile) {
        @($LayoutProfile)
    } elseif (@($model.components).Count -gt 18) {
        @('Spacious', 'Balanced', 'Wide')
    } else {
        @('Balanced', 'Spacious', 'Wide')
    }
    foreach ($profile in $layoutProfiles) {
        Assert-Budget
        $attemptedLayoutProfiles.Add($profile)
        $candidateDirectory = Join-Path $designDirectory ".candidates\$profile\design"
        New-Item -ItemType Directory -Force -Path $candidateDirectory | Out-Null
        $candidateModel = Join-Path $candidateDirectory 'design-model.json'
        Copy-Item -LiteralPath $ModelPath -Destination $candidateModel
        foreach ($name in $sourceNames) {
            Copy-Item -LiteralPath (Join-Path $designDirectory $name) -Destination (Join-Path $candidateDirectory $name)
        }
        $candidate = [ordered]@{
            profile = $profile
            order = $candidates.Count
            validation = 'failed'
            score = $null
            directory = $candidateDirectory
            issues = @()
            elapsedMs = 0
            compositionReport = $null
        }
        $candidateStart = $stopwatch.ElapsedMilliseconds
        $activePhase = ''
        try {
            $activePhase = 'generate'
            $mark = $stopwatch.ElapsedMilliseconds
            & (Join-Path $PSScriptRoot 'New-Diagrams.ps1') -ModelPath $candidateModel `
                -OutputDirectory $candidateDirectory -LayoutProfile $profile -SourcesPrepared | Out-Null
            $phase.generate += $stopwatch.ElapsedMilliseconds - $mark
            $activePhase = ''
            Assert-Budget

            $activePhase = 'validate'
            $mark = $stopwatch.ElapsedMilliseconds
            & (Join-Path $PSScriptRoot 'Test-Diagrams.ps1') `
                -SolutionArchitecture (Join-Path $candidateDirectory "SA_$slug.svg") `
                -SequenceDiagram (Join-Path $candidateDirectory "SD_$slug.svg") `
                -OutputPath (Join-Path $candidateDirectory 'validation-report.json') | Out-Null
            $phase.validate += $stopwatch.ElapsedMilliseconds - $mark
            $activePhase = ''
            $manifest = Get-Content -LiteralPath (Join-Path $candidateDirectory 'diagram-manifest.json') -Raw | ConvertFrom-Json
            $quality = $manifest.layoutQuality
            if ($quality.validation -ne 'passed' -or
                $quality.score -isnot [ValueType] -or
                $quality.score -is [bool] -or
                [double]::IsNaN([double]$quality.score) -or
                [double]::IsInfinity([double]$quality.score)) {
                throw 'Candidate has no passing, finite presentation-quality score.'
            }
            $candidate.validation = 'passed'
            $candidate.score = [double]$quality.score
        } catch {
            if ($activePhase) { $phase[$activePhase] += $stopwatch.ElapsedMilliseconds - $mark }
            $message = $_.Exception.Message
            $candidate.issues = @($message)
            $candidateFailures.Add("$profile`: $message")
        } finally {
            $compositionReportPath = Join-Path $candidateDirectory "composition-candidates-$profile.json"
            if (Test-Path -LiteralPath $compositionReportPath -PathType Leaf) {
                $candidate.compositionReport = Get-Content -LiteralPath $compositionReportPath -Raw | ConvertFrom-Json
            }
            $candidate.elapsedMs = $stopwatch.ElapsedMilliseconds - $candidateStart
            $candidates.Add([pscustomobject]$candidate)
        }
    }
    $selected = @($candidates | Where-Object validation -eq 'passed' |
        Sort-Object -Property @{Expression = 'score'; Descending = $true}, @{Expression = 'order'; Ascending = $true} |
        Select-Object -First 1)
    if ($selected.Count -gt 0) {
        $selectedLayoutProfile = $selected[0].profile
        foreach ($name in @("SA_$slug.svg", "SD_$slug.svg", 'preview.html', 'diagram-manifest.json', 'validation-report.json')) {
            Copy-Item -LiteralPath (Join-Path $selected[0].directory $name) -Destination (Join-Path $designDirectory $name)
        }
        $manifest = Get-Content -LiteralPath (Join-Path $designDirectory 'diagram-manifest.json') -Raw | ConvertFrom-Json
        $manifest.solutionArchitecture = $saPath
        $manifest.sequenceDiagram = $sdPath
        $manifest.layoutQuality.candidateReport = 'candidate-report.json'
        [IO.File]::WriteAllText((Join-Path $designDirectory 'diagram-manifest.json'), ($manifest | ConvertTo-Json -Depth 50), $Utf8)
    }
    if ([string]::IsNullOrWhiteSpace($selectedLayoutProfile)) {
        throw "All deterministic layout profiles failed: $($candidateFailures -join ' | ')"
    }

    $remainingSeconds = [Math]::Floor($DeadlineSeconds - $stopwatch.Elapsed.TotalSeconds - 5)
    if ($remainingSeconds -lt 5) { throw 'Insufficient budget remains for rendering.' }
    $mark = $stopwatch.ElapsedMilliseconds
    & (Join-Path $PSScriptRoot 'Render-Diagrams.ps1') -SvgPaths @($saPath, $sdPath) -OutputPath $renderPath -ProfileRoot (Join-Path $designDirectory '.browser-profiles') -TimeoutSeconds ([Math]::Min(45, $remainingSeconds)) | Out-Null
    $phase.render = $stopwatch.ElapsedMilliseconds - $mark
    Assert-Budget
    $status = 'passed'
} catch {
    $errors.Add($_.Exception.Message)
}

$stopwatch.Stop()
$phase.total = $stopwatch.ElapsedMilliseconds
if ($selectedLayoutProfile -and (Test-Path -LiteralPath $validationPath -PathType Leaf)) {
    $validation = Get-Content -LiteralPath $validationPath -Raw | ConvertFrom-Json
    foreach ($issue in @($validation.issues)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$issue) -and -not $errors.Contains([string]$issue)) { $errors.Add([string]$issue) }
    }
    [IO.File]::WriteAllText($candidateReportPath, ([ordered]@{
        selection = 'Highest passing presentation-quality score; deterministic profile-order tie break.'
        selectedLayoutProfile = $selectedLayoutProfile
        candidates = $candidates.ToArray()
    } | ConvertTo-Json -Depth 50), $Utf8)
}
$pngSa = [IO.Path]::ChangeExtension($saPath, '.png')
$pngSd = [IO.Path]::ChangeExtension($sdPath, '.png')
if (-not (Test-Path -LiteralPath $pngSa -PathType Leaf) -or -not (Test-Path -LiteralPath $pngSd -PathType Leaf)) {
    $status = 'failed'
    if (-not $errors.Contains('One or both PNG renders are missing.')) { $errors.Add('One or both PNG renders are missing.') }
}
if (-not (Test-Path -LiteralPath $previewPath -PathType Leaf) -or (Get-Item -LiteralPath $previewPath).Length -eq 0) {
    $status = 'failed'
    $errors.Add('The HTML preview is missing or empty.')
}
if ($stopwatch.Elapsed.TotalSeconds -ge $DeadlineSeconds) {
    $status = 'failed'
    $errors.Add("Run exceeded the $DeadlineSeconds-second generation deadline.")
}

$report = [ordered]@{
    validation = if ($status -eq 'passed') { 'pending-inspection' } else { 'failed' }
    structuralValidation = $status
    renderedInspection = if ($status -eq 'passed') { 'pending' } else { 'not-run' }
    validationIssues = @($errors)
    cacheStatus = $cacheStatus
    selectedLayoutProfile = $selectedLayoutProfile
    attemptedLayoutProfiles = @($attemptedLayoutProfiles)
    candidateSelection = 'Highest passing presentation-quality score after source and geometry gates; rendered inspection still required.'
    candidateFailures = @($candidateFailures)
    candidateReport = $candidateReportPath
    sourceReport = (Join-Path $designDirectory 'source-report.json')
    pipelineStages = @('drawio', 'mermaid', 'presentation', 'raster', 'inspection')
    timingsMs = $phase
    completedUnderEightMinutes = ($stopwatch.Elapsed.TotalSeconds -lt 480)
    completedWithinGenerationDeadline = ($stopwatch.Elapsed.TotalSeconds -lt $DeadlineSeconds)
    tempOutputPath = $tempOutputRoot
    designDirectory = $designDirectory
    modelPath = $ModelPath
    solutionArchitecture = $saPath
    sequenceDiagram = $sdPath
    solutionArchitecturePng = $pngSa
    sequenceDiagramPng = $pngSd
    htmlPreview = $previewPath
    diagramManifest = (Join-Path $designDirectory 'diagram-manifest.json')
    validationReport = $validationPath
    renderReport = $renderPath
    completedAt = [DateTimeOffset]::Now.ToString('o')
}
[IO.File]::WriteAllText($runReportPath, ($report | ConvertTo-Json -Depth 8), $Utf8)
$report
if ($status -ne 'passed') { throw "Fast path failed. See $runReportPath" }
