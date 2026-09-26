# Solution Marketing Video Production

This template turns a solution-specific storyboard and approved visual assets
into a 1080p narrated MP4. It does not build or test the solution itself. The hosting
agent owns evidence review, creative direction, screenshot sanitization, visual
inspection, and final delivery. This workflow is independent of CAD checkpoints.

## Setup

Read `requirements.txt` for the complete dependency and service inventory. From
the generated production directory:

```powershell
npm ci --no-audit --no-fund
python -m venv .\work\speech-env
.\work\speech-env\Scripts\python.exe -m pip install -r .\requirements.txt
```

Replace the starter script and add the referenced image before previewing. After
reviewing the script for confidentiality and approving online speech:

```powershell
npm run preview
pwsh -NoProfile -File .\Narrate.ps1 -Preview -AllowOnlineSpeech
pwsh -NoProfile -File .\Narrate.ps1 -AllowOnlineSpeech
node .\render.mjs --smoke
npm run render
npm run verify
```

Set `readyForRender` to `true` only after adapting the starter material. This is a
human-review attestation, not an automated proof of factual accuracy. Do not hand
off starter text or synthetic test fixtures as a finished solution video.

## Storyboard Contract

`storyboard.json` is strict JSON. The renderer validates the runtime contract:

| Field | Meaning |
| --- | --- |
| `title` | Actual solution name, not LISA unless marketing LISA itself |
| `audience` | Default `Developers`; change only when requested |
| `disclosure` | Short visible line describing illustrative UI/results as needed |
| `readyForRender` | `false` until solution-specific copy and assets are reviewed |
| `allowRepositoryLinks` | Default `false`; explicit user request required to enable |
| `scenes` | 2-20 ordered scenes; target 90-120 seconds, maximum 10 minutes |

Each scene needs a lowercase kebab-case `id`, `type`, `heading`, 1-6 `narration`
phrases, and `minimumDuration` (5-30 seconds). An optional `label` identifies a
developer action, product surface, sample finding, or reconstruction. Keep headings
short; text overflow fails instead of silently clipping.

| Type | Additional fields |
| --- | --- |
| `title`, `closing` | Optional `image` for a real product or brand asset |
| `steps` | `items`: 1-5 concrete developer actions |
| `terminal` | `commands`: 1-5 verified command lines; these are displayed, never executed |
| `screenshot` | `image`: required project-relative asset path; optional `label` |
| `evidence` | `items`, `evidenceKind`: `measured` or `illustrative`; `label` |

Measured evidence requires a nonempty `sources` list of local evidence-file paths.
File presence is checked automatically; the hosting agent must verify that those
sources actually support each claim. Illustrative evidence requires a visible
label containing `sample` or `illustrative`. Never invent aggregate scores,
timestamps, published states, or success counts and describe them as measured.

Assets and evidence must remain inside the production directory, including after
symlink resolution. Keep images in `assets/` and use PNG/JPEG/WebP or trusted SVGs.
Screenshots are fitted without distorting or cropping away critical controls.
Do not embed a screenshot with customer identities, tenant URLs, tokens, or
unrelated data. Redact first; preserve the private original outside the deliverable.

The provided template is intentionally not a hardcoded Copilot Studio skin.
Use the target solution's actual current UI. When only one screen is available,
do not invent adjacent screens and call them verified. Label reconstructions and
show LISA's annotations outside the native product UI when possible.

## Narration And Timing

The tested voice is `en-US-AvaMultilingualNeural`, `+14%` rate, `+0Hz` pitch.
Use contractions, short clauses, clear emphasis, and useful momentum. Faster
delivery alone does not fix stiff copy. Do not claim the synthetic voice is a
human performer, clone a voice, or imply a speaker's age as a verified fact.

The online `edge-tts` client processes only approved narration text. It is a
community client to Microsoft's Edge speech service, not a contracted Azure
Speech API. Follow applicable service terms and organizational data policy.
No secrets belong in commands or configuration. A speech outage blocks narration;
it must not trigger a silent fallback to SAPI or fabricated audio.

`Narrate.ps1` stages WAVs in a new generation, records a narration-content hash,
and switches `work/voice-current.json` only after all phrases succeed. Preview
uses a separate pointer. If wording or scene IDs change, re-synthesize. Visual-only
changes preserve the voice. New scene lengths are computed from measured WAV
durations with 0.35 second lead-in, 0.08 second phrase gaps, and 0.45 second tail.
The renderer refuses stale narration or a preview-only profile.

An approved supplied-audio workflow may create the same pointer/profile contract:
mono 48 kHz PCM 16-bit WAVs named `<scene-id>-<phrase-index>.wav`, zero-based indexes,
`preview: false`, and `narrationHash` from `node render.mjs --narration-hash`.
Record the actual provider and permission provenance; never label human recordings
as Ava. Adapt disclosure accordingly in the generated renderer and player.

## Verification And Outputs

Preview checks all captions and scene layouts and creates `output/storyboard.jpg`,
`output/thumbnail.jpg`, and `work/<scene-id>.png`. Inspect these visually. The
three-second smoke test exercises rendering, audio mixing, and H.264/AAC encoding.
Full rendering stages the MP4 before replacing the current output.

`npm run verify` checks storyboard identity, narration identity, caption timing,
full audio/video decoding, and non-silent/non-clipping peak audio. It extracts
`work/encoded-<scene-id>.png` from the actual MP4. It writes `output/verification.json`
without claiming an automated listening review or aesthetic judgment. Run tools
such as `volumedetect` when diagnosing mix issues; do not claim to have heard audio
when only waveform/level checks were performed.

Deliver the folder containing:

- `output/marketing-video.mp4`: 1920x1080, 24 fps, H.264/AAC, fast-start playback.
- `watch.html`: local responsive player, no server required.
- `output/captions.srt` and `output/captions.vtt`: phrase-aligned captions.
- `output/thumbnail.jpg`, `output/storyboard.jpg`, and `output/timing.json`.
- `output/verification.json` and the editable storyboard/renderer/narration script.

Captions are burned in; do not enable sidecars over them by default. Keep the
player and `output/` together. Do not ship `node_modules/`, `work/`, provider
credentials, or raw private screenshots. Test local player links; if a browser
automation tool blocks file URLs, disclose that rather than claiming playback.

## Lessons From The Validated Run

The originating execution history produced a LISA demo and refined it through
four user corrections: remove repository links, center the developer journey,
replace sluggish SAPI narration with energetic neural speech, and update stale
Copilot Studio UI from the user's current screenshot. These became defaults,
not hardcoded LISA-specific claims or mandatory Copilot Studio screens.

The original final MP4 was about 1:40 and passed full decoding, audio-level,
caption, and encoded-frame inspection. Its runtime is not a target benchmark for
other solutions. Browser file-URL playback was blocked by the automation tool.
On this host `rg` was unavailable, and the terminal tool once rewrote `&&` inside
a quoted Node command; prefer checked-in scripts or separate assertions for
repeatable validation. Never disable TLS to solve speech or npm access issues.