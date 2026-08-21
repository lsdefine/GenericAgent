import { create } from 'zustand';
import { CONDUCTOR_WS_URL, CONDUCTOR_BASE } from '../services/constants';
import {
  fetchConductorModel,
  saveConductorModel,
  type ConductorModelState,
} from '../services/services-api';
const RECON_BASE_MS = 1200;
const RECON_MAX_MS = 30_000;
const FAIL_MAX = 5;

export type ConductorConnectionStatus = 'connecting' | 'ready' | 'offline' | 'error';
export type WorkerStatus = 'running' | 'reported' | 'paused' | 'failed' | 'terminated';

export interface ConductorMessage {
  id?: string;
  role: 'user' | 'conductor' | 'system';
  msg: string;
  ts?: number;
  read?: boolean;
  files?: { name: string; path: string }[];
  images?: { name: string; path: string; base64?: string }[];
  _local?: boolean;
}

export interface Worker {
  id: string;
  title: string;
  status: WorkerStatus;
  summary: string;
  fullReply: string;
  updatedAt?: number;
}

export interface ConductorRuntimeModel extends ConductorModelState {
  current: string | null;
  running: boolean;
}

interface ConductorState {
  connectionStatus: ConductorConnectionStatus;
  messages: ConductorMessage[];
  workers: Worker[];
  conductorTyping: boolean;
  modelConfig: ConductorModelState | null;
  runtimeModel: ConductorRuntimeModel | null;

  connect: () => void;
  disconnect: () => void;
  sendMessage: (msg: string, files?: ConductorMessage['files'], images?: ConductorMessage['images']) => void;
  killWorker: (id: string) => Promise<void>;
  loadModel: () => Promise<void>;
  selectModel: (llmNo: number) => Promise<void>;
}

function mapStatus(status: string, reply: string): WorkerStatus {
  if (status === 'running') return 'running';
  if (status === 'failed') return 'failed';
  if (status === 'aborted') return 'terminated';
  if (status === 'stopped') return reply.trim() ? 'reported' : 'paused';
  return 'paused';
}

let titleSeq = 0;
const titleSeen = new Map<string, number>();

function normalizeWorker(raw: Record<string, unknown>): Worker {
  const id = String(raw.id ?? '');
  if (!titleSeen.has(id)) titleSeen.set(id, ++titleSeq);

  const status = mapStatus(String(raw.status ?? ''), String(raw.reply ?? ''));
  let title = String(raw.prompt ?? '').replace(/^[\s请帮我麻烦]+/u, '').trim();
  if (!title) {
    title = `Task #${titleSeen.get(id)}`;
  } else {
    title = (title.split(/[\n。！？.!?]/)[0] || '').trim();
    if (title.length > 18) title = title.slice(0, 18) + '…';
  }

  const reply = String(raw.reply ?? '').replace(/\s+/g, ' ').trim();
  const summary = reply
    ? (reply.length > 80 ? reply.slice(0, 80) + '…' : reply)
    : (status === 'running' ? 'Working…' : 'Waiting…');

  return { id, title, status, summary, fullReply: String(raw.reply ?? ''), updatedAt: raw.updated_at as number | undefined };
}

let ws: WebSocket | null = null;
let wsGen = 0;
let connectTimer: ReturnType<typeof setTimeout> | null = null;
let failCount = 0;
let everConnected = false;

export const useConductorStore = create<ConductorState>((set, get) => {
  function scheduleReconnect() {
    if (connectTimer) clearTimeout(connectTimer);
    if (!everConnected && failCount >= FAIL_MAX) {
      set({ connectionStatus: 'offline' });
      return;
    }
    const delay = Math.min(RECON_MAX_MS, RECON_BASE_MS * Math.pow(2, Math.max(0, failCount - 1)));
    set({ connectionStatus: everConnected ? 'connecting' : 'connecting' });
    connectTimer = setTimeout(() => get().connect(), delay);
  }

  function onMessage(data: Record<string, unknown>, gen: number) {
    if (gen !== wsGen) return;

    if (data.type === 'hello') {
      const chat = (data.chat as Record<string, unknown>[] || []).map((raw): ConductorMessage => ({
        id: String(raw.id ?? ''),
        role: (raw.role as ConductorMessage['role']) || 'system',
        msg: String(raw.msg ?? ''),
        ts: raw.ts as number | undefined,
        read: raw.read as boolean | undefined,
        files: (raw.files as ConductorMessage['files']) || [],
        images: (raw.images as ConductorMessage['images']) || [],
      }));
      const workers = ((data.subagents as Record<string, unknown>[]) || []).map(normalizeWorker);
      set({
        messages: chat,
        workers,
        conductorTyping: !!data.running,
        runtimeModel: (data.model as ConductorRuntimeModel | undefined) ?? null,
      });
    } else if (data.type === 'subagents') {
      const workers = ((data.items as Record<string, unknown>[]) || []).map(normalizeWorker);
      set({ workers });
    } else if (data.type === 'chat') {
      const item = data.item as Record<string, unknown>;
      const newMsg: ConductorMessage = {
        id: String(item.id ?? ''),
        role: (item.role as ConductorMessage['role']) || 'system',
        msg: String(item.msg ?? ''),
        ts: item.ts as number | undefined,
        read: item.read as boolean | undefined,
        files: (item.files as ConductorMessage['files']) || [],
        images: (item.images as ConductorMessage['images']) || [],
      };
      set((s) => {
        if (newMsg.id && s.messages.some((m) => m.id === newMsg.id)) return s;
        if (newMsg.role === 'user') {
          const plain = newMsg.msg.replace(/\[(Image|File)\s+#\d+\]\s*/g, '').trim();
          for (let i = s.messages.length - 1; i >= 0; i--) {
            const m = s.messages[i];
            if (m._local && m.role === 'user') {
              const localPlain = m.msg.replace(/\[(Image|File)\s+#\d+\]\s*/g, '').trim();
              if (localPlain === plain || m.msg === newMsg.msg) {
                const updated = [...s.messages];
                updated[i] = { ...updated[i], id: newMsg.id || updated[i].id, ts: newMsg.ts ?? updated[i].ts, _local: false };
                return { messages: updated };
              }
            }
          }
        }
        const conductorTyping = newMsg.role === 'conductor' ? false : s.conductorTyping;
        return { messages: [...s.messages, newMsg], conductorTyping };
      });
    } else if (data.type === 'model') {
      set({ runtimeModel: data.model as ConductorRuntimeModel });
    }
  }

  return {
    connectionStatus: 'offline',
    messages: [],
    workers: [],
    conductorTyping: false,
    modelConfig: null,
    runtimeModel: null,

    connect() {
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
      if (connectTimer) { clearTimeout(connectTimer); connectTimer = null; }
      const gen = ++wsGen;
      set({ connectionStatus: 'connecting' });

      let sock: WebSocket;
      try {
        sock = new WebSocket(CONDUCTOR_WS_URL);
      } catch {
        failCount++;
        scheduleReconnect();
        return;
      }
      ws = sock;

      sock.onopen = () => {
        if (gen !== wsGen) return;
        everConnected = true;
        failCount = 0;
        set({ connectionStatus: 'ready' });
        get().loadModel();
      };

      sock.onclose = () => {
        if (gen !== wsGen) return;
        set({ connectionStatus: everConnected ? 'connecting' : 'offline' });
        if (everConnected) {
          scheduleReconnect();
        } else {
          failCount++;
          scheduleReconnect();
        }
      };

      sock.onerror = () => {};

      sock.onmessage = (ev) => {
        if (gen !== wsGen) return;
        try {
          onMessage(JSON.parse(ev.data), gen);
        } catch {}
      };
    },

    disconnect() {
      wsGen++;
      if (connectTimer) { clearTimeout(connectTimer); connectTimer = null; }
      if (ws) {
        const old = ws;
        ws = null;
        old.onopen = old.onclose = old.onerror = old.onmessage = null;
        try { old.close(); } catch {}
      }
      failCount = 0;
      everConnected = false;
      set({ connectionStatus: 'offline', messages: [], workers: [], conductorTyping: false, runtimeModel: null });
    },

    sendMessage(msg, files, images) {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const payload: Record<string, unknown> = { msg };
      if (files && files.length > 0) payload.files = files;
      if (images && images.length > 0) payload.images = images;
      ws.send(JSON.stringify(payload));

      const localMsg: ConductorMessage = {
        id: `local-${Date.now()}`,
        role: 'user',
        msg,
        ts: Date.now() / 1000,
        files,
        images,
        _local: true,
      };
      set((s) => ({ messages: [...s.messages, localMsg], conductorTyping: true }));
    },

    async killWorker(id) {
      try {
        await fetch(`${CONDUCTOR_BASE}/subagent/${id}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'kill' }),
        });
      } catch {}
    },

    async loadModel() {
      try {
        set({ modelConfig: await fetchConductorModel() });
      } catch {}
    },

    async selectModel(llmNo) {
      const previous = get().modelConfig;
      set({ modelConfig: { configured: llmNo, effective: llmNo, fallbackReason: null } });
      try {
        set({ modelConfig: await saveConductorModel(llmNo) });
      } catch {
        set({ modelConfig: previous });
      }
    },
  };
});

useConductorStore.getState().connect();
