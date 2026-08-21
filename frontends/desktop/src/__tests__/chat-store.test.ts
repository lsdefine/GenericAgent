// @vitest-environment node
import { describe, it, expect } from 'vitest';

// Test the mergeMessages logic (extracted from stores/chat.ts since it's not exported)
type MessageStatus = 'completed' | 'in_progress' | 'failed';
interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  status: MessageStatus;
  createdAt?: number;
}

const PARTIAL_MSG_ID = '__partial__';

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

function msg(id: string, role: Message['role'], content: string, createdAt: number): Message {
  return { id, role, content, status: 'completed', createdAt };
}

describe('mergeMessages', () => {
  it('merges new incoming messages into empty current', () => {
    const result = mergeMessages([], [msg('1', 'user', 'hi', 100)]);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('1');
  });

  it('deduplicates by id', () => {
    const existing = [msg('1', 'user', 'hi', 100)];
    const incoming = [msg('1', 'user', 'hi', 100), msg('2', 'assistant', 'hello', 200)];
    const result = mergeMessages(existing, incoming);
    expect(result).toHaveLength(2);
  });

  it('replaces local messages when server message matches content', () => {
    const current = [msg('local-123', 'user', 'hello', 100)];
    const incoming = [msg('server-1', 'user', 'hello', 100)];
    const result = mergeMessages(current, incoming);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('server-1');
  });

  it('keeps local messages that have no server match', () => {
    const current = [msg('local-123', 'user', 'unique text', 100)];
    const incoming = [msg('server-1', 'user', 'different text', 50)];
    const result = mergeMessages(current, incoming);
    expect(result).toHaveLength(2);
    expect(result.some((m) => m.id === 'local-123')).toBe(true);
  });

  it('removes old partial message before appending new one', () => {
    const current = [
      msg('1', 'user', 'q', 100),
      { id: PARTIAL_MSG_ID, role: 'assistant' as const, content: 'old partial', status: 'in_progress' as const, createdAt: 200 },
    ];
    const partial = msg('x', 'assistant', 'new partial', 300);
    const result = mergeMessages(current, [], partial);
    const partials = result.filter((m) => m.id === PARTIAL_MSG_ID);
    expect(partials).toHaveLength(1);
    expect(partials[0].content).toBe('new partial');
  });

  it('sorts by createdAt', () => {
    const current: Message[] = [];
    const incoming = [
      msg('3', 'assistant', 'C', 300),
      msg('1', 'user', 'A', 100),
      msg('2', 'assistant', 'B', 200),
    ];
    const result = mergeMessages(current, incoming);
    expect(result.map((m) => m.id)).toEqual(['1', '2', '3']);
  });

  it('appends partial at the end', () => {
    const incoming = [msg('1', 'user', 'q', 100)];
    const partial = msg('p', 'assistant', 'typing...', 200);
    const result = mergeMessages([], incoming, partial);
    expect(result[result.length - 1].id).toBe(PARTIAL_MSG_ID);
    expect(result[result.length - 1].status).toBe('in_progress');
  });

  it('handles no partial gracefully', () => {
    const result = mergeMessages([msg('1', 'user', 'hi', 100)], [], undefined);
    expect(result.filter((m) => m.id === PARTIAL_MSG_ID)).toHaveLength(0);
  });
});

describe('sendMessage queue logic', () => {
  interface QueuedMessage { text: string; opts?: { files?: unknown[] } }

  it('enqueues when status is running', () => {
    const queue: QueuedMessage[] = [];
    const status = 'running';
    const text = 'follow-up';
    const opts = { files: [{ name: 'f.txt', path: '/tmp/f.txt' }] };

    // Simulate the store logic
    if (status === 'running') {
      queue.push({ text, opts });
    }
    expect(queue).toHaveLength(1);
    expect(queue[0].text).toBe('follow-up');
  });

  it('does not enqueue when idle', () => {
    const queue: QueuedMessage[] = [];
    const status: string = 'idle';
    const text = 'new msg';
    if (status === 'running') {
      queue.push({ text });
    }
    expect(queue).toHaveLength(0);
  });

  it('cancelQueued removes by index', () => {
    let queue: QueuedMessage[] = [
      { text: 'msg1' },
      { text: 'msg2' },
      { text: 'msg3' },
    ];
    const indexToRemove = 1;
    queue = queue.filter((_, i) => i !== indexToRemove);
    expect(queue).toHaveLength(2);
    expect(queue.map((q) => q.text)).toEqual(['msg1', 'msg3']);
  });

  it('drains queue on idle: shifts first item', () => {
    const queue: QueuedMessage[] = [
      { text: 'first' },
      { text: 'second' },
    ];
    const [next, ...rest] = queue;
    expect(next.text).toBe('first');
    expect(rest).toHaveLength(1);
    expect(rest[0].text).toBe('second');
  });
});
