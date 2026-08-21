import { create } from 'zustand';
import { subscribe } from '../services/ws';
import {
  fetchTokenHistory as apiFetchHistory,
  fetchConductorTokenStats,
  fetchLiveTokenStats,
  emptySnapshot,
  type TokenRecord,
  type HistoryEntry,
  type TokenSnapshot,
} from '../services/token-api';

export type { TokenRecord, HistoryEntry, TokenSnapshot };
export { emptySnapshot };

const POLL_INTERVAL_MS = 15_000;

interface TokenState {
  history: HistoryEntry[];
  snapshot: TokenSnapshot;
  loading: boolean;
  error: string | null;

  conductorHistory: HistoryEntry[];
  conductorSnapshot: TokenSnapshot;
  conductorLoading: boolean;
  conductorOffline: boolean;

  dateRange: [Date | null, Date | null];

  fetchHistory: () => Promise<void>;
  fetchConductorHistory: () => Promise<void>;
  fetchLiveStats: () => Promise<void>;
  setDateRange: (range: [Date | null, Date | null]) => void;
  resetFilters: () => void;
  startPolling: () => void;
  stopPolling: () => void;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;

export const useTokenStore = create<TokenState>((set, get) => {
  subscribe('token.snapshot', (data: unknown) => {
    const evt = data as { snap?: TokenSnapshot; history?: HistoryEntry[] };
    if (evt.snap) set({ snapshot: evt.snap });
    if (evt.history) set({ history: evt.history, loading: false });
  });

  subscribe('token.changed', (data: unknown) => {
    const evt = data as { entry?: HistoryEntry };
    if (evt.entry) {
      set((s) => ({
        history: [...s.history, evt.entry!],
        snapshot: {
          totalInput: s.snapshot.totalInput + evt.entry!.input,
          totalOutput: s.snapshot.totalOutput + evt.entry!.output,
          totalCacheWrite: s.snapshot.totalCacheWrite + evt.entry!.cacheWrite,
          totalCacheRead: s.snapshot.totalCacheRead + evt.entry!.cacheRead,
        },
      }));
    }
  });

  return {
    history: [],
    snapshot: emptySnapshot(),
    loading: true,
    error: null,

    conductorHistory: [],
    conductorSnapshot: emptySnapshot(),
    conductorLoading: false,
    conductorOffline: false,

    dateRange: [null, null],

    async fetchHistory() {
      set({ loading: true, error: null });
      try {
        const data = await apiFetchHistory();
        set({
          history: data.history,
          snapshot: data.snap,
          loading: false,
        });
        if (data.conductorSnapshot) {
          set({ conductorSnapshot: data.conductorSnapshot });
        }
      } catch (e) {
        set({ loading: false, error: (e as Error).message });
      }
    },

    async fetchConductorHistory() {
      set({ conductorLoading: true });
      try {
        const records = await fetchConductorTokenStats();
        const entries: HistoryEntry[] = records.map((r, i) => ({
          id: `cond-${i}`,
          title: r.thread || `Conductor ${i + 1}`,
          input: r.input,
          output: r.output,
          cacheWrite: r.cacheCreate,
          cacheRead: r.cacheRead,
          model: r.model,
          ts: Date.now(),
        }));

        const snap: TokenSnapshot = entries.reduce(
          (acc, e) => ({
            totalInput: acc.totalInput + e.input,
            totalOutput: acc.totalOutput + e.output,
            totalCacheWrite: acc.totalCacheWrite + e.cacheWrite,
            totalCacheRead: acc.totalCacheRead + e.cacheRead,
          }),
          emptySnapshot(),
        );

        set({
          conductorHistory: entries,
          conductorSnapshot: snap,
          conductorLoading: false,
          conductorOffline: false,
        });
      } catch {
        set({ conductorLoading: false, conductorOffline: true });
      }
    },

    async fetchLiveStats() {
      try {
        const records = await fetchLiveTokenStats();
        const snap: TokenSnapshot = records.reduce(
          (acc, r) => ({
            totalInput: acc.totalInput + r.input,
            totalOutput: acc.totalOutput + r.output,
            totalCacheWrite: acc.totalCacheWrite + r.cacheCreate,
            totalCacheRead: acc.totalCacheRead + r.cacheRead,
          }),
          emptySnapshot(),
        );
        set({ snapshot: snap });
      } catch {
        // Live stats are best-effort
      }
    },

    startPolling() {
      if (pollTimer) return;
      pollTimer = setInterval(() => {
        get().fetchHistory();
      }, POLL_INTERVAL_MS);
    },

    stopPolling() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    },

    setDateRange(range: [Date | null, Date | null]) {
      set({ dateRange: range });
    },

    resetFilters() {
      set({ dateRange: [null, null] });
    },
  };
});
