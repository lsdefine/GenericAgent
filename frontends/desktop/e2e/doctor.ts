import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

interface Check { name: string; ok: boolean; detail: string }

function executable(name: string, args = ['--version']): Check {
  const result = spawnSync(name, args, { encoding: 'utf8' });
  const output = `${result.stdout || ''}${result.stderr || ''}`.trim().split(/\r?\n/)[0] || 'not found';
  return { name, ok: result.status === 0, detail: output };
}

const root = resolve(process.cwd());
const repoRoot = resolve(root, '..', '..');
const worktreeOutput = spawnSync('git', ['worktree', 'list', '--porcelain'], { cwd: repoRoot, encoding: 'utf8' }).stdout;
const worktrees = worktreeOutput.split(/\r?\n/)
  .filter((line) => line.startsWith('worktree '))
  .map((line) => line.slice(9));
const pythonCandidates = process.platform === 'win32'
  ? [repoRoot, ...worktrees].map((path) => resolve(path, '.venv', 'Scripts', 'python.exe')).concat('python')
  : [repoRoot, ...worktrees].map((path) => resolve(path, '.venv', 'bin', 'python')).concat('python3', 'python');
const python = pythonCandidates.find((candidate) =>
  (!candidate.includes('/') || existsSync(candidate))
  && spawnSync(candidate, ['-c', 'import aiohttp'], { stdio: 'ignore' }).status === 0,
);
const checks: Check[] = [
  executable(process.execPath, ['--version']),
  python
    ? executable(python, ['-c', 'import aiohttp; print("aiohttp available")'])
    : { name: 'Python bridge runtime', ok: false, detail: 'set GA_E2E_PYTHON to a Python with aiohttp' },
  executable('cargo'),
  { name: 'WDIO service', ok: existsSync(resolve(root, 'node_modules/@wdio/tauri-service')), detail: 'node_modules/@wdio/tauri-service' },
  { name: 'Tauri config', ok: existsSync(resolve(root, 'src-tauri/tauri.e2e.conf.json')), detail: 'src-tauri/tauri.e2e.conf.json' },
];

for (const check of checks) {
  process.stdout.write(`${check.ok ? 'OK ' : 'FAIL '} ${check.name}: ${check.detail}\n`);
}
if (checks.some((check) => !check.ok)) process.exitCode = 1;
