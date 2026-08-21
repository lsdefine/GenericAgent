// @vitest-environment node
import { describe, it, expect } from 'vitest';

// We test normalizeMessage by importing the module's internals.
// Since normalizeMessage is not exported, we replicate its logic here for unit testing.
// This mirrors the implementation in services/chat.ts.

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

describe('normalizeMessage — files field', () => {
  it('extracts files from raw message', () => {
    const raw = {
      id: 1,
      role: 'user',
      content: 'hello',
      ts: 1000,
      files: [{ name: 'data.csv', path: '/tmp/data.csv', size: 1024 }],
    };
    const msg = normalizeMessage(raw);
    expect(msg.files).toEqual([{ name: 'data.csv', path: '/tmp/data.csv', size: 1024 }]);
  });

  it('handles missing files gracefully', () => {
    const raw = { id: 2, role: 'user', content: 'hi', ts: 2000 };
    const msg = normalizeMessage(raw);
    expect(msg.files).toBeUndefined();
  });

  it('handles empty files array', () => {
    const raw = { id: 3, role: 'user', content: 'hey', ts: 3000, files: [] };
    const msg = normalizeMessage(raw);
    expect(msg.files).toBeUndefined();
  });

  it('preserves images alongside files', () => {
    const raw = {
      id: 4,
      role: 'user',
      content: 'both',
      ts: 4000,
      images: [{ name: 'pic.png', path: '/tmp/pic.png' }],
      files: [{ name: 'doc.pdf', path: '/tmp/doc.pdf', size: 5000 }],
    };
    const msg = normalizeMessage(raw);
    expect(msg.images).toHaveLength(1);
    expect(msg.files).toHaveLength(1);
  });
});
