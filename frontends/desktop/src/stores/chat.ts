import { create } from 'zustand';
import { createSession, sendPrompt, pollMessages, cancelGeneration, listSessions, deleteSession as apiDeleteSession, renameSession as apiRenameSession, pinSession as apiPinSession, setSessionModel as apiSetSessionModel, type Message, type SessionInfo } from '../services/chat';
import { subscribe, onBridgeStatusChange } from '../services/ws';
import { useSettingsStore } from './settings';

const PARTIAL_MSG_ID = '__partial__';
const POLL_INTERVAL_MS = 1000;

export interface SendOptions {
  files?: { name: string; path: string; size?: number }[];
  images?: { name: string; path: string; base64?: string }[];
}

interface QueuedMessage {
  text: string;
  opts?: SendOptions;
}

interface ChatState {
  activeSessionId: string | null;
  messages: Message[];
  status: 'idle' | 'running';
  sessions: SessionInfo[];
  runningSessions: Set<string>;
  turnStartedAt: number | null;
  pendingQueue: QueuedMessage[];
  sessionModelNo: number | null;

  newSession: () => Promise<void>;
  sendMessage: (text: string, opts?: SendOptions) => Promise<void>;
  cancel: () => Promise<void>;
  cancelQueued: (index: number) => void;
  setActiveSession: (id: string | null) => void;
  loadSessions: () => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  pinSession: (id: string, pinned: boolean) => Promise<void>;
  selectSessionModel: (llmNo: number) => Promise<void>;
}

// rAF throttle state for partial updates (WS path)
let pendingPartial: Message | null = null;
let rafId: number | null = null;

// Fallback polling state
let pollTimer: ReturnType<typeof setInterval> | null = null;

// Per-session turn start timestamps — persists across session switches
const turnStartMap = new Map<string, number>();

export const useChatStore = create<ChatState>((set, get) => {
  function mergeMessages(current: Message[], incoming: Message[], partial?: Message): Message[] {
    const withoutPartial = current.filter((m) => m.id !== PARTIAL_MSG_ID);
    const localMsgs = withoutPartial.filter((m) => String(m.id).startsWith('local-'));
    let merged = withoutPartial.filter((m) => !String(m.id).startsWith('local-'));

    for (const inc of incoming) {
      if (merged.some((m) => m.id === inc.id)) continue;
      const localIdx = localMsgs.findIndex((l) => l.role === inc.role && l.content === inc.content);
      if (localIdx >= 0) {
        localMsgs.splice(localIdx, 1);
      }
      merged.push(inc);
    }
    merged = [...merged, ...localMsgs];
    merged.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));

    if (partial) {
      merged.push({ ...partial, id: PARTIAL_MSG_ID, status: 'in_progress' });
    }
    return merged;
  }

  function inferTurnStart(messages: Message[]): number {
    // Find the last user message's createdAt as the best approximation of turn start
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user' && messages[i].createdAt) {
        return messages[i].createdAt!;
      }
    }
    return Date.now();
  }

  function setTurnStart(sessionId: string, ts: number) {
    turnStartMap.set(sessionId, ts);
    const { activeSessionId } = get();
    if (sessionId === activeSessionId) {
      set({ turnStartedAt: ts });
    }
  }

  function clearTurnStart(sessionId: string) {
    turnStartMap.delete(sessionId);
    const { activeSessionId } = get();
    if (sessionId === activeSessionId) {
      set({ turnStartedAt: null });
    }
  }

  function flushPartial() {
    rafId = null;
    if (!pendingPartial) return;
    const partial = pendingPartial;
    pendingPartial = null;
    const { messages } = get();
    const withoutPartial = messages.filter((m) => m.id !== PARTIAL_MSG_ID);
    set({ messages: [...withoutPartial, partial] });
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(() => {
      const { activeSessionId, status } = get();
      if (!activeSessionId || status !== 'running') { stopPolling(); return; }
      pollMessages(activeSessionId).then((result) => {
        set((s) => ({
          messages: mergeMessages(s.messages, result.messages, result.partial),
          status: result.status,
          turnStartedAt: result.status === 'running' ? s.turnStartedAt : null,
        }));
        if (result.model) {
          useSettingsStore.getState().setLiveModel(result.model);
          if (result.model.llmNo != null && result.status !== 'running') {
            set({ sessionModelNo: result.model.llmNo });
          }
        }
        if (result.status !== 'running') {
          clearTurnStart(activeSessionId);
          stopPolling();
          const { pendingQueue, status: cur } = get();
          if (cur === 'idle' && pendingQueue.length > 0) {
            const [next, ...rest] = pendingQueue;
            set({ pendingQueue: rest });
            get().sendMessage(next.text, next.opts);
          }
        }
      }).catch(() => {});
    }, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    if (pollTimer !== null) { clearInterval(pollTimer); pollTimer = null; }
  }

  // Real-time partial updates via WebSocket — rAF throttled (faster path)
  subscribe('partial-update', (data: unknown) => {
    const evt = data as { sessionId?: string; content?: string; turn_segs?: string[]; curr_turn?: number };
    const { activeSessionId } = get();
    if (!evt.sessionId || evt.sessionId !== activeSessionId) return;

    pendingPartial = {
      id: PARTIAL_MSG_ID,
      role: 'assistant',
      content: evt.content || '',
      status: 'in_progress',
      turn_segs: evt.turn_segs,
    };

    if (rafId === null) {
      rafId = requestAnimationFrame(flushPartial);
    }
  });

  // On session-state change
  subscribe('session-state', (data: unknown) => {
    const evt = data as { sessionId?: string; status?: string };
    if (evt.sessionId && evt.status) {
      set((s) => {
        const next = new Set(s.runningSessions);
        if (evt.status === 'running') {
          next.add(evt.sessionId!);
        } else {
          next.delete(evt.sessionId!);
        }
        return { runningSessions: next };
      });
    }
    const { activeSessionId } = get();
    if (evt.sessionId && evt.sessionId === activeSessionId) {
      if (evt.status === 'running') {
        // Only record start time if not already tracked
        if (!turnStartMap.has(evt.sessionId)) {
          setTurnStart(evt.sessionId, Date.now());
        } else {
          set({ turnStartedAt: turnStartMap.get(evt.sessionId)! });
        }
        set({ status: 'running' });
        startPolling();
      } else if (evt.status === 'idle' || evt.status === 'error' || evt.status === 'cancelled') {
        stopPolling();
        if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
        pendingPartial = null;

        clearTurnStart(evt.sessionId);
        set({ status: 'idle' });
        pollMessages(activeSessionId).then((result) => {
          set((s) => ({
            messages: mergeMessages(
              s.messages.filter((m) => m.id !== PARTIAL_MSG_ID),
              result.messages,
              undefined,
            ),
          }));
          if (result.model) {
            useSettingsStore.getState().setLiveModel(result.model);
            if (result.model.llmNo != null) {
              set({ sessionModelNo: result.model.llmNo });
            }
          }
          const { pendingQueue, status: curStatus } = get();
          if (curStatus === 'idle' && pendingQueue.length > 0) {
            const [next, ...rest] = pendingQueue;
            set({ pendingQueue: rest });
            get().sendMessage(next.text, next.opts);
          }
        }).catch(() => {});
      }
    }
    // Handle non-active session turn end — clean up map
    if (evt.sessionId && evt.sessionId !== activeSessionId) {
      if (evt.status === 'idle' || evt.status === 'error' || evt.status === 'cancelled') {
        turnStartMap.delete(evt.sessionId);
      } else if (evt.status === 'running' && !turnStartMap.has(evt.sessionId)) {
        turnStartMap.set(evt.sessionId, Date.now());
      }
    }
    if (evt.status === 'idle' || evt.status === 'error') {
      listSessions().then((sessions) => set({ sessions })).catch(() => {});
    }
  });

  listSessions().then((sessions) => set({ sessions })).catch(() => {});

  return {
    activeSessionId: null,
    messages: [],
    status: 'idle',
    sessions: [],
    runningSessions: new Set(),
    turnStartedAt: null,
    pendingQueue: [],
    sessionModelNo: null,

    async newSession() {
      set({ activeSessionId: null, messages: [], status: 'idle', turnStartedAt: null, pendingQueue: [], sessionModelNo: null });
    },

    async sendMessage(text: string, opts?: SendOptions) {
      let { activeSessionId, status } = get();
      if (!activeSessionId) {
        activeSessionId = await createSession();
        set({ activeSessionId });
        get().loadSessions();
        const pendingModel = get().sessionModelNo;
        if (pendingModel != null) {
          apiSetSessionModel(activeSessionId, pendingModel).catch(() => {});
        }
      }
      if (status === 'running') {
        set((s) => ({ pendingQueue: [...s.pendingQueue, { text, opts }] }));
        return;
      }
      const now = Date.now();
      const localImages = opts?.images?.map((f) => ({ name: f.name, path: f.base64 || f.path || f.name }));
      const localFiles = opts?.files;
      const userMsg: Message = { id: `local-${now}`, role: 'user', content: text, status: 'completed', createdAt: now, images: localImages, files: localFiles };
      set((s) => ({ messages: [...s.messages, userMsg], status: 'running' }));
      setTurnStart(activeSessionId, now);
      startPolling();
      await sendPrompt(activeSessionId, text, opts?.files, opts?.images);
    },

    cancelQueued(index: number) {
      set((s) => ({ pendingQueue: s.pendingQueue.filter((_, i) => i !== index) }));
    },

    async cancel() {
      const { activeSessionId } = get();
      if (!activeSessionId) return;
      await cancelGeneration(activeSessionId);
    },

    setActiveSession(id: string | null) {
      stopPolling();
      const restoredTs = id ? turnStartMap.get(id) ?? null : null;
      set({ activeSessionId: id, messages: [], status: 'idle', turnStartedAt: restoredTs, pendingQueue: [], sessionModelNo: null });
      if (id) {
        pollMessages(id).then((result) => {
          const merged = mergeMessages([], result.messages, result.partial);
          set({ messages: merged, status: result.status });
          if (result.model) {
            useSettingsStore.getState().setLiveModel(result.model);
            if (result.model.llmNo != null) {
              set({ sessionModelNo: result.model.llmNo });
            }
          }
          if (result.status === 'running') {
            if (!turnStartMap.has(id)) {
              const inferred = inferTurnStart(result.messages);
              setTurnStart(id, inferred);
            } else {
              set({ turnStartedAt: turnStartMap.get(id)! });
            }
            startPolling();
          } else {
            turnStartMap.delete(id);
            set({ turnStartedAt: null });
          }
        }).catch(() => {});
      }
    },

    async loadSessions() {
      try {
        const sessions = await listSessions();
        set({ sessions });
      } catch {}
    },

    async deleteSession(id: string) {
      const { activeSessionId } = get();
      if (activeSessionId === id) {
        set({ activeSessionId: null, messages: [], status: 'idle', turnStartedAt: null });
      }
      turnStartMap.delete(id);
      set((s) => ({ sessions: s.sessions.filter((ss) => ss.id !== id) }));
      try { await apiDeleteSession(id); } catch {}
    },

    async renameSession(id: string, title: string) {
      set((s) => ({
        sessions: s.sessions.map((ss) =>
          ss.id === id ? { ...ss, title, untitled: false } : ss,
        ),
      }));
      try { await apiRenameSession(id, title); } catch {}
    },

    async pinSession(id: string, pinned: boolean) {
      set((s) => ({
        sessions: s.sessions.map((ss) =>
          ss.id === id ? { ...ss, pinned } : ss,
        ),
      }));
      try { await apiPinSession(id, pinned); } catch {}
    },

    async selectSessionModel(llmNo: number) {
      const { activeSessionId } = get();
      const prev = get().sessionModelNo;
      set({ sessionModelNo: llmNo });
      if (!activeSessionId) return;
      try {
        const res = await apiSetSessionModel(activeSessionId, llmNo);
        if (res.model) {
          useSettingsStore.getState().setLiveModel(res.model);
          if (res.model.llmNo != null) set({ sessionModelNo: res.model.llmNo });
        }
      } catch {
        set({ sessionModelNo: prev });
      }
    },
  };
});

// Reload session list whenever the bridge (re)connects.
onBridgeStatusChange((status) => {
  if (status === 'ready') {
    useChatStore.getState().loadSessions();
  }
});
