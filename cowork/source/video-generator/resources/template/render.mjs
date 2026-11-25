import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { spawn, spawnSync } from 'node:child_process';
import { mkdir, readFile, realpath, writeFile, rename } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createCanvas, GlobalFonts, loadImage } from '@napi-rs/canvas';
import ffmpeg from 'ffmpeg-static';

const WIDTH = 1920;
const HEIGHT = 1080;
const FPS = 24;
const RATE = 48000;
const colors = { ink: '#152123', muted: '#546567', paper: '#F4F6F5', teal: '#007F84', cyan: '#61E4E8', dark: '#10191B', white: '#FFFFFF', line: '#D0DDDC' };
const clamp = value => Math.max(0, Math.min(1, value));
const hash = value => createHash('sha256').update(value).digest('hex');
export const narrationHash = story => hash(JSON.stringify(story.scenes.map(scene => ({ id: scene.id, narration: scene.narration }))));

export async function localAsset(root, relative) {
  assert(typeof relative === 'string' && relative.length, 'Asset path required');
  assert(!path.isAbsolute(relative) && !/^[a-z]:|^[/\\]|\.\.(?:[/\\]|$)/i.test(relative), 'Assets must be project-relative without traversal');
  const target = await realpath(path.resolve(root, relative));
  const boundary = await realpath(root);
  const resolved = path.relative(boundary, target);
  assert(resolved && !resolved.startsWith('..') && !path.isAbsolute(resolved), 'Asset escapes production folder');
  return target;
}

export async function validateStory(story, root, delivery = false) {
  for (const field of ['title', 'audience', 'disclosure']) assert(typeof story[field] === 'string' && story[field].trim(), `${field} required`);
  assert.equal(typeof story.allowRepositoryLinks, 'boolean');
  assert.equal(typeof story.readyForRender, 'boolean');
  assert(Array.isArray(story.scenes) && story.scenes.length >= 2 && story.scenes.length <= 20, 'Use 2-20 scenes');
  if (!story.allowRepositoryLinks) assert.doesNotMatch(JSON.stringify(story), /(?:github\.com|github\.io|gitlab\.com|bitbucket\.org|dev\.azure\.com)/i, 'Repository links are disabled');
  const ids = new Set();
  let images = 0;
  for (const scene of story.scenes) {
    assert(/^[a-z][a-z0-9-]{0,39}$/.test(scene.id), 'Unsafe scene ID');
    assert(!ids.has(scene.id), `Duplicate scene: ${scene.id}`);
    ids.add(scene.id);
    assert(['title', 'steps', 'terminal', 'screenshot', 'evidence', 'closing'].includes(scene.type), 'Unknown scene type');
    assert(typeof scene.heading === 'string' && scene.heading.trim(), 'Scene heading required');
    assert(Number.isFinite(scene.minimumDuration) && scene.minimumDuration >= 5 && scene.minimumDuration <= 30, 'Scene holds must be 5-30 seconds');
    assert(Array.isArray(scene.narration) && scene.narration.length >= 1 && scene.narration.length <= 6, 'Narration required');
    for (const phrase of scene.narration) assert(typeof phrase === 'string' && phrase.trim() && phrase.length <= 500, 'Invalid narration phrase');
    if (scene.type === 'screenshot') assert(scene.image, 'Screenshot scenes require an image');
    if (scene.image) { await localAsset(root, scene.image); images++; }
    if (['steps', 'evidence', 'terminal'].includes(scene.type)) {
      const rows = scene.type === 'terminal' ? scene.commands : scene.items;
      assert(Array.isArray(rows) && rows.length >= 1 && rows.length <= 5, 'Use 1-5 rows');
      for (const row of rows) assert(typeof row === 'string' && row.trim(), 'Rows must be nonempty text');
    }
    if (scene.type === 'evidence') {
      assert(['measured', 'illustrative'].includes(scene.evidenceKind), 'Evidence must be labeled');
      if (scene.evidenceKind === 'measured') {
        assert(Array.isArray(scene.sources) && scene.sources.length, 'Measured evidence requires source files');
        for (const source of scene.sources) await localAsset(root, source);
      } else assert(/sample|illustrative/i.test(scene.label || ''), 'Sample evidence requires a visible label');
    }
  }
  if (delivery) { assert(story.readyForRender, 'Tailor the starter story and set readyForRender before delivery'); assert(images > 0, 'Supply a real visual asset for the solution'); }
}

export function readWave(buffer) {
  assert.equal(buffer.toString('ascii', 0, 4), 'RIFF');
  assert.equal(buffer.toString('ascii', 8, 12), 'WAVE');
  let format;
  let data;
  for (let offset = 12; offset + 8 <= buffer.length;) {
    const kind = buffer.toString('ascii', offset, offset + 4);
    const size = buffer.readUInt32LE(offset + 4);
    assert(offset + 8 + size <= buffer.length, 'Truncated WAV');
    if (kind === 'fmt ') format = buffer.subarray(offset + 8, offset + 8 + size);
    if (kind === 'data') data = buffer.subarray(offset + 8, offset + 8 + size);
    offset += 8 + size + size % 2;
  }
  assert(format?.length >= 16 && data?.length > 0, 'WAV format/data missing');
  assert.equal(format.readUInt16LE(0), 1, 'Use PCM WAV');
  assert.equal(format.readUInt16LE(2), 1, 'Use mono WAV');
  assert.equal(format.readUInt32LE(4), RATE, 'Use 48 kHz WAV');
  assert.equal(format.readUInt16LE(14), 16, 'Use 16-bit WAV');
  assert.equal(data.length % 2, 0);
  return { data, duration: data.length / (RATE * 2) };
}

export function waveBuffer(samples) {
  const result = Buffer.alloc(44 + samples.length * 2);
  result.write('RIFF'); result.writeUInt32LE(result.length - 8, 4); result.write('WAVEfmt ', 8);
  result.writeUInt32LE(16, 16); result.writeUInt16LE(1, 20); result.writeUInt16LE(1, 22);
  result.writeUInt32LE(RATE, 24); result.writeUInt32LE(RATE * 2, 28);
  result.writeUInt16LE(2, 32); result.writeUInt16LE(16, 34); result.write('data', 36);
  result.writeUInt32LE(samples.length * 2, 40);
  samples.forEach((sample, index) => result.writeInt16LE(Math.round(Math.max(-1, Math.min(1, sample)) * 32767), 44 + index * 2));
  return result;
}

export function timestamp(seconds, separator = ',') {
  const milliseconds = Math.round(seconds * 1000);
  return `${String(Math.floor(milliseconds / 3600000)).padStart(2, '0')}:${String(Math.floor(milliseconds / 60000) % 60).padStart(2, '0')}:${String(Math.floor(milliseconds / 1000) % 60).padStart(2, '0')}${separator}${String(milliseconds % 1000).padStart(3, '0')}`;
}

async function timeline(story, root) {
  const pointer = JSON.parse(await readFile(path.join(root, 'work/voice-current.json'), 'utf8'));
  const directory = await localAsset(root, pointer.directory);
  const profile = JSON.parse((await readFile(path.join(directory, 'narration-profile.json'), 'utf8')).replace(/^\uFEFF/, ''));
  assert.equal(profile.narrationHash, narrationHash(story), 'Narration is stale; rerun Narrate.ps1');
  assert.equal(profile.preview, false, 'Preview narration cannot be used for delivery');
  let cursor = 0;
  const scenes = [];
  const cues = [];
  for (const scene of story.scenes) {
    let voiceCursor = 0.35;
    const voices = [];
    for (const [index, phrase] of scene.narration.entries()) {
      const wave = readWave(await readFile(path.join(directory, `${scene.id}-${index}.wav`)));
      voices.push({ ...wave, start: cursor + voiceCursor });
      cues.push({ start: cursor + voiceCursor, end: cursor + voiceCursor + wave.duration, text: phrase });
      voiceCursor += wave.duration + 0.08;
    }
    const duration = Math.ceil(Math.max(scene.minimumDuration, voiceCursor + 0.45) * FPS) / FPS;
    scenes.push({ ...scene, start: cursor, duration, voices });
    cursor += duration;
  }
  assert(cursor <= 600, 'Keep the video under ten minutes');
  return { duration: cursor, scenes, cues, profile };
}

function createPainter(story, images) {
  for (const [filename, family] of [['bahnschrift.ttf', 'Display'], ['segoeui.ttf', 'Body'], ['segoeuib.ttf', 'Bold'], ['consola.ttf', 'Mono']]) {
    assert(GlobalFonts.registerFromPath(path.join(process.env.WINDIR || 'C:\\Windows', 'Fonts', filename), family), `Missing font: ${filename}`);
  }
  const canvas = createCanvas(WIDTH, HEIGHT);
  const context = canvas.getContext('2d');
  const rectangle = (left, top, width, height, color) => { context.fillStyle = color; context.fillRect(left, top, width, height); };
  function text(value, left, top, width, size, color = colors.ink, family = 'Body') {
    context.font = `${size}px "${family}"`; context.textBaseline = 'top'; context.fillStyle = color;
    assert(context.measureText(value).width <= width + 1, `Text overflow: ${value}`);
    assert(left >= 0 && left + width <= WIDTH && top >= 0 && top + size <= HEIGHT, 'Text outside frame');
    context.fillText(value, left, top);
  }
  function wrap(value, left, top, width, size, color = colors.ink, bottom = 875) {
    context.font = `${size}px "Body"`;
    let line = '';
    for (const word of value.split(/\s+/)) {
      const candidate = line ? `${line} ${word}` : word;
      if (line && context.measureText(candidate).width > width) {
        assert(top + size <= bottom, 'Wrapped text overflow');
        text(line, left, top, width, size, color); top += size * 1.35; line = word;
      } else line = candidate;
    }
    assert(top + size <= bottom, 'Wrapped text overflow');
    text(line, left, top, width, size, color);
    return top + size * 1.35;
  }
  function fitImage(image, left, top, width, height) {
    const scale = Math.min(width / image.width, height / image.height);
    context.drawImage(image, left + (width - image.width * scale) / 2, top + (height - image.height * scale) / 2, image.width * scale, image.height * scale);
  }
  function draw(scene, index, seconds, duration, caption = '') {
    context.globalAlpha = 1;
    rectangle(0, 0, WIDTH, HEIGHT, colors.paper);
    rectangle(0, 0, WIDTH, 108, colors.white);
    text(story.title, 96, 31, 1728, 32, colors.ink, 'Bold');
    text(scene.label || story.audience, 98, 129, 1724, 21, colors.teal, 'Bold');
    let headingSize = 68;
    while (headingSize > 34) { context.font = `${headingSize}px "Display"`; if (context.measureText(scene.heading).width <= 1728) break; headingSize--; }
    text(scene.heading, 96, 185, 1728, headingSize, colors.ink, 'Display');
    const fadeIn = clamp(seconds / 0.5);
    context.globalAlpha = fadeIn;
    if (scene.type === 'screenshot') {
      fitImage(images.get(scene.image), 96, 295, 1728, 567);
    } else if (scene.type === 'title' || scene.type === 'closing') {
      if (scene.image) fitImage(images.get(scene.image), 96, 300, 1728, 550);
      else wrap(scene.label || story.audience, 100, 450, 1720, 52, colors.teal);
    } else if (scene.type === 'terminal') {
      rectangle(96, 312, 1728, 513, colors.dark);
      scene.commands.forEach((command, commandIndex) => {
        const visible = clamp((seconds - 0.7 - commandIndex * 0.65) / 0.5);
        text(command.slice(0, Math.floor(command.length * visible)), 131, 361 + commandIndex * 81, 1650, 30, colors.cyan, 'Mono');
      });
    } else {
      scene.items.forEach((item, itemIndex) => {
        const top = 330 + itemIndex * 105;
        rectangle(100, top + 5, 5, 58, scene.type === 'evidence' ? '#CF573E' : colors.teal);
        wrap(item, 131, top, 1650, 31, colors.ink, top + 89);
      });
    }
    context.globalAlpha = 1;
    text(`${String(index + 1).padStart(2, '0')} / ${String(story.scenes.length).padStart(2, '0')}`, 98, 893, 150, 20, colors.muted, 'Mono');
    text(story.disclosure, 280, 892, 1535, 19, colors.muted);
    rectangle(0, 956, WIDTH, 124, colors.dark);
    if (caption) wrap(caption, 128, 978, 1664, 30, colors.white, 1068);
    rectangle(0, HEIGHT - 4, WIDTH * ((index + clamp(seconds / duration)) / story.scenes.length), 4, colors.cyan);
  }
  return { canvas, draw };
}

async function previews(story, painter, root) {
  const sheet = createCanvas(1280, Math.ceil(story.scenes.length / 2) * 360);
  const context = sheet.getContext('2d');
  for (const [index, scene] of story.scenes.entries()) {
    for (const phrase of scene.narration) painter.draw(scene, index, 6.5, scene.minimumDuration, phrase);
    await writeFile(path.join(root, 'work', `${scene.id}.png`), await painter.canvas.encode('png'));
    context.drawImage(painter.canvas, index % 2 * 640, Math.floor(index / 2) * 360, 640, 360);
  }
  await writeFile(path.join(root, 'output/storyboard.jpg'), await sheet.encode('jpeg', 90));
  painter.draw(story.scenes[0], 0, 5, 7);
  await writeFile(path.join(root, 'output/thumbnail.jpg'), await painter.canvas.encode('jpeg', 94));
}

async function soundtrack(timing, root) {
  const samples = new Float32Array(Math.ceil(timing.duration * RATE));
  const chords = [[130.813, 164.814, 195.998], [110, 130.813, 164.814], [87.307, 110, 130.813], [97.999, 123.471, 146.832]];
  for (let index = 0; index < samples.length; index++) {
    const seconds = index / RATE;
    const chord = chords[Math.floor(seconds / 5) % chords.length];
    const beat = seconds * 1.6;
    const phase = beat % 0.5;
    const envelope = Math.min(1, phase * 70) * Math.exp(-phase * 9);
    samples[index] = Math.min(clamp(seconds / 2), clamp((timing.duration - seconds) / 2)) * Math.sin(seconds * 2 * Math.PI * chord[Math.floor(beat * 2) % 3] * 2) * envelope * 0.012;
  }
  for (const scene of timing.scenes) for (const voice of scene.voices) {
    const start = Math.round(voice.start * RATE);
    for (let index = 0; index < voice.data.length / 2; index++) samples[start + index] += voice.data.readInt16LE(index * 2) / 32768 * 0.93;
  }
  await writeFile(path.join(root, 'work/soundtrack.wav'), waveBuffer(samples));
}

async function encode(timing, painter, root, smoke) {
  const duration = smoke ? Math.min(3, timing.duration) : timing.duration;
  const temporary = path.join(root, 'work', smoke ? 'smoke.mp4' : 'rendering.mp4');
  const encoder = spawn(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pixel_format', 'rgba', '-video_size', `${WIDTH}x${HEIGHT}`, '-framerate', String(FPS), '-i', 'pipe:0', '-i', path.join(root, 'work/soundtrack.wav'), '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-ar', String(RATE), '-t', duration.toFixed(6), '-movflags', '+faststart', temporary], { stdio: ['pipe', 'ignore', 'pipe'] });
  let errors = '';
  encoder.stderr.on('data', chunk => { errors += chunk; });
  const completion = new Promise((resolve, reject) => { encoder.once('error', reject); encoder.once('close', code => code === 0 ? resolve() : reject(new Error(errors || `FFmpeg exit ${code}`))); });
  completion.catch(() => {});
  encoder.stdin.on('error', () => {});
  let sceneIndex = 0;
  try {
    for (let frame = 0; frame < Math.round(duration * FPS); frame++) {
      const seconds = frame / FPS;
      while (sceneIndex + 1 < timing.scenes.length && seconds >= timing.scenes[sceneIndex + 1].start) sceneIndex++;
      const scene = timing.scenes[sceneIndex];
      painter.draw(scene, sceneIndex, seconds - scene.start, scene.duration, timing.cues.find(cue => seconds >= cue.start && seconds < cue.end)?.text || '');
      const pixels = painter.canvas.getContext('2d').getImageData(0, 0, WIDTH, HEIGHT).data;
      if (!encoder.stdin.write(Buffer.from(pixels.buffer, pixels.byteOffset, pixels.byteLength))) await Promise.race([once(encoder.stdin, 'drain'), completion.then(() => { throw new Error('Encoder stopped early'); })]);
      if (frame % (FPS * 10) === 0) console.log(`Rendering ${seconds.toFixed(0)} / ${duration.toFixed(1)} seconds`);
    }
    encoder.stdin.end();
    await completion;
  } catch (error) { encoder.kill(); await completion.catch(() => {}); throw error; }
  if (!smoke) await rename(temporary, path.join(root, 'output/marketing-video.mp4'));
}

const escapeHtml = value => value.replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
async function deliveryFiles(story, timing, root) {
  await writeFile(path.join(root, 'output/captions.srt'), timing.cues.map((cue, index) => `${index + 1}\n${timestamp(cue.start)} --> ${timestamp(cue.end)}\n${cue.text}\n`).join('\n'));
  await writeFile(path.join(root, 'output/captions.vtt'), 'WEBVTT\n\n' + timing.cues.map(cue => `${timestamp(cue.start, '.')} --> ${timestamp(cue.end, '.')}\n${cue.text}\n`).join('\n'));
  await writeFile(path.join(root, 'output/timing.json'), JSON.stringify({ duration: timing.duration, width: WIDTH, height: HEIGHT, fps: FPS, storyHash: hash(JSON.stringify(story)), narration: timing.profile, scenes: timing.scenes.map(({ id, start, duration }) => ({ id, start, duration })), captions: timing.cues }, null, 2) + '\n');
  await writeFile(path.join(root, 'watch.html'), `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${escapeHtml(story.title)}</title><style>body{margin:0;background:#f4f6f5;color:#152123;font-family:Bahnschrift,'Segoe UI',sans-serif;letter-spacing:0}main{max-width:1440px;padding:24px;margin:auto}h1{font-size:26px;overflow-wrap:anywhere}video{display:block;width:100%;aspect-ratio:16/9;background:#10191b}p{line-height:1.5}a{color:#007f84}</style><main><h1>${escapeHtml(story.title)}</h1><video controls playsinline preload="metadata" poster="output/thumbnail.jpg" aria-label="Narrated video with embedded captions"><source src="output/marketing-video.mp4" type="video/mp4"></video><p>${escapeHtml(story.disclosure)} Synthetic narration.</p><a href="output/marketing-video.mp4" download>Download MP4</a> &nbsp; <a href="output/captions.srt" download>Captions</a></main></html>`);
}

async function verifyVideo(story, root) {
  const filename = path.join(root, 'output/marketing-video.mp4');
  const timing = JSON.parse(await readFile(path.join(root, 'output/timing.json'), 'utf8'));
  assert.equal(timing.storyHash, hash(JSON.stringify(story)), 'Video does not match the current storyboard');
  assert.equal(timing.narration.narrationHash, narrationHash(story));
  let previous = 0;
  for (const cue of timing.captions) { assert(cue.start >= previous && cue.end > cue.start && cue.end <= timing.duration); previous = cue.end; }
  const metadata = spawnSync(ffmpeg, ['-hide_banner', '-i', filename], { encoding: 'utf8' });
  assert.match(metadata.stderr, /1920x1080/); assert.match(metadata.stderr, /Video: h264/); assert.match(metadata.stderr, /Audio: aac/);
  const decoded = spawnSync(ffmpeg, ['-v', 'error', '-i', filename, '-f', 'null', '-'], { encoding: 'utf8' });
  assert.equal(decoded.status, 0, decoded.stderr); assert.equal(decoded.stderr.trim(), '');
  const audio = spawnSync(ffmpeg, ['-hide_banner', '-i', filename, '-vn', '-af', 'volumedetect', '-f', 'null', '-'], { encoding: 'utf8' });
  assert.equal(audio.status, 0, audio.stderr);
  const peak = Number(audio.stderr.match(/max_volume: ([-\d.]+) dB/)?.[1]);
  assert(Number.isFinite(peak) && peak < 0 && peak > -45, 'Audio silent, clipped, or unmeasurable');
  for (const scene of timing.scenes) {
    const extraction = spawnSync(ffmpeg, ['-v', 'error', '-y', '-ss', String(scene.start + Math.min(6.5, scene.duration - 0.5)), '-i', filename, '-frames:v', '1', '-update', '1', path.join(root, 'work', `encoded-${scene.id}.png`)], { encoding: 'utf8' });
    assert.equal(extraction.status, 0, extraction.stderr);
  }
  await writeFile(path.join(root, 'output/verification.json'), JSON.stringify({ decoded: true, audioPeakDb: peak, duration: timing.duration, framesExtracted: timing.scenes.length, visualInspection: 'Required from hosting agent', listeningReview: 'Not automated' }, null, 2) + '\n');
  console.log(`PASS: full decode, captions, source hash, audio peak ${peak} dB; encoded frames ready for inspection.`);
}

export async function main(root, mode) {
  const story = JSON.parse(await readFile(path.join(root, 'storyboard.json'), 'utf8'));
  if (mode === '--narration-hash') { console.log(narrationHash(story)); return; }
  await validateStory(story, root, !['--preview', '--validate'].includes(mode));
  if (mode === '--validate') { console.log('PASS: storyboard and assets'); return; }
  await mkdir(path.join(root, 'output'), { recursive: true }); await mkdir(path.join(root, 'work'), { recursive: true });
  if (mode === '--verify') { await verifyVideo(story, root); return; }
  const images = new Map();
  for (const scene of story.scenes) if (scene.image) images.set(scene.image, await loadImage(await localAsset(root, scene.image)));
  const painter = createPainter(story, images);
  await previews(story, painter, root);
  console.log(`PASS: ${story.scenes.length} scenes, caption fit, assets and fonts`);
  if (mode === '--preview') return;
  const timing = await timeline(story, root);
  await soundtrack(timing, root);
  await encode(timing, painter, root, mode === '--smoke');
  if (mode !== '--smoke') await deliveryFiles(story, timing, root);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const mode = process.argv[2];
  assert([undefined, '--preview', '--validate', '--narration-hash', '--smoke', '--verify'].includes(mode), 'Unknown option');
  await main(path.dirname(fileURLToPath(import.meta.url)), mode);
}