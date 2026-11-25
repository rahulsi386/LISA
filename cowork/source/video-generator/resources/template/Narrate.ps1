param(
    [string]$VoiceName = 'en-US-AvaMultilingualNeural',
    [string]$Rate = '+14%',
    [string]$Pitch = '+0Hz',
    [switch]$Preview,
    [switch]$AllowOnlineSpeech
)

$ErrorActionPreference = 'Stop'
if (-not $AllowOnlineSpeech) {
    throw 'Online narration sends script text to Microsoft Edge speech. Review the script and service policy, then pass -AllowOnlineSpeech for approved nonsensitive text.'
}
$python = Join-Path $PSScriptRoot 'work\speech-env\Scripts\python.exe'
$ffmpeg = Join-Path $PSScriptRoot 'node_modules\ffmpeg-static\ffmpeg.exe'
foreach ($required in @($python, $ffmpeg)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing dependency: $required. Follow requirements.txt and README.md setup."
    }
}
& node (Join-Path $PSScriptRoot 'render.mjs') --validate
if ($LASTEXITCODE -ne 0) { throw 'Storyboard validation failed.' }
$narrationHash = & node (Join-Path $PSScriptRoot 'render.mjs') --narration-hash
if ($LASTEXITCODE -ne 0) { throw 'Cannot fingerprint narration.' }
$story = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'storyboard.json') -Raw | ConvertFrom-Json
$generation = 'voice-' + [guid]::NewGuid().ToString('N')
$directory = Join-Path $PSScriptRoot "work\$generation"
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$scenes = if ($Preview) { @($story.scenes[0]) } else { @($story.scenes) }

foreach ($scene in $scenes) {
    for ($phraseIndex = 0; $phraseIndex -lt $scene.narration.Count; $phraseIndex++) {
        $name = "$($scene.id)-$phraseIndex"
        $mp3 = Join-Path $directory "$name.mp3"
        $wave = Join-Path $directory "$name.wav"
        & $python -m edge_tts --voice $VoiceName "--rate=$Rate" "--pitch=$Pitch" `
            --text $scene.narration[$phraseIndex] --write-media $mp3
        if ($LASTEXITCODE -ne 0) { throw "Speech failed for $name. Previous active narration is unchanged." }
        & $ffmpeg -hide_banner -loglevel error -y -i $mp3 `
            -af 'silenceremove=start_periods=1:start_duration=0.015:start_threshold=-48dB,areverse,silenceremove=start_periods=1:start_duration=0.015:start_threshold=-48dB,areverse' `
            -ac 1 -ar 48000 -c:a pcm_s16le $wave
        if ($LASTEXITCODE -ne 0) { throw "WAV conversion failed for $name. Previous active narration is unchanged." }
    }
    Write-Output "Narration ready: $($scene.id) / $VoiceName / $Rate"
}

$currentHash = & node (Join-Path $PSScriptRoot 'render.mjs') --narration-hash
if ($LASTEXITCODE -ne 0 -or $currentHash -ne $narrationHash) {
    throw 'The narration changed during synthesis. Active narration has not been changed.'
}
@{
    provider = 'Microsoft Edge online neural speech via edge-tts'
    clientVersion = '7.2.7'
    voice = $VoiceName
    rate = $Rate
    pitch = $Pitch
    synthetic = $true
    preview = [bool]$Preview
    narrationHash = $narrationHash
    generatedAt = [DateTimeOffset]::UtcNow.ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $directory 'narration-profile.json') -Encoding utf8NoBOM

$pointerName = if ($Preview) { 'voice-preview.json' } else { 'voice-current.json' }
$temporary = Join-Path $directory 'pointer.json'
@{ directory = "work/$generation" } | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding utf8NoBOM
[System.IO.File]::Move($temporary, (Join-Path $PSScriptRoot "work\$pointerName"), $true)
Write-Output "Narration saved: $directory"