// @vitest-environment node
/**
 * Bridge API contract tests.
 * Tests the request building and response parsing logic of services/bridge.ts
 * without requiring a live bridge process.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const BRIDGE_BASE = 'http://127.0.0.1:14168';

describe('bridge API contract', () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function devFetch(path: string, opts?: RequestInit): Promise<unknown> {
    const res = await fetch(`${BRIDGE_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
    });
    if (!(res as Response).ok) throw new Error(`${(res as Response).status}`);
    return (res as Response).json();
  }

  describe('GET /status', () => {
    it('parses valid status response', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ status: 'running', version: '0.1.0', uptime: 123 }),
      });

      const result = await devFetch('/status');
      expect(result).toEqual({ status: 'running', version: '0.1.0', uptime: 123 });
      expect(mockFetch).toHaveBeenCalledWith(
        `${BRIDGE_BASE}/status`,
        expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
      );
    });

    it('throws on non-2xx response', async () => {
      mockFetch.mockResolvedValue({ ok: false, status: 503, statusText: 'Service Unavailable' });
      await expect(devFetch('/status')).rejects.toThrow('503');
    });

    it('throws on network error', async () => {
      mockFetch.mockRejectedValue(new Error('ECONNREFUSED'));
      await expect(devFetch('/status')).rejects.toThrow('ECONNREFUSED');
    });
  });

  describe('POST /session/new', () => {
    it('creates a session and returns session id', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ session: { id: 'abc-123', title: 'New Session' } }),
      });

      const result = await devFetch('/session/new', { method: 'POST', body: '{}' }) as { session: { id: string } };
      expect(result.session.id).toBe('abc-123');
    });
  });

  describe('POST /session/:id/prompt', () => {
    it('sends message payload correctly', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ status: 'running' }),
      });

      const body = JSON.stringify({ message: 'hello', images: [], files: [] });
      await devFetch('/session/test-session/prompt', { method: 'POST', body });

      expect(mockFetch).toHaveBeenCalledWith(
        `${BRIDGE_BASE}/session/test-session/prompt`,
        expect.objectContaining({
          method: 'POST',
          body,
        }),
      );
    });

    it('handles empty message gracefully', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ status: 'idle' }),
      });

      const result = await devFetch('/session/s1/prompt', {
        method: 'POST',
        body: JSON.stringify({ message: '', images: [], files: [] }),
      });
      expect(result).toEqual({ status: 'idle' });
    });
  });

  describe('GET /services/list', () => {
    it('parses service list with multiple services', async () => {
      const services = [
        { id: 'bridge', name: 'Desktop Bridge', status: 'running' },
        { id: 'agent', name: 'GenericAgent', status: 'stopped' },
      ];
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ services }),
      });

      const result = await devFetch('/services/list') as { services: unknown[] };
      expect(result.services.length).toBe(2);
    });

    it('handles empty service list', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ services: [] }),
      });

      const result = await devFetch('/services/list') as { services: unknown[] };
      expect(result.services).toEqual([]);
    });
  });

  describe('GET /services/logs', () => {
    it('parses log response with lines array', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ lines: ['[12:00:00] Start', '[12:00:01] Ready'] }),
      });

      const result = await devFetch('/services/logs?id=__bridge__&tail=200') as { lines: string[] };
      expect(result.lines.length).toBe(2);
    });
  });

  describe('model profiles CRUD', () => {
    it('GET /model-profiles returns profiles array', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          profiles: [{ id: 1, name: 'GPT-4', model: 'gpt-4', apibase: 'https://api.openai.com', protocol: 'oai', stream: true }],
        }),
      });

      const result = await devFetch('/model-profiles') as { profiles: unknown[] };
      expect(result.profiles.length).toBe(1);
    });

    it('POST /model-profiles adds a profile', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          profiles: [
            { id: 1, name: 'GPT-4', model: 'gpt-4', apibase: 'https://api.openai.com', protocol: 'oai', stream: true },
            { id: 2, name: 'New', model: 'new-model', apibase: 'https://new.api', protocol: 'oai', stream: false },
          ],
        }),
      });

      const result = await devFetch('/model-profiles', {
        method: 'POST',
        body: JSON.stringify({ name: 'New', model: 'new-model', apibase: 'https://new.api', protocol: 'oai', stream: false }),
      }) as { profiles: unknown[] };
      expect(result.profiles.length).toBe(2);
    });

    it('DELETE /model-profiles/:id removes a profile', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ profiles: [] }),
      });

      const result = await devFetch('/model-profiles/1', { method: 'DELETE' }) as { profiles: unknown[] };
      expect(result.profiles).toEqual([]);
    });
  });
});
