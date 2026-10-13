import { fileURLToPath } from 'node:url';
process.chdir(fileURLToPath(new URL('.', import.meta.url)));
import { build } from 'esbuild';
import { writeFile, readFile, mkdir } from 'node:fs/promises';
import { schema, prompt } from './library.mjs';
await build({ absWorkingDir: fileURLToPath(new URL('.', import.meta.url)), entryPoints: ['worker.mjs'], bundle: true, platform: 'node', target: 'node22', minify: true, format: 'cjs', outfile: 'worker.cjs', legalComments: 'eof' });
await writeFile('schema.json', JSON.stringify(schema, null, 2) + '\n');
await writeFile('prompt.txt', prompt);
let notices = '# Third-party licenses for the bundled OpenUI parser\n\n';
for (const [name, file] of [['@openuidev/lang-core 1.0.0', 'node_modules/@openuidev/lang-core/LICENSE'], ['zod 4.3.6', 'node_modules/zod/LICENSE']]) {
  // lang-core's npm tarball may omit LICENSE; retain the verified upstream license.
  const license = await readFile(file, 'utf8').catch(() => readFile('OPENUI-LICENSE', 'utf8'));
  notices += `## ${name}\n\n${license}\n`;
}
await writeFile('THIRD_PARTY_NOTICES.txt', notices.trimEnd() + '\n');

await writeFile(new URL('../../../../skills/sage-openui/references/components.md', import.meta.url), '# Generated Sage OpenUI component contract\n\n' + prompt);

// Keep the checked-in native gallery fixtures aligned with the official parser.
const { gallery } = await import('./gallery.mjs');
const { parseSurface } = await import('./worker.mjs');
const fixturesDirectory = new URL('../../test/fixtures/', import.meta.url);
await mkdir(fixturesDirectory, { recursive: true });
await writeFile(new URL('openui_gallery.json', fixturesDirectory), JSON.stringify(gallery.map(item => ({ ...item, surface: { tree: parseSurface(item.code, true), complete: false } })), null, 2) + '\n');

// Exercise native rendering at intermediate parser states, not only complete
// trees. Keep these fixtures reproducible and part of the default Flutter suite.
function replay(code, streamId, stride) {
  const frames = [];
  let last;
  for (let end = 1; end <= code.length; end += stride) {
    const tree = parseSurface(code.slice(0, end), false, streamId);
    const serialized = JSON.stringify(tree);
    if (tree && serialized !== last) {
      frames.push({ tree, complete: false });
      last = serialized;
    }
  }
  frames.push({ tree: parseSurface(code, true, streamId), complete: true, surface_id: streamId });
  return frames;
}
await writeFile(new URL('openui_gallery_replay.json', fixturesDirectory), JSON.stringify(gallery.map(item => ({ name: item.name, frames: replay(item.code, item.name, 7) }))) + '\n');
const coffeeFile = new URL('openui_coffee_replay.json', fixturesDirectory);
const coffee = JSON.parse(await readFile(coffeeFile, 'utf8'));
await writeFile(coffeeFile, JSON.stringify({ code: coffee.code, frames: replay(coffee.code, 'coffee-replay', 1) }) + '\n');

const slideLayout = JSON.parse(await readFile('slide_layout.json', 'utf8'));
await writeFile(new URL('../../lib/src/ui/openui_slide_layout.dart', import.meta.url), '// Generated from slide_layout.json; shared with PPTX export.\nconst openUiSlideLayout = ' + JSON.stringify(slideLayout) + ';\n');

const tracker = await readFile(new URL('openui_running_tracker.openui', fixturesDirectory), 'utf8');
await writeFile(new URL('openui_running_tracker.json', fixturesDirectory), JSON.stringify(replay(tracker, 'tracker', 29)) + '\n');
