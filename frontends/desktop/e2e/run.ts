import { existsSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { DesktopE2EHarness } from './harness/orchestrator';

function argument(name: string): string | undefined {
  const prefix = `--${name}=`;
  return process.argv.find((value) => value.startsWith(prefix))?.slice(prefix.length);
}

function pythonPath(repoRoot: string): string {
  const configured = process.env.GA_E2E_PYTHON;
  if (configured) return configured;
  const worktrees = spawnSync('git', ['worktree', 'list', '--porcelain'], {
    cwd: repoRoot,
    encoding: 'utf8',
  }).stdout.split(/\r?\n/).filter((line) => line.startsWith('worktree ')).map((line) => line.slice(9));
  const roots = [repoRoot, ...worktrees];
  const candidates = process.platform === 'win32'
    ? [...roots.map((root) => resolve(root, '.venv', 'Scripts', 'python.exe')), 'python']
    : [
        ...(process.env.VIRTUAL_ENV ? [resolve(process.env.VIRTUAL_ENV, 'bin', 'python')] : []),
        ...roots.map((root) => resolve(root, '.venv', 'bin', 'python')),
        'python3',
        'python',
      ];
  const compatible = candidates.find((candidate) => {
    if (candidate.includes('/') && !existsSync(candidate)) return false;
    return spawnSync(candidate, ['-c', 'import aiohttp'], { stdio: 'ignore' }).status === 0;
  });
  if (!compatible) throw new Error('No Python runtime with aiohttp found; set GA_E2E_PYTHON');
  return compatible;
}

async function run(): Promise<void> {
  const mode = argument('mode') === 'desktop' ? 'desktop' : 'browser';
  const suite = argument('suite') === 'full' ? 'full' : 'smoke';
  const desktopRoot = resolve(process.cwd());
  const repoRoot = resolve(desktopRoot, '..', '..');
  const harness = new DesktopE2EHarness({
    mode,
    desktopRoot,
    pythonPath: pythonPath(repoRoot),
    application: process.env.GA_E2E_APPLICATION,
  });
  let exitCode = 1;
  try {
    const context = await harness.start();
    if (mode === 'desktop' && !context.application) {
      const build = spawn('npm', [
        'run', 'tauri', 'build', '--', '--no-bundle', '--features', 'e2e',
        '--config', 'src-tauri/tauri.e2e.conf.json',
      ], {
        cwd: desktopRoot,
        env: {
          ...process.env,
          ...context.appEnv,
          HOME: process.env.HOME,
          USERPROFILE: process.env.USERPROFILE,
        },
        stdio: 'inherit',
        shell: process.platform === 'win32',
      });
      const buildCode = await new Promise<number>((resolveExit, reject) => {
        build.once('error', reject);
        build.once('exit', (code) => resolveExit(code ?? 1));
      });
      if (buildCode !== 0) throw new Error(`Tauri E2E build failed with exit code ${buildCode}`);
      const binary = resolve(
        desktopRoot,
        'src-tauri',
        'target',
        'release',
        process.platform === 'win32' ? 'ga-desktop.exe' : 'ga-desktop',
      );
      if (!existsSync(binary)) throw new Error(`Tauri E2E binary not found: ${binary}`);
      context.application = binary;
      writeFileSync(harness.contextFile, JSON.stringify(context, null, 2), 'utf8');
    }
    const config = resolve(desktopRoot, 'e2e', `wdio.${mode}.conf.ts`);
    const wdio = resolve(desktopRoot, 'node_modules', '@wdio', 'cli', 'bin', 'wdio.js');
    const child = spawn(process.execPath, [wdio, 'run', config], {
      cwd: desktopRoot,
      env: { ...process.env, GA_E2E_CONTEXT_FILE: harness.contextFile, GA_E2E_SUITE: suite },
      stdio: 'inherit',
    });
    exitCode = await new Promise<number>((resolveExit, reject) => {
      child.once('error', reject);
      child.once('exit', (code) => resolveExit(code ?? 1));
    });
    if (exitCode !== 0) harness.markFailed();
  } catch (error) {
    harness.markFailed();
    throw error;
  } finally {
    await harness.stop();
  }
  process.exitCode = exitCode;
}

void run().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack : error}\n`);
  process.exitCode = 1;
});
