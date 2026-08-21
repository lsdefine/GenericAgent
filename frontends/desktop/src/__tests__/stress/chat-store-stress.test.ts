// @vitest-environment node
import { describe, it, expect } from 'vitest';

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

describe('mergeMessages stress tests', () => {
  it('handles 300+ message merge without data loss', () => {
    const existing: Message[] = [];
    for (let i = 0; i < 150; i++) {
      existing.push(msg(`e-${i}`, i % 2 === 0 ? 'user' : 'assistant', `msg-${i}`, i * 100));
    }
    const incoming: Message[] = [];
    for (let i = 100; i < 250; i++) {
      incoming.push(msg(`e-${i}`, i % 2 === 0 ? 'user' : 'assistant', `msg-${i}`, i * 100));
    }

    const result = mergeMessages(existing, incoming);
    expect(result.length).toBe(250);
    expect(result[0].id).toBe('e-0');
    expect(result[249].id).toBe('e-249');
  });

  it('maintains sort stability with identical timestamps', () => {
    const msgs: Message[] = [];
    for (let i = 0; i < 50; i++) {
      msgs.push(msg(`batch-${i}`, 'assistant', `content-${i}`, 1000));
    }
    const result = mergeMessages([], msgs);
    expect(result.length).toBe(50);
    for (let i = 0; i < 50; i++) {
      expect(result[i].id).toBe(`batch-${i}`);
    }
  });

  it('concurrent partial updates do not corrupt message array', () => {
    const base: Message[] = [];
    for (let i = 0; i < 100; i++) {
      base.push(msg(`m-${i}`, 'user', `text-${i}`, i * 100));
    }

    const partial1: Message = { id: PARTIAL_MSG_ID, role: 'assistant', content: 'partial-1', status: 'in_progress' };
    const result1 = mergeMessages(base, [], partial1);
    expect(result1.length).toBe(101);
    expect(result1[100].content).toBe('partial-1');

    const partial2: Message = { id: PARTIAL_MSG_ID, role: 'assistant', content: 'partial-2', status: 'in_progress' };
    const result2 = mergeMessages(result1, [], partial2);
    expect(result2.length).toBe(101);
    expect(result2[100].content).toBe('partial-2');
  });

  it('local messages survive until confirmed by server', () => {
    const local: Message[] = [
      msg('local-1', 'user', 'hello', 100),
      msg('local-2', 'user', 'world', 200),
    ];
    const serverConfirmed: Message[] = [
      msg('srv-1', 'user', 'hello', 100),
    ];

    const result = mergeMessages(local, serverConfirmed);
    expect(result.length).toBe(2);
    expect(result.find((m) => m.id === 'srv-1')).toBeTruthy();
    expect(result.find((m) => m.id === 'local-2')).toBeTruthy();
    expect(result.find((m) => m.id === 'local-1')).toBeUndefined();
  });

  it('rapid partial → confirmed transitions preserve order', () => {
    let state: Message[] = [];
    for (let turn = 0; turn < 50; turn++) {
      const userMsg = msg(`u-${turn}`, 'user', `q-${turn}`, turn * 200);
      state = mergeMessages(state, [userMsg]);

      const partial: Message = { id: PARTIAL_MSG_ID, role: 'assistant', content: `partial-${turn}`, status: 'in_progress' };
      state = mergeMessages(state, [], partial);

      const confirmed = msg(`a-${turn}`, 'assistant', `answer-${turn}`, turn * 200 + 100);
      state = mergeMessages(state, [confirmed]);
    }

    const nonPartial = state.filter((m) => m.id !== PARTIAL_MSG_ID);
    expect(nonPartial.length).toBe(100);
    for (let i = 0; i < nonPartial.length - 1; i++) {
      expect((nonPartial[i].createdAt ?? 0) <= (nonPartial[i + 1].createdAt ?? 0)).toBe(true);
    }
  });

  it('handles 500 messages without performance degradation', () => {
    const large: Message[] = [];
    for (let i = 0; i < 500; i++) {
      large.push(msg(`big-${i}`, i % 2 === 0 ? 'user' : 'assistant', `content-${i}`, i));
    }

    const start = performance.now();
    const result = mergeMessages([], large);
    const elapsed = performance.now() - start;

    expect(result.length).toBe(500);
    expect(elapsed).toBeLessThan(100);
  });

  it('empty incoming does not mutate existing', () => {
    const existing: Message[] = [];
    for (let i = 0; i < 200; i++) {
      existing.push(msg(`e-${i}`, 'user', `text-${i}`, i * 10));
    }
    const result = mergeMessages(existing, []);
    expect(result.length).toBe(200);
    expect(result).toEqual(existing);
  });
});
