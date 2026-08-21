// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  fetchTokenHistory: vi.fn(),
  fetchConductorTokenStats: vi.fn(),
  fetchLiveTokenStats: vi.fn(),
  emptySnapshot: () => ({
    totalInput: 0,
    totalOutput: 0,
    totalCacheWrite: 0,
    totalCacheRead: 0,
  }),
}));

vi.mock('../services/token-api', () => api);
vi.mock('../services/ws', () => ({ subscribe: vi.fn() }));

function history(input: number) {
  return {
    history: [
      {
        id: 'sess-1',
        title: 'Session',
        input,
        output: 0,
        cacheWrite: 0,
        cacheRead: 0,
        model: '',
        ts: 1,
      },
    ],
    snap: {
      totalInput: input,
      totalOutput: 0,
      totalCacheWrite: 0,
      totalCacheRead: 0,
    },
  };
}

describe('token store ledger polling', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    vi.useFakeTimers();
    api.fetchTokenHistory.mockResolvedValueOnce(history(1_000)).mockResolvedValueOnce(history(1_010));
    api.fetchLiveTokenStats.mockResolvedValue([
      { thread: 'GA-sess-1', input: 10, output: 0, cacheCreate: 0, cacheRead: 0, model: '' },
    ]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('refreshes persisted totals after live counters restart from zero', async () => {
    const { useTokenStore } = await import('../stores/token');
    await useTokenStore.getState().fetchHistory();
    expect(useTokenStore.getState().snapshot.totalInput).toBe(1_000);

    useTokenStore.getState().startPolling();
    await vi.advanceTimersByTimeAsync(15_000);

    expect(api.fetchTokenHistory).toHaveBeenCalledTimes(2);
    expect(useTokenStore.getState().snapshot.totalInput).toBe(1_010);
    useTokenStore.getState().stopPolling();
  });
});
