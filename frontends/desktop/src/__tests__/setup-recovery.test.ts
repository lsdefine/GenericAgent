import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Window } from 'happy-dom';
import { describe, expect, it, vi } from 'vitest';
import type { BootstrapFailureCode, BootstrapSnapshot } from '../loading/types';

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const fallbackHtml = fs.readFileSync(path.join(desktopRoot, 'public/fallback.html'), 'utf8');
const fallbackScript = fallbackHtml.match(/<script>([\s\S]*)<\/script>/)?.[1] ?? '';
const fallbackMarkup = fallbackHtml.replace(/<script>[\s\S]*<\/script>/, '');

function failedSnapshot(code: BootstrapFailureCode): BootstrapSnapshot {
  return {
    seq: 1,
    mode: 'cold_start',
    phase: 'failed',
    stage: 'service',
    progress: 90,
    failure: { code, detail: 'filtered technical detail' },
    diagnostics: {
      buildId: 'build-123',
      platform: 'windows',
      projectDir: 'C:\\GenericAgent',
      pythonPath: 'C:\\Python\\python.exe',
      portState: code === 'port_conflict' ? 'foreign' : 'free',
      bridgeIdentity: null,
      recentLogs: ['stderr: filtered startup failure'],
    },
  };
}

function idleSnapshot(): BootstrapSnapshot {
  const snapshot = failedSnapshot('unknown');
  return { ...snapshot, seq: 0, phase: 'idle', stage: null, progress: 0, failure: null };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function byId<T>(recoveryWindow: Window, id: string): T {
  const element = recoveryWindow.document.getElementById(id);
  if (!element) throw new Error(`missing #${id}`);
  return element as unknown as T;
}

function createRecoveryWindow(options?: {
  snapshots?: BootstrapSnapshot[];
  retryError?: Error;
}) {
  const recoveryWindow = new Window({ url: 'tauri://localhost/fallback.html' });
  const snapshots = [...(options?.snapshots ?? [failedSnapshot('service_timeout')])];
  const calls: Array<{ command: string; args?: unknown }> = [];
  let bootstrapHandler: ((event: { payload: BootstrapSnapshot }) => void) | undefined;
  const invoke = vi.fn(async (command: string, args?: unknown) => {
    calls.push({ command, args });
    if (command === 'get_config') return ['C:\\SavedPython\\python.exe', 'C:\\SavedGA'];
    if (command === 'get_bootstrap_snapshot') return snapshots.shift() ?? failedSnapshot('unknown');
    if (command === 'retry_bootstrap' && options?.retryError) throw options.retryError;
    return undefined;
  });

  Object.defineProperty(recoveryWindow.navigator, 'language', { value: 'zh-CN', configurable: true });
  Object.defineProperty(recoveryWindow, '__TAURI__', {
    value: {
      core: { invoke },
      event: {
        listen: vi.fn(async (_name: string, handler: (event: { payload: BootstrapSnapshot }) => void) => {
          bootstrapHandler = handler;
          return () => {};
        }),
      },
    },
    configurable: true,
  });
  recoveryWindow.document.write(fallbackMarkup);
  recoveryWindow.eval(fallbackScript);
  return {
    recoveryWindow,
    invoke,
    calls,
    emitBootstrap: (snapshot: BootstrapSnapshot) => bootstrapHandler?.({ payload: snapshot }),
  };
}

describe('setup bootstrap recovery', () => {
  it('updates from an idle hidden-window snapshot when a later failure event arrives', async () => {
    const { recoveryWindow, emitBootstrap } = createRecoveryWindow({ snapshots: [idleSnapshot()] });
    await flush();

    emitBootstrap(failedSnapshot('service_exited'));
    await flush();

    expect(recoveryWindow.document.getElementById('failure-title')?.textContent).toBe('后台服务意外退出');
    expect(recoveryWindow.document.getElementById('diagnostics')?.textContent).toContain(
      'failure_code: service_exited',
    );
  });

  it('prefills saved paths, explains the failure, and keeps diagnostics collapsed', async () => {
    const { recoveryWindow } = createRecoveryWindow();
    await flush();

    const document = recoveryWindow.document;
    expect(byId<{ value: string }>(recoveryWindow, 'project-dir').value).toBe('C:\\SavedGA');
    expect(byId<{ value: string }>(recoveryWindow, 'python-path').value).toBe('C:\\SavedPython\\python.exe');
    expect(document.getElementById('failure-title')?.textContent).toBe('后台服务启动超时');
    expect((document.querySelector('details') as unknown as { open: boolean }).open).toBe(false);
    expect(document.getElementById('diagnostics')?.textContent).toContain('failure_code: service_timeout');
  });

  it('retries with the edited paths and refreshes the failure snapshot in place', async () => {
    const retryFailure = failedSnapshot('port_conflict');
    retryFailure.seq = 2;
    const { recoveryWindow, calls } = createRecoveryWindow({
      snapshots: [failedSnapshot('spawn_failed'), retryFailure],
      retryError: new Error('retry failed'),
    });
    await flush();

    const document = recoveryWindow.document;
    byId<{ value: string }>(recoveryWindow, 'project-dir').value = 'D:\\GenericAgent';
    byId<{ value: string }>(recoveryWindow, 'python-path').value = 'D:\\venv\\python.exe';
    byId<{ click: () => void }>(recoveryWindow, 'retry').click();
    await flush();

    expect(calls).toContainEqual({
      command: 'retry_bootstrap',
      args: { pythonPath: 'D:\\venv\\python.exe', projectDir: 'D:\\GenericAgent' },
    });
    expect(document.getElementById('failure-title')?.textContent).toBe('本地连接被占用');
    expect(byId<{ disabled: boolean }>(recoveryWindow, 'retry').disabled).toBe(false);
  });

  it('keeps the retry action busy when Rust completes startup successfully', async () => {
    const { recoveryWindow, calls } = createRecoveryWindow();
    await flush();

    byId<{ click: () => void }>(recoveryWindow, 'retry').click();
    await flush();

    expect(calls.some(({ command }) => command === 'retry_bootstrap')).toBe(true);
    expect(byId<{ disabled: boolean; textContent: string }>(recoveryWindow, 'retry')).toMatchObject({
      disabled: true,
      textContent: '正在重试…',
    });
  });

  it('copies the stable diagnostics text when the Clipboard API is available', async () => {
    const { recoveryWindow } = createRecoveryWindow();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(recoveryWindow.navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    await flush();

    byId<{ click: () => void }>(recoveryWindow, 'copy').click();
    await flush();

    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('GenericAgent Desktop startup diagnostics'));
    expect(recoveryWindow.document.getElementById('copy-status')?.textContent).toBe(
      '已复制，可粘贴给部署智能体排查。',
    );
  });
});
