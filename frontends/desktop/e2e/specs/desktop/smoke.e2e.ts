import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, relative, sep } from 'node:path';
import { ChatPage } from '../../pages/ChatPage';
import { UsagePage } from '../../pages/UsagePage';
import { RecoveryPage } from '../../pages/RecoveryPage';
import { controlRequest, loadE2EContext } from '../../harness/context';
import { pathsReferToSameEntry } from '../../harness/runtime';

const chat = new ChatPage();
const usage = new UsagePage();
const recovery = new RecoveryPage();
const context = loadE2EContext();

async function tauriInvokeResult(
  command: string,
  args: Record<string, unknown>,
): Promise<{ ok: boolean; value?: unknown; error?: string }> {
  return browser.execute(async (name, payload) => {
    const invoke = (window as any).__TAURI__?.core?.invoke;
    if (!invoke) return { ok: false, error: 'Tauri invoke is unavailable' };
    try {
      return { ok: true, value: await invoke(name, payload) };
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  }, command, args);
}

async function waitForIdentity(expectedRoot: string): Promise<{ ga_root: string; app_dir: string }> {
  let identity = { ga_root: '', app_dir: '' };
  await browser.waitUntil(async () => {
    try {
      identity = await (await fetch(`${context.bridgeBase}/services/identity`)).json() as typeof identity;
      return pathsReferToSameEntry(identity.ga_root, expectedRoot);
    } catch {
      return false;
    }
  }, { timeout: 40_000, interval: 250, timeoutMsg: `Bridge identity did not switch to ${expectedRoot}` });
  return identity;
}

describe('GenericAgent native Tauri smoke', () => {
  it('boots in the isolated sandbox and completes chat plus usage UI', async () => {
    await chat.switchToMainAndWait();
    const identity = await (await fetch(`${context.bridgeBase}/services/identity`)).json() as { ga_root: string };
    assert.ok(pathsReferToSameEntry(identity.ga_root, context.sandboxRoot), 'bridge must run inside the E2E sandbox');
    await chat.waitForBridgeReady();
    await chat.startNewChat();
    await chat.send('[E2E:normal] native smoke');
    await chat.waitForAssistantText('Harness reply', 60_000);
    await usage.open();
    await usage.waitForTotal('107', 30_000);

    await controlRequest('/bridge/kill-external', { method: 'POST', body: '{}' });
    await chat.startNewChat();
    await recovery.waitForOffline();
    await recovery.recoverFromServices();
    await browser.waitUntil(async () => {
      try {
        return (await fetch(`${context.bridgeBase}/services/identity`)).ok;
      } catch {
        return false;
      }
    }, { timeout: 30_000, interval: 250, timeoutMsg: 'Bridge did not restart through the native UI' });
    await chat.startNewChat();
    await chat.waitForBridgeReady();
  });

  it('switches only GA_ROOT for a compatible external core and clears the persisted override', async () => {
    await chat.switchToMainAndWait();
    await chat.waitForBridgeReady();
    const settingsPath = join(context.sandboxRoot, '.home', '.ga_desktop_settings.json');
    const externalParent = await mkdtemp(join(tmpdir(), 'ga-desktop-compatible-core-'));
    const external = join(externalParent, '外部 core with spaces');
    try {
      await cp(context.sandboxRoot, external, {
        recursive: true,
        filter(source) {
          const rel = relative(context.sandboxRoot, source);
          if (!rel) return true;
          const first = rel.split(sep)[0];
          return !new Set(['.home', 'e2e-report', 'temp']).has(first);
        },
      });
      const switched = await tauriInvokeResult('set_ga_source', { dir: external });
      assert.equal(switched.ok, true, switched.error);
      const externalIdentity = await waitForIdentity(external);
      const switchedSettings = JSON.parse(await readFile(settingsPath, 'utf8')) as { ga_source_override?: string };
      assert.ok(pathsReferToSameEntry(switchedSettings.ga_source_override || '', external));
      assert.ok(
        pathsReferToSameEntry(externalIdentity.app_dir, join(context.sandboxRoot, 'frontends')),
        'bridge code must remain package/sandbox-owned',
      );

      const cleared = await tauriInvokeResult('clear_ga_source', {});
      assert.equal(cleared.ok, true, cleared.error);
      const builtinIdentity = await waitForIdentity(context.sandboxRoot);
      assert.ok(pathsReferToSameEntry(builtinIdentity.app_dir, join(context.sandboxRoot, 'frontends')));
      const clearedSettings = JSON.parse(await readFile(settingsPath, 'utf8')) as { ga_source_override?: string };
      assert.equal(Object.prototype.hasOwnProperty.call(clearedSettings, 'ga_source_override'), false);
    } finally {
      await rm(externalParent, { recursive: true, force: true });
    }
  });
});
