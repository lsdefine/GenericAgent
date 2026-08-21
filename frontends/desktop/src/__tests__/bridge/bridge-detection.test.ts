// @vitest-environment node
/**
 * Bridge detection and health-check logic tests.
 * Tests the port probe, timeout, and retry behavior that determines
 * whether the bridge process is available.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const BRIDGE_BASE = 'http://127.0.0.1:14168';
const PROBE_TIMEOUT_MS = 3000;
const MAX_RETRIES = 5;
const RETRY_INTERVAL_MS = 1000;

interface ProbeResult {
  reachable: boolean;
  latencyMs?: number;
  error?: string;
}

async function probeBridge(fetchFn: typeof fetch): Promise<ProbeResult> {
  const start = performance.now();
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
    const res = await fetchFn(`${BRIDGE_BASE}/status`, { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) return { reachable: false, error: `HTTP ${res.status}` };
    return { reachable: true, latencyMs: performance.now() - start };
  } catch (e) {
    return { reachable: false, error: (e as Error).message };
  }
}

async function waitForBridge(fetchFn: typeof fetch, maxRetries = MAX_RETRIES): Promise<{ connected: boolean; attempts: number }> {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    const result = await probeBridge(fetchFn);
    if (result.reachable) return { connected: true, attempts: attempt };
    if (attempt < maxRetries) {
      await new Promise((r) => setTimeout(r, RETRY_INTERVAL_MS));
    }
  }
  return { connected: false, attempts: maxRetries };
}

describe('bridge detection', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('probeBridge', () => {
    it('returns reachable=true with latency on success', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
      const result = await probeBridge(mockFetch as unknown as typeof fetch);
      expect(result.reachable).toBe(true);
      expect(result.latencyMs).toBeGreaterThanOrEqual(0);
    });

    it('returns reachable=false on HTTP error', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ ok: false, status: 503 });
      const result = await probeBridge(mockFetch as unknown as typeof fetch);
      expect(result.reachable).toBe(false);
      expect(result.error).toBe('HTTP 503');
    });

    it('returns reachable=false on network error', async () => {
      const mockFetch = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'));
      const result = await probeBridge(mockFetch as unknown as typeof fetch);
      expect(result.reachable).toBe(false);
      expect(result.error).toBe('ECONNREFUSED');
    });

    it('returns reachable=false on abort (timeout)', async () => {
      const mockFetch = vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError'));
      const result = await probeBridge(mockFetch as unknown as typeof fetch);
      expect(result.reachable).toBe(false);
      expect(result.error).toContain('Aborted');
    });
  });

  describe('waitForBridge retry logic', () => {
    it('succeeds on first attempt', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
      const promise = waitForBridge(mockFetch as unknown as typeof fetch);
      const result = await promise;
      expect(result).toEqual({ connected: true, attempts: 1 });
    });

    it('retries and succeeds on third attempt', async () => {
      let callCount = 0;
      const mockFetch = vi.fn().mockImplementation(() => {
        callCount++;
        if (callCount < 3) return Promise.reject(new Error('ECONNREFUSED'));
        return Promise.resolve({ ok: true, status: 200 });
      });

      const promise = waitForBridge(mockFetch as unknown as typeof fetch);
      await vi.advanceTimersByTimeAsync(RETRY_INTERVAL_MS);
      await vi.advanceTimersByTimeAsync(RETRY_INTERVAL_MS);
      const result = await promise;
      expect(result).toEqual({ connected: true, attempts: 3 });
    });

    it('gives up after MAX_RETRIES', async () => {
      const mockFetch = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'));
      const promise = waitForBridge(mockFetch as unknown as typeof fetch, 3);
      await vi.advanceTimersByTimeAsync(RETRY_INTERVAL_MS * 3);
      const result = await promise;
      expect(result).toEqual({ connected: false, attempts: 3 });
    });

    it('does not retry after success', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
      await waitForBridge(mockFetch as unknown as typeof fetch, 5);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });

  describe('URL construction', () => {
    it('probe targets /status endpoint', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
      await probeBridge(mockFetch as unknown as typeof fetch);
      expect(mockFetch).toHaveBeenCalledWith(
        'http://127.0.0.1:14168/status',
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });
  });
});
