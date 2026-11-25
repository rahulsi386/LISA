import { cp, copyFile, mkdir, readdir, realpath, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import assert from 'node:assert/strict';

const skillRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export async function initialize(output, name) {
  assert(typeof output === 'string' && output.trim(), 'An explicit output directory is required');
  assert(typeof name === 'string' && name.trim() && name.length <= 100, 'Supply a solution name (1-100 characters)');
  const target = path.resolve(output);
  let ancestor = target;
  while (true) {
    try { ancestor = await realpath(ancestor); break; }
    catch (error) {
      if (error.code !== 'ENOENT') throw error;
      const parent = path.dirname(ancestor);
      assert(parent !== ancestor, 'Cannot resolve output location');
      ancestor = parent;
    }
  }
  const plugin = await realpath(path.resolve(skillRoot, '../..'));
  const relative = path.relative(plugin, ancestor);
  assert(relative.startsWith(`..${path.sep}`) || relative === '..' || path.isAbsolute(relative), 'Output must be outside the installed plugin');
  try { assert.equal((await readdir(target)).length, 0, 'Refusing to overwrite a nonempty production folder'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  await mkdir(target, { recursive: true });
  await cp(path.join(skillRoot, 'resources/template'), target, {
    recursive: true,
    filter: source => !path.relative(path.join(skillRoot, 'resources/template'), source).split(path.sep).includes('node_modules')
  });
  await copyFile(path.join(skillRoot, 'requirements.txt'), path.join(target, 'requirements.txt'));
  await copyFile(path.join(skillRoot, 'resources/production-guide.md'), path.join(target, 'README.md'));
  await mkdir(path.join(target, 'assets'), { recursive: true });
  await writeFile(path.join(target, '.gitignore'), 'node_modules/\nwork/\n');
  const story = {
    title: name.trim(), audience: 'Developers', readyForRender: false, allowRepositoryLinks: false,
    disclosure: 'Illustrative developer journey. Sample observations are not live deployment results.',
    scenes: [
      { id: 'intro', type: 'title', heading: name.trim(), label: 'DEVELOPER JOURNEY', narration: [`Meet ${name.trim()}.`, 'Start with the problem your developer needs to solve.'], minimumDuration: 7 },
      { id: 'brief', type: 'steps', heading: 'Start with your brief.', items: ['Define the requirement', 'Choose approved sources', 'Set the target environment'], narration: ['Describe the developer inputs for this solution.'], minimumDuration: 8 },
      { id: 'build', type: 'terminal', heading: 'Create the solution.', commands: ['Replace this line with a verified command.'], narration: ['Explain the actual implementation action and its safeguards.'], minimumDuration: 8 },
      { id: 'inspect', type: 'screenshot', heading: 'Inspect what you created.', image: 'assets/solution.png', label: 'ILLUSTRATIVE UI / REPLACE WITH APPROVED CAPTURE', narration: ['Show the current solution interface and inspect the resulting output.'], minimumDuration: 9 },
      { id: 'evaluate', type: 'evidence', heading: 'Review the evidence.', evidenceKind: 'illustrative', label: 'SAMPLE FINDING / NOT MEASURED', items: ['Test: replace with an actual scenario', 'Observation: label sample or measured data', 'Decision: ground the outcome in evidence'], narration: ['Explain a concrete test and the finding the developer reviews.'], minimumDuration: 9 },
      { id: 'outro', type: 'closing', heading: 'Build. Inspect. Evaluate.', label: name.trim(), narration: ['Close with the next action for this solution.'], minimumDuration: 7 }
    ]
  };
  await writeFile(path.join(target, 'storyboard.json'), JSON.stringify(story, null, 2) + '\n');
  return target;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { values } = parseArgs({ options: { output: { type: 'string' }, name: { type: 'string' } } });
  console.log(`Production folder: ${await initialize(values.output, values.name)}`);
  console.log('Replace starter copy, add assets/solution.png, preview, then set readyForRender to true.');
}