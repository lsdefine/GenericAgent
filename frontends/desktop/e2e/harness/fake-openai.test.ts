// @vitest-environment node
import { afterEach, describe, expect, it } from 'vitest';
import { FakeOpenAI } from './fake-openai';

const servers: FakeOpenAI[] = [];

afterEach(async () => {
  await Promise.all(servers.splice(0).map((server) => server.stop()));
});

describe('FakeOpenAI', () => {
  it('streams deterministic text and exact usage while redacting authorization', async () => {
    const server = new FakeOpenAI();
    servers.push(server);
    const baseUrl = await server.start();

    const response = await fetch(`${baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: { authorization: 'Bearer must-not-leak', 'content-type': 'application/json' },
      body: JSON.stringify({ model: 'e2e-model', stream: true, messages: [{ role: 'user', content: 'hello' }] }),
    });
    const body = await response.text();

    expect(response.status).toBe(200);
    expect(body).toContain('Harness reply');
    expect(body).toContain('"prompt_tokens":101');
    expect(body).toContain('"completion_tokens":17');
    expect(server.transcript()).toEqual([
      expect.objectContaining({ path: '/v1/chat/completions', scenario: 'normal', authorization: '[redacted]' }),
    ]);
  });

  it('can fail or disconnect deterministically from prompt markers', async () => {
    const server = new FakeOpenAI();
    servers.push(server);
    const baseUrl = await server.start();

    const failed = await fetch(`${baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: '[E2E:http500]' }] }),
    });
    expect(failed.status).toBe(500);

    await expect(fetch(`${baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: '[E2E:disconnect]' }] }),
    })).rejects.toThrow();
  });

  it('waits for calls from the requested scenario instead of all earlier traffic', async () => {
    const server = new FakeOpenAI();
    servers.push(server);
    const baseUrl = await server.start();

    await fetch(`${baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: 'ordinary request' }] }),
    });
    await expect(server.waitForScenarioRequests('two-call-hang', 1, 25)).rejects.toThrow(/two-call-hang/);

    await fetch(`${baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: '[E2E:two-call-hang]' }] }),
    });
    await expect(server.waitForScenarioRequests('two-call-hang', 1, 25)).resolves.toBeUndefined();
  });
});
