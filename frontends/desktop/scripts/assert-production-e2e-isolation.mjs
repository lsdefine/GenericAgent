import { readdir, readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';

const dist = resolve(process.cwd(), 'dist');
const forbidden = ['__wdio_original_core__', '[WDIO Tauri Plugin]', 'plugin:wdio|'];

async function files(root) {
  const result = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) result.push(...await files(path));
    else result.push(path);
  }
  return result;
}

for (const path of await files(dist)) {
  if (!/\.(?:html|js|css)$/.test(path)) continue;
  const content = await readFile(path, 'utf8');
  const marker = forbidden.find((value) => content.includes(value));
  if (marker) throw new Error(`Production build contains E2E marker ${marker} in ${path}`);
}
process.stdout.write('Production frontend contains no WDIO plugin markers.\n');
