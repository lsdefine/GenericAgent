import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';

export type FakeScenario = 'normal' | 'http500' | 'disconnect' | 'two-call-hang';

export interface FakeTranscriptEntry {
  path: string;
  scenario: FakeScenario;
  authorization: '[redacted]' | '';
  model: string;
  call: number;
}

export class FakeOpenAI {
  private server: Server | null = null;
  private entries: FakeTranscriptEntry[] = [];
  private scenarioCalls = new Map<FakeScenario, number>();
  private heldResponses = new Set<ServerResponse>();

  async start(): Promise<string> {
    if (this.server) throw new Error('FakeOpenAI already started');
    this.server = createServer((request, response) => void this.handle(request, response));
    await new Promise<void>((resolve, reject) => {
      this.server!.once('error', reject);
      this.server!.listen(0, '127.0.0.1', resolve);
    });
    const { port } = this.server.address() as AddressInfo;
    return `http://127.0.0.1:${port}`;
  }

  async stop(): Promise<void> {
    for (const response of this.heldResponses) response.destroy();
    this.heldResponses.clear();
    const server = this.server;
    this.server = null;
    if (!server) return;
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }

  transcript(): FakeTranscriptEntry[] {
    return this.entries.map((entry) => ({ ...entry }));
  }

  releaseHeld(): void {
    for (const response of this.heldResponses) this.writeTextResponse(response, 'Harness resumed');
    this.heldResponses.clear();
  }

  async waitForScenarioRequests(scenario: FakeScenario, count: number, timeoutMs = 10_000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (this.entries.filter((entry) => entry.scenario === scenario).length < count) {
      if (Date.now() >= deadline) {
        throw new Error(`Timed out waiting for ${count} ${scenario} fake LLM requests`);
      }
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
  }

  private async handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const chunks: Buffer[] = [];
    for await (const chunk of request) chunks.push(Buffer.from(chunk));
    let body: Record<string, unknown> = {};
    try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { /* invalid body handled as normal */ }
    const scenario = this.scenario(body);
    const call = (this.scenarioCalls.get(scenario) ?? 0) + 1;
    this.scenarioCalls.set(scenario, call);
    this.entries.push({
      path: request.url || '',
      scenario,
      authorization: request.headers.authorization ? '[redacted]' : '',
      model: typeof body.model === 'string' ? body.model : '',
      call,
    });

    if (scenario === 'http500') {
      response.writeHead(500, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ error: { message: 'deterministic harness failure' } }));
      return;
    }
    if (scenario === 'disconnect') {
      request.socket.destroy();
      return;
    }
    if (scenario === 'two-call-hang' && call > 1) {
      this.heldResponses.add(response);
      response.on('close', () => this.heldResponses.delete(response));
      return;
    }
    if (scenario === 'two-call-hang') {
      this.writeToolResponse(response);
      return;
    }
    this.writeTextResponse(response, 'Harness reply');
  }

  private scenario(body: Record<string, unknown>): FakeScenario {
    const raw = JSON.stringify(body);
    if (raw.includes('[E2E:http500]')) return 'http500';
    if (raw.includes('[E2E:disconnect]')) return 'disconnect';
    if (raw.includes('[E2E:two-call-hang]')) return 'two-call-hang';
    return 'normal';
  }

  private headers(response: ServerResponse): void {
    response.writeHead(200, {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache',
      connection: 'close',
    });
  }

  private writeTextResponse(response: ServerResponse, text: string): void {
    this.headers(response);
    response.write(`data: ${JSON.stringify({ choices: [{ delta: { content: text } }] })}\n\n`);
    response.write(`data: ${JSON.stringify({ choices: [], usage: {
      prompt_tokens: 101,
      completion_tokens: 17,
      prompt_tokens_details: { cached_tokens: 11 },
    } })}\n\n`);
    response.end('data: [DONE]\n\n');
  }

  private writeToolResponse(response: ServerResponse): void {
    this.headers(response);
    response.write(`data: ${JSON.stringify({ choices: [{ delta: { tool_calls: [{
      index: 0,
      id: 'call_harness_1',
      function: { name: 'update_working_checkpoint', arguments: '{"key_info":"e2e"}' },
    }] } }] })}\n\n`);
    response.write(`data: ${JSON.stringify({ choices: [], usage: {
      prompt_tokens: 101,
      completion_tokens: 17,
      prompt_tokens_details: { cached_tokens: 11 },
    } })}\n\n`);
    response.end('data: [DONE]\n\n');
  }
}
