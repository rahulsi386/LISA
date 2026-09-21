import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, readdir, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { initialize } from '../scripts/initialize.mjs';
import { localAsset, validateStory, narrationHash, readWave, waveBuffer, timestamp, main } from '../resources/template/render.mjs';

const skill = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
async function fixture(context) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'lisa-video-test-'));
  context.after(() => rm(root, { recursive: true, force: true }));
  await initialize(root, 'Inventory Planner');
  await writeFile(path.join(root, 'assets/solution.svg'), '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400"><rect width="800" height="400" fill="#007f84"/><text x="50" y="200" font-size="48" fill="white">Test fixture: Inventory Planner</text></svg>');
  const story = JSON.parse(await readFile(path.join(root, 'storyboard.json'), 'utf8'));
  story.scenes.find(scene => scene.id === 'inspect').image = 'assets/solution.svg';
  return { root, story };
}

test('initializer creates a self-contained non-LISA project and preserves existing files', async context => {
  const { root, story } = await fixture(context);
  assert.equal(story.title, 'Inventory Planner');
  assert.equal(story.readyForRender, false);
  for (const name of ['package.json', 'package-lock.json', 'render.mjs', 'Narrate.ps1', 'requirements.txt', 'README.md']) assert((await readdir(root)).includes(name), name);
  await assert.rejects(initialize(root, 'Other solution'), /nonempty/);
  await assert.rejects(initialize(path.join(skill, 'forbidden-output'), 'Other solution'), /outside the installed plugin/);
});

test('story validates but delivery blocks unreviewed starter content', async context => {
  const { root, story } = await fixture(context);
  await validateStory(story, root);
  await assert.rejects(validateStory(story, root, true), /readyForRender/);
  story.readyForRender = true;
  await validateStory(story, root, true);
});

test('rejects repository links, duplicate IDs and unlabeled or unsupported evidence', async context => {
  const { root, story } = await fixture(context);
  const linked = structuredClone(story);
  linked.scenes[0].narration = ['Visit https://github.com/example/project'];
  await assert.rejects(validateStory(linked, root), /Repository links/);
  linked.allowRepositoryLinks = true;
  await validateStory(linked, root);
  const duplicate = structuredClone(story);
  duplicate.scenes[1].id = duplicate.scenes[0].id;
  await assert.rejects(validateStory(duplicate, root), /Duplicate/);
  const evidence = story.scenes.find(scene => scene.type === 'evidence');
  evidence.label = 'Everything passed';
  await assert.rejects(validateStory(story, root), /visible label/);
  evidence.evidenceKind = 'measured';
  await assert.rejects(validateStory(story, root), /source files/);
});

test('rejects missing images and traversal', async context => {
  const { root, story } = await fixture(context);
  await assert.rejects(localAsset(root, '../private.txt'), /project-relative/);
  await assert.rejects(localAsset(root, 'C:\\private.txt'), /project-relative/);
  delete story.scenes.find(scene => scene.type === 'screenshot').image;
  await assert.rejects(validateStory(story, root), /require an image/);
});

test('narration hash permits visual revisions but detects spoken copy changes', async context => {
  const { story } = await fixture(context);
  const original = narrationHash(story);
  story.scenes[0].heading = 'New heading';
  assert.equal(narrationHash(story), original);
  story.scenes[0].narration[0] = 'Changed speech.';
  assert.notEqual(narrationHash(story), original);
});

test('WAV contract and caption timestamps are deterministic', () => {
  assert.equal(readWave(waveBuffer(new Float32Array(48000))).duration, 1);
  assert.throws(() => readWave(Buffer.from('invalid')));
  assert.equal(timestamp(61.125), '00:01:01,125');
  assert.equal(timestamp(61.125, '.'), '00:01:01.125');
});

test('offline full render verifies video, captions, assets and stale narration detection', async context => {
  const { root, story } = await fixture(context);
  story.readyForRender = true;
  await writeFile(path.join(root, 'storyboard.json'), JSON.stringify(story));
  await main(root, '--preview');
  story.scenes = story.scenes.filter(scene => ['inspect', 'evaluate'].includes(scene.id));
  for (const scene of story.scenes) { scene.minimumDuration = 5; scene.narration = ['Synthetic test audio fixture.']; }
  await writeFile(path.join(root, 'storyboard.json'), JSON.stringify(story));
  const voiceDirectory = 'work/voice-test';
  await mkdir(path.join(root, voiceDirectory), { recursive: true });
  const audio = Float32Array.from({ length: 48000 }, (_, index) => Math.sin(index * 2 * Math.PI * 240 / 48000) * 0.2);
  for (const scene of story.scenes) await writeFile(path.join(root, voiceDirectory, `${scene.id}-0.wav`), waveBuffer(audio));
  await writeFile(path.join(root, voiceDirectory, 'narration-profile.json'), JSON.stringify({ narrationHash: narrationHash(story), preview: false, provider: 'Offline test tone, not speech' }));
  await writeFile(path.join(root, 'work/voice-current.json'), JSON.stringify({ directory: voiceDirectory }));
  await main(root, '--smoke');
  assert((await readdir(path.join(root, 'work'))).includes('smoke.mp4'));
  await main(root);
  await main(root, '--verify');
  const result = JSON.parse(await readFile(path.join(root, 'output/verification.json'), 'utf8'));
  assert.equal(result.decoded, true);
  assert.equal(result.framesExtracted, 2);
  const player = await readFile(path.join(root, 'watch.html'), 'utf8');
  assert(player.includes('Inventory Planner'));
  assert(!player.includes('github.com'));
  for (const match of player.matchAll(/(?:src|href|poster)="([^"]+)"/g)) await localAsset(root, match[1]);
  story.scenes[0].narration[0] = 'Changed speech.';
  await writeFile(path.join(root, 'storyboard.json'), JSON.stringify(story));
  await assert.rejects(main(root, '--smoke'), /stale/);
});