import { randomUUID } from 'node:crypto';
import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { appendFile, cp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { basename, dirname, join, resolve } from 'node:path';
import { FakeOpenAI } from './fake-openai';
import { allocateLoopbackPort, pathsReferToSameEntry, redactEvidence } from './runtime';
import { cleanupSandbox, createSandbox, type SandboxLayout } from './sandbox';
import type { E2EContextFile } from './context';

type HarnessMode = 'browser' | 'desktop';

interface StartOptions {
  mode: HarnessMode;
  desktopRoot: string;
  pythonPath: string;
  application?: string;
}

interface ManagedProcess {
  name: string;
  child: ChildProcess;
}

function inheritedEnv(env: Record<string, string>): NodeJS.ProcessEnv {
  return Object.fromEntries(Object.entries(env));
}

async function waitForHttp(url: string, timeoutMs = 30_000): Promise<Response> {
  const deadline = Date.now() + timeoutMs;
  let lastError = 'not started';
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = String(error);
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError}`);
}

async function stopChild(processInfo: ManagedProcess | null, hard = false): Promise<void> {
  if (!processInfo || processInfo.child.exitCode !== null) return;
  const child = processInfo.child;
  if (process.platform === 'win32' && child.pid) {
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    return;
  }
  child.kill(hard ? 'SIGKILL' : 'SIGTERM');
  await Promise.race([
    new Promise<void>((resolveExit) => child.once('exit', () => resolveExit())),
    new Promise<void>((resolveWait) => setTimeout(resolveWait, 3_000)),
  ]);
  if (child.exitCode === null) child.kill('SIGKILL');
}

async function jsonBody(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>;
}

function jsonResponse(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8' });
  response.end(JSON.stringify(body));
}

export class DesktopE2EHarness {
  private readonly options: StartOptions;
  private fake = new FakeOpenAI();
  private sandbox: SandboxLayout | null = null;
  private bridge: ManagedProcess | null = null;
  private vite: ManagedProcess | null = null;
  private controlServer: Server | null = null;
  private foreignBridge: Server | null = null;
  private contextPath = '';
  private failed = false;
  private bridgePort = 0;
  private vitePort = 0;
  private controlToken = randomUUID();
  private fakeBase = '';

  constructor(options: StartOptions) {
    this.options = options;
  }

  get contextFile(): string { return this.contextPath; }

  async start(): Promise<E2EContextFile> {
    const desktopRoot = resolve(this.options.desktopRoot);
    const repoRoot = resolve(desktopRoot, '..', '..');
    this.bridgePort = await allocateLoopbackPort();
    this.vitePort = await allocateLoopbackPort();
    this.fakeBase = await this.fake.start();
    this.sandbox = await createSandbox({
      repoRoot,
      pythonPath: this.options.pythonPath,
      fakeBaseUrl: this.fakeBase,
      bridgePort: this.bridgePort,
      vitePort: this.vitePort,
      controlToken: this.controlToken,
    });

    if (this.options.mode === 'browser') {
      await this.seedLegacyHistory();
      await this.startBridge();
      await this.startVite(desktopRoot);
    }
    const controlBase = await this.startControlServer();
    const context: E2EContextFile = {
      mode: this.options.mode,
      sandboxRoot: this.sandbox.root,
      reports: this.sandbox.reports,
      bridgeBase: `http://127.0.0.1:${this.bridgePort}`,
      viteUrl: this.options.mode === 'browser' ? `http://127.0.0.1:${this.vitePort}` : undefined,
      controlBase,
      controlToken: this.controlToken,
      application: this.options.application,
      appEnv: this.options.mode === 'desktop' ? this.sandbox.env : undefined,
    };
    this.contextPath = join(this.sandbox.root, '.e2e-context.json');
    await writeFile(this.contextPath, JSON.stringify(context, null, 2), 'utf8');
    await this.captureSnapshot('started');
    return context;
  }

  markFailed(): void { this.failed = true; }

  async stop(): Promise<void> {
    await this.captureSnapshot(this.failed ? 'failed' : 'completed').catch(() => {});
    await stopChild(this.vite);
    await stopChild(this.bridge);
    await this.releaseForeignBridge();
    if (this.options.mode === 'desktop') await this.stopExternalBridge().catch(() => {});
    this.fake.releaseHeld();
    await this.fake.stop();
    if (this.controlServer) {
      await new Promise<void>((resolveClose) => this.controlServer!.close(() => resolveClose()));
      this.controlServer = null;
    }
    const sandbox = this.sandbox;
    this.sandbox = null;
    if (sandbox && !this.failed) {
      await cleanupSandbox(sandbox.root);
    } else if (sandbox) {
      const artifactRoot = resolve(
        process.env.GA_E2E_ARTIFACT_DIR || join(this.options.desktopRoot, 'e2e-results'),
        `${basename(sandbox.root)}-${Date.now()}`,
      );
      await mkdir(dirname(artifactRoot), { recursive: true });
      await cp(sandbox.reports, artifactRoot, { recursive: true });
      process.stderr.write(`E2E report copied to ${artifactRoot}\n`);
      process.stderr.write(`E2E failure evidence preserved at ${sandbox.root}\n`);
    }
  }

  private async startBridge(): Promise<void> {
    const sandbox = this.requireSandbox();
    const script = join(sandbox.root, 'frontends', 'desktop_bridge.py');
    this.bridge = this.spawnLogged('bridge', this.options.pythonPath, [script], sandbox.root, sandbox.env);
    const identityResponse = await waitForHttp(`http://127.0.0.1:${this.bridgePort}/services/identity`);
    const identity = await identityResponse.json() as { ga_root?: string };
    if (!pathsReferToSameEntry(String(identity.ga_root || ''), sandbox.root)) {
      throw new Error(`Bridge escaped E2E sandbox: ${identity.ga_root || '<missing>'}`);
    }
  }

  private async seedLegacyHistory(): Promise<void> {
    const sandbox = this.requireSandbox();
    const temp = join(sandbox.root, 'temp');
    await mkdir(temp, { recursive: true });
    await writeFile(join(temp, 'desktop_token_history.json'), JSON.stringify({
      history: [{
        sessionId: 'legacy-e2e',
        title: 'Legacy E2E',
        model: 'legacy-model',
        ts: 1_700_000_000,
      }],
      snap: {
        'GA-legacy-e2e': { input: 2, output: 3, cacheCreate: 0, cacheRead: 1 },
      },
    }), 'utf8');
  }

  private async restartBridge(hard = false): Promise<void> {
    await stopChild(this.bridge, hard);
    this.bridge = null;
    await this.startBridge();
  }

  private async startVite(desktopRoot: string): Promise<void> {
    const sandbox = this.requireSandbox();
    const viteBin = join(desktopRoot, 'node_modules', 'vite', 'bin', 'vite.js');
    this.vite = this.spawnLogged(
      'vite',
      process.execPath,
      [viteBin, '--host', '127.0.0.1', '--port', String(this.vitePort), '--strictPort'],
      desktopRoot,
      sandbox.env,
    );
    await waitForHttp(`http://127.0.0.1:${this.vitePort}`);
  }

  private spawnLogged(name: string, executable: string, args: string[], cwd: string, env: Record<string, string>): ManagedProcess {
    const sandbox = this.requireSandbox();
    const child = spawn(executable, args, {
      cwd,
      env: inheritedEnv(env),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    const logPath = join(sandbox.reports, `${name}.log`);
    const capture = (chunk: Buffer) => void appendFile(logPath, redactEvidence(chunk.toString('utf8')), 'utf8');
    child.stdout?.on('data', capture);
    child.stderr?.on('data', capture);
    child.once('error', (error) => void appendFile(logPath, `\n[spawn error] ${error}\n`, 'utf8'));
    return { name, child };
  }

  private async startControlServer(): Promise<string> {
    this.controlServer = createServer((request, response) => void this.handleControl(request, response));
    await new Promise<void>((resolveListen, reject) => {
      this.controlServer!.once('error', reject);
      this.controlServer!.listen(0, '127.0.0.1', resolveListen);
    });
    const { port } = this.controlServer.address() as AddressInfo;
    return `http://127.0.0.1:${port}`;
  }

  private async handleControl(request: IncomingMessage, response: ServerResponse): Promise<void> {
    try {
      if (request.socket.remoteAddress !== '127.0.0.1' && request.socket.remoteAddress !== '::ffff:127.0.0.1') {
        jsonResponse(response, 403, { error: 'loopback only' }); return;
      }
      if (request.headers['x-ga-e2e-token'] !== this.controlToken) {
        jsonResponse(response, 403, { error: 'forbidden' }); return;
      }
      const url = new URL(request.url || '/', 'http://127.0.0.1');
      if (request.method === 'GET' && url.pathname === '/fake/transcript') {
        jsonResponse(response, 200, { requests: this.fake.transcript() }); return;
      }
      if (request.method === 'POST' && url.pathname === '/bridge/restart') {
        await this.restartBridge(false);
        jsonResponse(response, 200, { ok: true }); return;
      }
      if (request.method === 'POST' && url.pathname === '/bridge/crash-after-second-call') {
        await this.fake.waitForScenarioRequests('two-call-hang', 2, 20_000);
        await this.restartBridge(true);
        jsonResponse(response, 200, { ok: true }); return;
      }
      if (request.method === 'POST' && url.pathname === '/bridge/kill-external') {
        if (this.options.mode !== 'desktop') {
          jsonResponse(response, 400, { error: 'desktop mode only' }); return;
        }
        await this.stopExternalBridge();
        jsonResponse(response, 200, { ok: true }); return;
      }
      if (request.method === 'POST' && url.pathname === '/port/occupy-bridge') {
        if (this.options.mode !== 'desktop') {
          jsonResponse(response, 400, { error: 'desktop mode only' }); return;
        }
        await this.stopExternalBridge();
        await this.occupyBridgePort();
        jsonResponse(response, 200, { ok: true }); return;
      }
      if (request.method === 'POST' && url.pathname === '/port/release-bridge') {
        await this.releaseForeignBridge();
        jsonResponse(response, 200, { ok: true }); return;
      }
      if (request.method === 'POST' && url.pathname === '/ledger/corrupt-tail') {
        const ledger = join(this.requireSandbox().root, 'temp', 'token_ledger.jsonl');
        await appendFile(ledger, '{"truncated":\nnot-json\n', 'utf8');
        jsonResponse(response, 200, { ok: true }); return;
      }
      if (request.method === 'POST' && url.pathname === '/settings/language') {
        const body = await jsonBody(request);
        const lang = body.lang === 'en' ? 'en' : body.lang === 'zh' ? 'zh' : null;
        if (!lang) { jsonResponse(response, 400, { error: 'lang must be zh or en' }); return; }
        const settingsPath = join(this.requireSandbox().home, '.ga_desktop_settings.json');
        const settings = JSON.parse(await readFile(settingsPath, 'utf8')) as Record<string, unknown>;
        settings.lang = lang;
        await writeFile(settingsPath, JSON.stringify(settings, null, 2), 'utf8');
        await this.restartBridge(false);
        jsonResponse(response, 200, { ok: true, lang }); return;
      }
      if (request.method === 'POST' && url.pathname === '/snapshot') {
        await this.captureSnapshot('requested');
        jsonResponse(response, 200, { ok: true }); return;
      }
      jsonResponse(response, 404, { error: 'not found' });
    } catch (error) {
      jsonResponse(response, 500, { error: String(error) });
    }
  }

  private async captureSnapshot(name: string): Promise<void> {
    const sandbox = this.requireSandbox();
    await mkdir(sandbox.reports, { recursive: true });
    const endpoints: Record<string, unknown> = {};
    for (const path of ['/services/identity', '/sessions', '/token-history']) {
      try {
        const response = await fetch(`http://127.0.0.1:${this.bridgePort}${path}`);
        endpoints[path] = await response.json();
      } catch (error) {
        endpoints[path] = { error: String(error) };
      }
    }
    const ledgerPath = join(sandbox.root, 'temp', 'token_ledger.jsonl');
    let ledger = '';
    try { ledger = await readFile(ledgerPath, 'utf8'); } catch { /* no calls yet */ }
    await writeFile(join(sandbox.reports, `${name}-snapshot.json`), JSON.stringify({
      time: new Date().toISOString(),
      sandbox: sandbox.root,
      processes: {
        bridge: this.bridge?.child.pid ?? null,
        vite: this.vite?.child.pid ?? null,
      },
      ports: { bridge: this.bridgePort, vite: this.vitePort },
      endpoints,
      fakeRequests: this.fake.transcript(),
    }, null, 2), 'utf8');
    if (ledger) await writeFile(join(sandbox.reports, `${name}-ledger.jsonl`), ledger, 'utf8');
    try {
      await cp(
        join(sandbox.root, 'temp', 'desktop_sessions'),
        join(sandbox.reports, `${name}-sessions`),
        { recursive: true },
      );
    } catch { /* no persisted sessions yet */ }
  }

  private async stopExternalBridge(): Promise<void> {
    const sandbox = this.requireSandbox();
    let identity: { ga_root?: string; pid?: number };
    try {
      identity = await (await fetch(`http://127.0.0.1:${this.bridgePort}/services/identity`)).json() as typeof identity;
    } catch {
      return;
    }
    if (!identity.pid) return;
    if (!pathsReferToSameEntry(String(identity.ga_root || ''), sandbox.root)) {
      throw new Error(`Refusing to stop bridge outside sandbox: ${identity.ga_root}`);
    }
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(identity.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      process.kill(identity.pid, 'SIGKILL');
    }
  }

  private async occupyBridgePort(): Promise<void> {
    await this.releaseForeignBridge();
    const deadline = Date.now() + 5_000;
    while (Date.now() < deadline) {
      const server = createServer((request, response) => {
        if (request.url === '/services/identity') {
          jsonResponse(response, 200, { service: 'foreign-e2e-listener' });
        } else {
          jsonResponse(response, 503, { error: 'foreign listener' });
        }
      });
      try {
        await new Promise<void>((resolveListen, reject) => {
          server.once('error', reject);
          server.listen(this.bridgePort, '127.0.0.1', resolveListen);
        });
        this.foreignBridge = server;
        return;
      } catch (error) {
        server.close();
        if ((error as NodeJS.ErrnoException).code !== 'EADDRINUSE') throw error;
        await new Promise((resolveWait) => setTimeout(resolveWait, 100));
      }
    }
    throw new Error(`Timed out occupying bridge port ${this.bridgePort}`);
  }

  private async releaseForeignBridge(): Promise<void> {
    const server = this.foreignBridge;
    this.foreignBridge = null;
    if (!server) return;
    await new Promise<void>((resolveClose) => server.close(() => resolveClose()));
  }

  private requireSandbox(): SandboxLayout {
    if (!this.sandbox) throw new Error('E2E sandbox has not started');
    return this.sandbox;
  }
}
