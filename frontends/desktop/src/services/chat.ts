import { BRIDGE_BASE } from './constants';

export type MessageStatus = 'completed' | 'in_progress' | 'failed';

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'error';
  content: string;
  status: MessageStatus;
  createdAt?: number;
  ts?: number;
  turn_segs?: string[];
  images?: { name: string; path: string }[];
  files?: { name: string; path: string; size?: number }[];
}

export interface SessionInfo {
  id: string;
  title: string;
  untitled: boolean;
  pinned?: boolean;
  updatedAt?: number | string;
  createdAt?: number | string;
}

export interface PollResult {
  messages: Message[];
  partial?: Message;
  status: 'running' | 'idle';
  plan?: unknown;
  model?: { isMixin: boolean; current: string; llmNo?: number; runningLlmNo?: number | null; runningModel?: string | null };
}

function useMock(): boolean {
  return import.meta.env.VITE_MOCK === 'true';
}

// --- Mock state for dev mode ---
let mockMessages: Map<string, Message[]> = new Map();
let mockSessionCounter = 0;
const mockRunning = new Set<string>();

function mockDelay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// --- API functions ---

function normalizeMessage(msg: Record<string, unknown>, status: MessageStatus = 'completed'): Message {
  const m: Message = {
    id: String(msg.id),
    role: msg.role as Message['role'],
    content: (msg.content as string) || '',
    status: (msg.status as MessageStatus) ?? status,
    createdAt: (msg.createdAt as number) ?? (msg.ts as number),
  };
  if (Array.isArray(msg.turn_segs)) {
    m.turn_segs = msg.turn_segs as string[];
  }
  if (Array.isArray(msg.images) && msg.images.length > 0) {
    m.images = msg.images as { name: string; path: string }[];
  }
  if (Array.isArray(msg.files) && msg.files.length > 0) {
    m.files = msg.files as { name: string; path: string; size?: number }[];
  }
  return m;
}


export async function createSession(): Promise<string> {
  if (useMock()) {
    const id = `mock-session-${++mockSessionCounter}`;
    mockMessages.set(id, []);
    return id;
  }
  const res = await fetch(`${BRIDGE_BASE}/session/new`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cwd: '', mcp_servers: [] }),
  });
  const data = await res.json();
  return data.sessionId;
}

async function uploadImage(sessionId: string, name: string, dataUrl: string): Promise<string> {
  const res = await fetch(`${BRIDGE_BASE}/upload`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, dataUrl, sid: sessionId }),
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || 'upload failed');
  return data.path;
}

export async function uploadFile(name: string, dataUrl: string): Promise<string> {
  const res = await fetch(`${BRIDGE_BASE}/upload`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, dataUrl, sid: '_files' }),
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || 'upload failed');
  return data.path;
}

export async function sendPrompt(
  sessionId: string,
  prompt: string,
  files?: { name: string; path: string; size?: number }[],
  images?: { name: string; path: string; base64?: string }[],
): Promise<string> {
  if (useMock()) {
    const now = Date.now();
    const userMsg: Message = { id: `msg-${now}`, role: 'user', content: prompt, status: 'completed', createdAt: now };
    const msgs = mockMessages.get(sessionId) || [];
    msgs.push(userMsg);
    mockMessages.set(sessionId, msgs);
    mockRunning.add(sessionId);

    setTimeout(() => {
      const ts = Date.now();
      const reply: Message = {
        id: `msg-${ts}`,
        role: 'assistant',
        content: `这是对「${prompt.slice(0, 30)}」的模拟回复。\n\n实际使用时会连接 Python bridge 获取真实 LLM 响应。`,
        status: 'completed',
        createdAt: ts,
      };
      const current = mockMessages.get(sessionId) || [];
      current.push(reply);
      mockMessages.set(sessionId, current);
      mockRunning.delete(sessionId);
    }, 800);

    return userMsg.id;
  }

  const filesMeta = (files || []).map((f) => ({ name: f.name, path: f.path, size: f.size }));

  // Upload images that only have base64 (pasted/dropped) to get file paths
  const imageMetas: { name: string; path: string }[] = [];
  for (const img of images || []) {
    const hasRealPath = img.path && !img.path.startsWith('data:') && img.path !== img.name;
    if (hasRealPath) {
      imageMetas.push({ name: img.name, path: img.path });
    } else {
      const dataUrl = img.base64 || (img.path?.startsWith('data:') ? img.path : undefined);
      if (dataUrl) {
        const path = await uploadImage(sessionId, img.name, dataUrl);
        imageMetas.push({ name: img.name, path });
      }
    }
  }

  const res = await fetch(`${BRIDGE_BASE}/session/${sessionId}/prompt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId, prompt, display: prompt, files: filesMeta, imageMetas }),
  });
  const data = await res.json();
  return data.userMessageId;
}

export async function pollMessages(
  sessionId: string,
  afterId?: string,
  limit: number = 50,
): Promise<PollResult> {
  if (useMock()) {
    await mockDelay(100);
    const msgs = mockMessages.get(sessionId) || [];
    const afterIdx = afterId ? msgs.findIndex((m) => m.id === afterId) : -1;
    const newMsgs = msgs.slice(afterIdx + 1);
    return { messages: newMsgs, status: mockRunning.has(sessionId) ? 'running' : 'idle' };
  }

  const params = new URLSearchParams({ limit: String(limit) });
  if (afterId) params.set('after', afterId);
  const res = await fetch(`${BRIDGE_BASE}/session/${sessionId}/messages?${params}`);
  const data = await res.json();
  return {
    messages: (data.messages || []).map((m: Record<string, unknown>) => normalizeMessage(m)),
    partial: data.partial ? normalizeMessage(data.partial, 'in_progress') : undefined,
    status: data.status,
    plan: data.plan,
    model: data.model,
  };
}

export async function cancelGeneration(sessionId: string): Promise<void> {
  if (useMock()) return;
  await fetch(`${BRIDGE_BASE}/session/${sessionId}/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId }),
  });
}

export async function setSessionModel(
  sessionId: string,
  llmNo: number,
): Promise<{ ok: boolean; llmNo: number; model: { isMixin: boolean; current: string; llmNo?: number; runningLlmNo?: number | null; runningModel?: string | null } }> {
  const res = await fetch(`${BRIDGE_BASE}/session/${sessionId}/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ llmNo }),
  });
  return res.json();
}

export async function listSessions(): Promise<SessionInfo[]> {
  if (useMock()) {
    return Array.from(mockMessages.keys()).map((id) => ({
      id,
      title: `Session ${id.split('-').pop()}`,
      untitled: true,
    }));
  }
  const res = await fetch(`${BRIDGE_BASE}/sessions`);
  const data = await res.json();
  const all: SessionInfo[] = data.sessions || [];
  // Filter out conductor worker sessions (tui_ prefix = internal dispatch)
  return all.filter((s) => !s.id.startsWith('tui_'));
}

export async function deleteSession(sessionId: string): Promise<void> {
  if (useMock()) {
    mockMessages.delete(sessionId);
    return;
  }
  await fetch(`${BRIDGE_BASE}/session/${sessionId}`, { method: 'DELETE' });
}

export async function renameSession(sessionId: string, title: string): Promise<void> {
  if (useMock()) return;
  await fetch(`${BRIDGE_BASE}/session/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
}

export async function pinSession(sessionId: string, pinned: boolean): Promise<void> {
  if (useMock()) return;
  await fetch(`${BRIDGE_BASE}/session/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pinned }),
  });
}
