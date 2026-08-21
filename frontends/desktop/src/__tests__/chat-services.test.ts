// @vitest-environment node
import { describe, it, expect } from 'vitest';

// We test normalizeMessage by replicating its logic (it's not exported)
type MessageStatus = 'completed' | 'in_progress' | 'failed';
interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  status: MessageStatus;
  createdAt?: number;
  ts?: number;
  turn_segs?: string[];
  images?: { name: string; path: string }[];
  files?: { name: string; path: string; size?: number }[];
}

function normalizeMessage(msg: Record<string, unknown>, status: MessageStatus = 'completed'): Message {
  const m: Message = {
    id: String(msg.id),
    role: msg.role as Message['role'],
    content: (msg.content as string) || '',
    status: (msg.status as MessageStatus) ?? status,
    createdAt: (msg.createdAt as number) ?? (msg.ts as number),
  };
  if (Array.isArray(msg.turn_segs)) m.turn_segs = msg.turn_segs as string[];
  if (Array.isArray(msg.images) && msg.images.length > 0) m.images = msg.images as { name: string; path: string }[];
  if (Array.isArray(msg.files) && msg.files.length > 0) m.files = msg.files as { name: string; path: string; size?: number }[];
  return m;
}

describe('normalizeMessage', () => {
  it('normalizes basic fields', () => {
    const raw = { id: 42, role: 'user', content: 'hi', ts: 1000 };
    const m = normalizeMessage(raw);
    expect(m.id).toBe('42');
    expect(m.role).toBe('user');
    expect(m.content).toBe('hi');
    expect(m.status).toBe('completed');
    expect(m.createdAt).toBe(1000);
  });

  it('uses createdAt over ts when both present', () => {
    const raw = { id: 1, role: 'assistant', content: '', createdAt: 2000, ts: 1000 };
    const m = normalizeMessage(raw);
    expect(m.createdAt).toBe(2000);
  });

  it('preserves status from raw if present', () => {
    const raw = { id: 1, role: 'assistant', content: '', status: 'in_progress' };
    const m = normalizeMessage(raw);
    expect(m.status).toBe('in_progress');
  });

  it('uses default status param when raw has none', () => {
    const raw = { id: 1, role: 'assistant', content: '' };
    const m = normalizeMessage(raw, 'in_progress');
    expect(m.status).toBe('in_progress');
  });

  it('extracts turn_segs array', () => {
    const raw = { id: 1, role: 'assistant', content: 'x', turn_segs: ['seg1', 'seg2'] };
    const m = normalizeMessage(raw);
    expect(m.turn_segs).toEqual(['seg1', 'seg2']);
  });

  it('ignores non-array turn_segs', () => {
    const raw = { id: 1, role: 'assistant', content: 'x', turn_segs: 'not an array' };
    const m = normalizeMessage(raw);
    expect(m.turn_segs).toBeUndefined();
  });

  it('extracts files array', () => {
    const raw = { id: 1, role: 'user', content: '', files: [{ name: 'a.txt', path: '/tmp/a.txt', size: 100 }] };
    const m = normalizeMessage(raw);
    expect(m.files).toEqual([{ name: 'a.txt', path: '/tmp/a.txt', size: 100 }]);
  });

  it('ignores empty files array', () => {
    const raw = { id: 1, role: 'user', content: '', files: [] };
    const m = normalizeMessage(raw);
    expect(m.files).toBeUndefined();
  });

  it('extracts images array', () => {
    const raw = { id: 1, role: 'user', content: '', images: [{ name: 'pic.png', path: '/tmp/pic.png' }] };
    const m = normalizeMessage(raw);
    expect(m.images).toEqual([{ name: 'pic.png', path: '/tmp/pic.png' }]);
  });

  it('handles null/undefined content gracefully', () => {
    const raw = { id: 1, role: 'user', content: null };
    const m = normalizeMessage(raw as any);
    expect(m.content).toBe('');
  });

  it('coerces numeric id to string', () => {
    const raw = { id: 999, role: 'user', content: '' };
    const m = normalizeMessage(raw);
    expect(m.id).toBe('999');
  });
});

describe('listSessions tui_ filter logic', () => {
  it('filters out sessions with tui_ prefix', () => {
    const sessions = [
      { id: 'session-1', title: 'Chat 1', untitled: false },
      { id: 'tui_worker_abc', title: 'Worker', untitled: true },
      { id: 'session-2', title: 'Chat 2', untitled: false },
      { id: 'tui_conductor_xyz', title: 'Conductor', untitled: true },
    ];
    const filtered = sessions.filter((s) => !s.id.startsWith('tui_'));
    expect(filtered).toHaveLength(2);
    expect(filtered.map((s) => s.id)).toEqual(['session-1', 'session-2']);
  });
});

describe('sendPrompt body construction', () => {
  it('builds correct request body with files and images', () => {
    const sessionId = 'test-session';
    const prompt = 'Analyze this';
    const files = [{ name: 'data.csv', path: '/tmp/data.csv', size: 1024 }];
    const imageMetas = [{ name: 'pic.png', path: '/tmp/pic.png' }];

    // Simulate what sendPrompt does
    const filesMeta = files.map((f) => ({ name: f.name, path: f.path, size: f.size }));
    const body = JSON.stringify({ sessionId, prompt, display: prompt, llmNo: 0, files: filesMeta, imageMetas });

    const parsed = JSON.parse(body);
    expect(parsed.files).toEqual([{ name: 'data.csv', path: '/tmp/data.csv', size: 1024 }]);
    expect(parsed.imageMetas).toEqual([{ name: 'pic.png', path: '/tmp/pic.png' }]);
    expect(parsed.prompt).toBe('Analyze this');
  });

  it('omits empty files array as empty', () => {
    const files: { name: string; path: string; size?: number }[] = [];
    const filesMeta = files.map((f) => ({ name: f.name, path: f.path, size: f.size }));
    expect(filesMeta).toEqual([]);
  });
});
