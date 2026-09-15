---
name: "video-generator"
description: "Generate or revise a developer-focused marketing video for an existing solution, with current product visuals, neural narration, timed captions, and verified MP4 output. Run only when the user explicitly invokes /video-generator or /lisa:video-generator; never run automatically after building, evaluating, or publishing a solution."
user-invocable: true
disable-model-invocation: true
argument-hint: "Solution name or configuration path, optional UI references and video brief"
---

# Video Generator

Create a marketing video for any existing solution using the developer's journey:
brief, implementation, inspecting the created solution, evaluation, and evidence.
This is a standalone Agency skill, **not a CAD stage**. Never invoke it from
`cad-orchestrator`, change the CAD stage registry, complete a lifecycle checkpoint,
or make video output a prerequisite for build, evaluation, publication, or cleanup.
Engines that ignore invocation frontmatter must still enforce explicit user intent.

## 1. Establish The Brief And Evidence

Use the user's supplied solution, configuration, documentation, screenshots, and
existing outputs. For LISA projects, resolve `lisa-config.json` with the packaged
`lisa_path_resolver.py`; read the current build handoff, design pointer, and
evaluation report when present. Read only relevant artifacts. Missing evaluation
or deployment evidence is a limitation, not permission to invent it or execute
cloud stages. Other solutions may provide their own README, demo, tests, and assets.

Default to a developer audience, a 90-120 second English 16:9 video, and the
existing solution's branding. Ask only for missing facts that materially change
the story: which solution, audience override, approved assets, or sensitive-data
permissions. Do not require a question when these are already supplied.

- Lead with what the developer wants to accomplish, not a catalog of skills.
- Show concrete inputs, the command or action, the created solution, its test,
  and the evidence the developer reviews. Use the appropriate platform for the
  solution; never assume every solution is a Copilot Studio agent.
- Distinguish measured results from illustrative scenarios in every affected
  scene. Never show sample PASS/Published as observed tenant state.
- Prefer supplied or authorized current screenshots. Remove environment URLs,
  owner names, identifiers, credentials, and unrelated customer information before
  copying them into a video project. Do not visit a tenant just because a screenshot
  contains its URL. UI reconstruction must be labeled; unseen pages are not verified.
- No GitHub or other repository links in frames, narration, captions, or watch page
  unless the user explicitly requests an exception.
- No cloud writes, deployments, evaluation runs, publication, new paid services,
  voice cloning, or impersonation are authorized by a video request.

## 2. Create A Project-Local Production Folder

Use `<basePath>/output/video/<solution-slug>/<run-id>/` for configured LISA projects,
or an explicitly selected solution-local output folder. Preserve prior versions.
The installed plugin is read-only during production. Resolve the skill from
`AGENCY_PLUGIN_DIR/skills/video-generator` or `CLAUDE_PLUGIN_ROOT/skills/video-generator`.
Copy the bundled template; never depend on the original LISA marketing folder.

```powershell
node "<skill-dir>/scripts/initialize.mjs" --output "<new-production-dir>" --name "<solution-name>"
Set-Location "<new-production-dir>"
npm ci --no-audit --no-fund
python -m venv .\work\speech-env
.\work\speech-env\Scripts\python.exe -m pip install -r .\requirements.txt
```

The initializer rejects a nonempty target. Read [requirements.txt](./requirements.txt)
before setup: it documents Python, Node/npm packages, FFmpeg, Windows fonts,
network access, disk/memory, and speech-service constraints. Do not install into
the plugin, use a global Python environment, disable TLS, or request secrets in chat.

## 3. Author The Story And Visuals

Edit the generated `storyboard.json` and copy sanitized, approved assets into its
`assets/` directory. All asset paths are project-relative. The template supports
title, steps, terminal, screenshot, evidence, and closing scenes. Each scene has
an id, heading, narration phrases, and minimum hold. Replace the generic starter
copy and illustrative evidence with solution-specific material before delivery.

Use [resources/production-guide.md](./resources/production-guide.md) for the
storyboard contract, screenshot treatment, render checks, and lessons from the
validated execution history. Extend the generated renderer only when the solution
needs a visual beyond the template; never modify the installed template during a run.

- Keep the real product or output visible, readable, and correctly framed.
- Use short developer-oriented copy, restrained animation, large terminal text,
  screenshot aspect-ratio preservation, and a separate caption-safe area.
- Reconstruct only from supplied evidence and visibly mark illustrative UI.
- Reuse actual brand assets; do not substitute a stock hero for the solution.
- Verify text fit after each meaningful visual edit; inspect real preview images.

## 4. Generate Natural Narration

The validated default is **Ava** (`en-US-AvaMultilingualNeural`) at `+14%` rate,
natural pitch (`+0Hz`), with conversational copy and short pauses. This is synthetic
female narration, not a human recording. Do not return to the robotic Windows SAPI
voice or raise pitch to imply age. Use an approved different voice when requested.

Tell the user that narration text will be sent to Microsoft's online Edge speech
service through the community `edge-tts` client. Only approved nonsensitive script
text may be sent. For confidential content or a policy that forbids that service,
obtain an approved provider or supplied audio; stop instead of silently uploading
text or falling back. Service access and terms may change; no availability or
commercial-use guarantee is implied.

```powershell
pwsh -NoProfile -File .\Narrate.ps1 -Preview -AllowOnlineSpeech
pwsh -NoProfile -File .\Narrate.ps1 -AllowOnlineSpeech
npm run preview
node .\render.mjs --smoke
npm run render
npm run verify
```

`-AllowOnlineSpeech` is required and attests that the script and service use were
reviewed; do not pass it for confidential or unapproved text. Preview the opening voice first. Full narration stages every phrase before
replacing the active voice set. Regenerate narration after spoken-copy changes;
visual-only revisions reuse the existing voice track. Phrase durations control
scene length and captions. Never fabricate audio approval: technical checks do
not prove a voice sounds human, energetic, or pleasant.

## 5. Verify And Deliver

Run focused checks before full rendering and after any revision:

1. Validate the storyboard, files, unique scene IDs, evidence labels, and forbidden links.
2. Render all scene previews; reject text overflow and missing assets. Visually
   inspect screenshots, captions, table columns, safe areas, and brand treatment.
3. Encode a short smoke test, then the full 1920x1080 H.264/AAC fast-start MP4.
4. Fully decode the final video and audio. Validate caption ordering and duration,
   extract encoded scene frames, and check audio levels for silence and clipping.
5. Inspect the encoded frames, not only source previews. Test the local watch page
   if the browser allows file URLs; if blocked, report that limit and check local
   assets. A plain HTML player does not need a dev server.

The packaged artifact contract uses `video` solely as an artifact category; its
file paths are relative to each generated production folder beneath the video
root, not a CAD stage or completion marker. Validate its definition with
`python "<plugin-skills-root>/validate_artifact_contracts.py" --skill video-generator`.

Deliver clickable paths to `output/marketing-video.mp4`, `watch.html`, caption
sidecars, the thumbnail, timing manifest, and editable source. Keep the folder
together. Burned-in captions are already visible; enabling sidecars over them
duplicates subtitles. Record any unverified playback, UI, or audio judgments.
Do not upload the video, modify the solution, or resume CAD as a side effect.