// @vitest-environment node
import { describe, it, expect, beforeEach } from 'vitest';

type WorkerStatus = 'running' | 'reported' | 'paused' | 'failed' | 'terminated';

interface Worker {
  id: string;
  title: string;
  status: WorkerStatus;
  summary: string;
  fullReply: string;
  updatedAt?: number;
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

describe('conductor stress tests', () => {
  beforeEach(() => {
    titleSeq = 0;
    titleSeen.clear();
  });

  describe('mapStatus', () => {
    it('maps all known status strings correctly', () => {
      expect(mapStatus('running', '')).toBe('running');
      expect(mapStatus('failed', '')).toBe('failed');
      expect(mapStatus('aborted', '')).toBe('terminated');
      expect(mapStatus('stopped', 'some reply')).toBe('reported');
      expect(mapStatus('stopped', '')).toBe('paused');
      expect(mapStatus('stopped', '   ')).toBe('paused');
      expect(mapStatus('unknown', '')).toBe('paused');
      expect(mapStatus('', '')).toBe('paused');
    });
  });

  describe('normalizeWorker', () => {
    it('truncates long titles at 18 chars', () => {
      const w = normalizeWorker({ id: '1', prompt: '这是一个非常长的任务名称超过十八个字符限制', status: 'running' });
      expect(w.title.length).toBeLessThanOrEqual(19); // 18 + ellipsis
      expect(w.title).toContain('…');
    });

    it('strips leading whitespace and filler from prompt', () => {
      const w = normalizeWorker({ id: '2', prompt: '请帮我写一个函数', status: 'running' });
      expect(w.title).not.toMatch(/^请帮我/);
    });

    it('generates sequential titles for empty prompts', () => {
      const w1 = normalizeWorker({ id: 'a', prompt: '', status: 'running' });
      const w2 = normalizeWorker({ id: 'b', prompt: '', status: 'running' });
      expect(w1.title).toBe('Task #1');
      expect(w2.title).toBe('Task #2');
    });

    it('reuses title sequence for same id', () => {
      const w1 = normalizeWorker({ id: 'x', prompt: '', status: 'running' });
      const w2 = normalizeWorker({ id: 'x', prompt: '', status: 'stopped', reply: 'done' });
      expect(w1.title).toBe(w2.title);
    });

    it('truncates summary at 80 chars', () => {
      const longReply = 'A'.repeat(200);
      const w = normalizeWorker({ id: '3', prompt: 'test', status: 'stopped', reply: longReply });
      expect(w.summary.length).toBeLessThanOrEqual(81); // 80 + ellipsis
    });
  });

  describe('concurrent worker state transitions', () => {
    it('handles 20 workers transitioning simultaneously', () => {
      const workers: Worker[] = [];
      for (let i = 0; i < 20; i++) {
        workers.push(normalizeWorker({
          id: `w-${i}`,
          prompt: `Task ${i}`,
          status: 'running',
          reply: '',
        }));
      }

      expect(workers.filter((w) => w.status === 'running').length).toBe(20);

      const completed = workers.map((w, i) =>
        normalizeWorker({ id: w.id, prompt: `Task ${i}`, status: 'stopped', reply: `Result ${i}` })
      );

      expect(completed.filter((w) => w.status === 'reported').length).toBe(20);
      expect(completed.every((w) => w.summary.startsWith('Result'))).toBe(true);
    });

    it('interleaved status changes do not lose data', () => {
      const states: Array<{ id: string; status: string; reply: string }> = [];
      for (let i = 0; i < 30; i++) {
        states.push({ id: `w-${i % 10}`, status: i < 10 ? 'running' : i < 20 ? 'stopped' : 'failed', reply: i >= 10 ? `reply-${i}` : '' });
      }

      const results = states.map((s) => normalizeWorker(s));
      expect(results.length).toBe(30);

      const failedSet = new Set(results.filter((w) => w.status === 'failed').map((w) => w.id));
      expect(failedSet.size).toBeGreaterThan(0);
    });
  });

  describe('message dedup with _local flag', () => {
    interface ConductorMessage {
      id: string;
      role: 'user' | 'conductor' | 'system';
      msg: string;
      _local?: boolean;
    }

    function applyChat(messages: ConductorMessage[], incoming: ConductorMessage): ConductorMessage[] {
      if (incoming.id && messages.some((m) => m.id === incoming.id)) return messages;
      if (incoming.role === 'user') {
        const localPlain = incoming.msg.replace(/\[(Image|File)\s+#\d+\]\s*/g, '').trim();
        for (let i = messages.length - 1; i >= 0; i--) {
          const m = messages[i];
          if (m._local && m.role === 'user') {
            const existing = m.msg.replace(/\[(Image|File)\s+#\d+\]\s*/g, '').trim();
            if (existing === localPlain) {
              const updated = [...messages];
              updated[i] = { ...updated[i], id: incoming.id, _local: false };
              return updated;
            }
          }
        }
      }
      return [...messages, incoming];
    }

    it('deduplicates local messages confirmed by server', () => {
      let msgs: ConductorMessage[] = [
        { id: 'local-1', role: 'user', msg: 'hello world', _local: true },
      ];

      msgs = applyChat(msgs, { id: 'srv-1', role: 'user', msg: 'hello world' });
      expect(msgs.length).toBe(1);
      expect(msgs[0].id).toBe('srv-1');
      expect(msgs[0]._local).toBe(false);
    });

    it('handles rapid fire messages without duplication', () => {
      let msgs: ConductorMessage[] = [];
      for (let i = 0; i < 20; i++) {
        msgs = [...msgs, { id: `local-${i}`, role: 'user', msg: `msg-${i}`, _local: true }];
      }
      for (let i = 0; i < 20; i++) {
        msgs = applyChat(msgs, { id: `srv-${i}`, role: 'user', msg: `msg-${i}` });
      }
      expect(msgs.length).toBe(20);
      expect(msgs.every((m) => !m._local)).toBe(true);
    });
  });
});
