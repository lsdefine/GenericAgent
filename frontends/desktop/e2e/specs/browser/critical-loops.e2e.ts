import assert from 'node:assert/strict';
import { ChatPage } from '../../pages/ChatPage';
import { UsagePage } from '../../pages/UsagePage';
import { controlRequest, loadE2EContext } from '../../harness/context';

const chat = new ChatPage();
const usage = new UsagePage();
const context = loadE2EContext();

interface TokenHistory {
  history: Array<{ input: number; output: number; cacheRead: number }>;
  snap: Record<string, { input: number; output: number; cacheRead: number }>;
}

async function history(): Promise<TokenHistory> {
  const response = await fetch(`${context.bridgeBase}/token-history`);
  assert.equal(response.status, 200);
  return await response.json() as TokenHistory;
}

function totals(value: TokenHistory) {
  return Object.values(value.snap).reduce((sum, item) => ({
    input: sum.input + item.input,
    output: sum.output + item.output,
    cacheRead: sum.cacheRead + item.cacheRead,
  }), { input: 0, output: 0, cacheRead: 0 });
}

async function waitForTotals(expected: { input: number; output: number; cacheRead: number }): Promise<void> {
  await browser.waitUntil(async () => {
    const actual = totals(await history());
    return actual.input === expected.input && actual.output === expected.output && actual.cacheRead === expected.cacheRead;
  }, { timeout: 30_000, interval: 250, timeoutMsg: `Token history did not reach ${JSON.stringify(expected)}` });
}

async function armEmptyTurn(): Promise<void> {
  const response = await fetch(`${context.bridgeBase}/__e2e__/next-turn`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-ga-e2e-token': context.controlToken },
    body: JSON.stringify({ mode: 'empty' }),
  });
  assert.equal(response.status, 200);
}

describe('GenericAgent critical desktop loops in browser mode', () => {
  before(async () => {
    await browser.url('/');
    await chat.waitUntilReady();
  });

  it('migrates legacy JSON history exactly once across bridge restarts', async () => {
    assert.deepEqual(totals(await history()), { input: 2, output: 3, cacheRead: 1 });
    await controlRequest('/bridge/restart', { method: 'POST', body: '{}' });
    assert.deepEqual(totals(await history()), { input: 2, output: 3, cacheRead: 1 });
  });

  it('persists exact per-call usage and survives corrupt JSONL plus restart', async () => {
    await chat.startNewChat();
    await chat.send('[E2E:normal] deterministic ledger');
    await chat.waitForAssistantText('Harness reply');
    await waitForTotals({ input: 92, output: 20, cacheRead: 12 });

    await usage.open();
    await usage.waitForTotal('112');
    assert.equal(await usage.cacheRate.getText(), '11.5%');

    await controlRequest('/ledger/corrupt-tail', { method: 'POST', body: '{}' });
    assert.deepEqual(totals(await history()), { input: 92, output: 20, cacheRead: 12 });
    await controlRequest('/bridge/restart', { method: 'POST', body: '{}' });
    assert.deepEqual(totals(await history()), { input: 92, output: 20, cacheRead: 12 });
    await browser.refresh();
    await chat.waitUntilReady();
    await usage.open();
    await usage.waitForTotal('112');
  });

  it('renders Chinese and English empty-turn fallbacks as assistant prose', async () => {
    await chat.startNewChat();
    await armEmptyTurn();
    await chat.send('empty zh');
    await chat.waitForAssistantText('这一轮结束了，但没有产出可见回复');

    await controlRequest('/settings/language', { method: 'POST', body: JSON.stringify({ lang: 'en' }) });
    await browser.refresh();
    await chat.waitUntilReady();
    await chat.startNewChat();
    await armEmptyTurn();
    await chat.send('empty en');
    await chat.waitForAssistantText('This turn ended without a visible response');
  });

  it('keeps the completed first API call after a hard bridge crash during call two', async () => {
    await chat.startNewChat();
    await chat.send('[E2E:two-call-hang] crash recovery');
    await controlRequest('/bridge/crash-after-second-call', { method: 'POST', body: '{}' });
    await waitForTotals({ input: 182, output: 37, cacheRead: 23 });
    await browser.refresh();
    await chat.waitUntilReady();
    await usage.open();
    await usage.waitForTotal('219');
  });
});
