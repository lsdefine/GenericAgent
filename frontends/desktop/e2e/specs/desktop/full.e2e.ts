import assert from 'node:assert/strict';
import { ChatPage } from '../../pages/ChatPage';
import { RecoveryPage } from '../../pages/RecoveryPage';
import { controlRequest, loadE2EContext } from '../../harness/context';
import { pathsReferToSameEntry } from '../../harness/runtime';

const chat = new ChatPage();
const recovery = new RecoveryPage();
const context = loadE2EContext();
const describeFull = process.env.GA_E2E_SUITE === 'full' ? describe : describe.skip;

describeFull('GenericAgent native Tauri full recovery', () => {
  it('rejects a foreign bridge port owner and recovers after retry', async () => {
    await chat.switchToMainAndWait();
    await chat.waitForBridgeReady();

    await controlRequest('/port/occupy-bridge', { method: 'POST', body: '{}' });
    await chat.startNewChat();
    await recovery.waitForOffline();
    await recovery.recoverFromServices();
    const blockedIdentity = await (await fetch(`${context.bridgeBase}/services/identity`)).json() as {
      service?: string;
      ga_root?: string;
    };
    assert.equal(blockedIdentity.service, 'foreign-e2e-listener');
    assert.equal(blockedIdentity.ga_root, undefined);

    await controlRequest('/port/release-bridge', { method: 'POST', body: '{}' });
    await recovery.retryFromServices();
    await browser.waitUntil(async () => {
      try {
        const response = await fetch(`${context.bridgeBase}/services/identity`);
        if (!response.ok) return false;
        const identity = await response.json() as { ga_root?: string };
        return Boolean(identity.ga_root)
          && pathsReferToSameEntry(identity.ga_root!, context.sandboxRoot);
      } catch {
        return false;
      }
    }, { timeout: 30_000, interval: 250, timeoutMsg: 'Bridge did not recover after releasing the foreign port owner' });
    await chat.startNewChat();
    await chat.waitForBridgeReady();
  });
});
