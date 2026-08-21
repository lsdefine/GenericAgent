import { execFileSync } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { tmpdir } from 'node:os';
import { assertLoopbackUrl, assertSandboxRoot } from './runtime';

export interface SandboxOptions {
  repoRoot: string;
  pythonPath: string;
  fakeBaseUrl: string;
  bridgePort: number;
  vitePort: number;
  controlToken: string;
  files?: string[];
}

export interface SandboxLayout {
  root: string;
  home: string;
  reports: string;
  env: Record<string, string>;
}

const EXCLUDED_PREFIXES = [
  '.agents/', '.codex/', '.trellis/', '.claude/', '.git/',
  'frontends/desktop/node_modules/', 'frontends/desktop/dist/',
  'frontends/desktop/src-tauri/target/', 'frontends/desktop/e2e-results/',
  'temp/', '.venv/',
];

function workspaceFiles(repoRoot: string): string[] {
  const output = execFileSync(
    'git',
    ['ls-files', '--cached', '--others', '--exclude-standard', '-z'],
    { cwd: repoRoot, encoding: 'utf8' },
  );
  return output.split('\0').filter(Boolean).filter((path) =>
    !EXCLUDED_PREFIXES.some((prefix) => path === prefix.slice(0, -1) || path.startsWith(prefix)),
  );
}

function safeRelativePath(path: string): string {
  const normalized = path.replaceAll('\\', '/');
  if (!normalized || normalized.startsWith('/') || normalized.split('/').includes('..')) {
    throw new Error(`Unsafe workspace path: ${path}`);
  }
  return normalized;
}

async function copySelectedFiles(sourceRoot: string, targetRoot: string, files: string[]): Promise<void> {
  for (const raw of files) {
    const path = safeRelativePath(raw);
    const source = resolve(sourceRoot, path);
    const target = resolve(targetRoot, path);
    const rel = relative(targetRoot, target);
    if (rel.startsWith(`..${sep}`) || rel === '..') throw new Error(`Path escaped sandbox: ${path}`);
    await mkdir(dirname(target), { recursive: true });
    try {
      await copyFile(source, target);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    }
  }
}

function fakeMykey(fakeBaseUrl: string): string {
  const base = `${assertLoopbackUrl(fakeBaseUrl).replace(/\/+$/, '')}/v1`;
  return [
    'native_oai_config = {',
    "    'name': 'GenericAgent E2E',",
    "    'apikey': 'e2e-dummy-key',",
    `    'apibase': ${JSON.stringify(base)},`,
    "    'model': 'e2e-model',",
    "    'api_mode': 'chat_completions',",
    "    'stream': True,",
    "    'max_retries': 0,",
    "    'connect_timeout': 2,",
    "    'read_timeout': 30,",
    '}',
    '',
  ].join('\n');
}

export async function createSandbox(options: SandboxOptions): Promise<SandboxLayout> {
  assertLoopbackUrl(options.fakeBaseUrl);
  if (!options.controlToken.trim()) throw new Error('E2E control token is required');
  const repoRoot = resolve(options.repoRoot);
  const root = await mkdtemp(join(tmpdir(), 'ga-desktop-e2e-'));
  const home = join(root, '.home');
  const reports = join(root, 'e2e-report');
  await mkdir(home, { recursive: true });
  await mkdir(reports, { recursive: true });
  await writeFile(join(root, '.ga-e2e-sandbox'), 'v1\n', 'utf8');
  await copySelectedFiles(repoRoot, root, options.files ?? workspaceFiles(repoRoot));
  await writeFile(join(root, 'mykey.py'), fakeMykey(options.fakeBaseUrl), 'utf8');
  await writeFile(join(home, '.ga_desktop_settings.json'), JSON.stringify({
    lang: 'zh',
    python_path: options.pythonPath,
    project_dir: root,
    ui: { llmNo: 0 },
  }, null, 2), 'utf8');

  const inherited = Object.fromEntries(
    Object.entries(process.env).filter((entry): entry is [string, string] => typeof entry[1] === 'string'),
  );
  const env = {
    ...inherited,
    HOME: home,
    USERPROFILE: home,
    GA_E2E: '1',
    GA_E2E_SETTINGS_PATH: join(home, '.ga_desktop_settings.json'),
    GA_E2E_CONTROL_TOKEN: options.controlToken,
    GA_DESKTOP_E2E_REPORT_DIR: reports,
    BRIDGE_HOST: '127.0.0.1',
    BRIDGE_PORT: String(options.bridgePort),
    VITE_BRIDGE_BASE: `http://127.0.0.1:${options.bridgePort}`,
    VITE_GA_E2E: '1',
    VITE_PORT: String(options.vitePort),
    NO_PROXY: '127.0.0.1,localhost,::1',
    no_proxy: '127.0.0.1,localhost,::1',
    PYTHONUNBUFFERED: '1',
    PYTHONIOENCODING: 'utf-8',
  };
  return { root, home, reports, env };
}

export async function cleanupSandbox(root: string): Promise<void> {
  await rm(assertSandboxRoot(root), { recursive: true, force: true });
}
