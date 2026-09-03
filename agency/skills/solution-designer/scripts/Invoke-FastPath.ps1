[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ModelPath,
    [Parameter(Mandatory = $true)][Alias('OutputDirectory')][string]$TempOutputPath,
    [ValidateRange(60, 7200)][int]$DeadlineSeconds = 3600
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$phase = [ordered]@{ generate = 0; validate = 0; render = 0; total = 0 }
$status = 'failed'
$errors = New-Object System.Collections.Generic.List[string]
$candidateFailures = New-Object System.Collections.Generic.List[string]
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
$python = Get-Command python -ErrorAction SilentlyContinue
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
$validationPath = Join-Path $designDirectory 'validation-report.json'
$renderPath = Join-Path $designDirectory 'render-report.json'

$referenceManifest = Get-Content -LiteralPath $referenceManifestPath -Raw | ConvertFrom-Json
$cacheAge = ([DateTimeOffset]::Now - [DateTimeOffset]::Parse([string]$referenceManifest.refreshedAt)).TotalDays
$cacheStatus = if ($cacheAge -le [double]$referenceManifest.maxAgeDays) { 'packaged-fresh' } else { 'packaged-stale' }

try {
    $layoutProfiles = if (@($model.components).Count -gt 18) {
        @('Spacious', 'Wide', 'Balanced')
    } else {
        @('Balanced', 'Spacious', 'Wide')
    }
    foreach ($profile in $layoutProfiles) {
        Assert-Budget
        try {
            $mark = $stopwatch.ElapsedMilliseconds
            & (Join-Path $PSScriptRoot 'New-Diagrams.ps1') -ModelPath $ModelPath -OutputDirectory $designDirectory -LayoutProfile $profile | Out-Null
            $phase.generate += $stopwatch.ElapsedMilliseconds - $mark
            Assert-Budget

            $mark = $stopwatch.ElapsedMilliseconds
            & (Join-Path $PSScriptRoot 'Test-Diagrams.ps1') -SolutionArchitecture $saPath -SequenceDiagram $sdPath -OutputPath $validationPath | Out-Null
            $phase.validate += $stopwatch.ElapsedMilliseconds - $mark
            $selectedLayoutProfile = $profile
            break
        } catch {
            $candidateFailures.Add("$profile`: $($_.Exception.Message)")
        }
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
if (Test-Path -LiteralPath $validationPath -PathType Leaf) {
    $validation = Get-Content -LiteralPath $validationPath -Raw | ConvertFrom-Json
    foreach ($issue in @($validation.issues)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$issue) -and -not $errors.Contains([string]$issue)) { $errors.Add([string]$issue) }
    }
}
$pngSa = [IO.Path]::ChangeExtension($saPath, '.png')
$pngSd = [IO.Path]::ChangeExtension($sdPath, '.png')
if (-not (Test-Path -LiteralPath $pngSa -PathType Leaf) -or -not (Test-Path -LiteralPath $pngSd -PathType Leaf)) {
    $status = 'failed'
    if (-not $errors.Contains('One or both PNG renders are missing.')) { $errors.Add('One or both PNG renders are missing.') }
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
    candidateFailures = @($candidateFailures)
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
    diagramManifest = (Join-Path $designDirectory 'diagram-manifest.json')
    validationReport = $validationPath
    renderReport = $renderPath
    completedAt = [DateTimeOffset]::Now.ToString('o')
}
[IO.File]::WriteAllText($runReportPath, ($report | ConvertTo-Json -Depth 8), $Utf8)
$report
if ($status -ne 'passed') { throw "Fast path failed. See $runReportPath" }
