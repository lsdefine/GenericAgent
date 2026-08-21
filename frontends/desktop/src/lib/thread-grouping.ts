import type { Message } from '../services/chat';
import { parseAgentContent, type ParsedSegment } from '../components/chat/agentProtocol';

export type SegmentStatus = 'running' | 'done';

export interface Turn {
  index: number;
  segments: ParsedSegment[];
  weight: number;
}

export type ThreadGroup =
  | { kind: 'turn'; userMsg: Message; assistantMsg: Message; turns: Turn[] }
  | { kind: 'standalone'; msg: Message };

function parseTurns(turnSegs: string[]): Turn[] {
  return turnSegs.map((seg, index) => {
    const segments = parseAgentContent(seg);
    const weight = segments.reduce((acc, s) => acc + s.content.length, 0);
    return { index, segments, weight };
  });
}

export function buildThreadGroups(messages: Message[]): ThreadGroup[] {
  const groups: ThreadGroup[] = [];
  let i = 0;

  while (i < messages.length) {
    const msg = messages[i];
    if (msg.role === 'user') {
      const next = messages[i + 1];
      if (next && next.role === 'assistant') {
        const turnSegs = next.turn_segs ?? (next.content ? [next.content] : []);
        const turns = parseTurns(turnSegs);
        groups.push({ kind: 'turn', userMsg: msg, assistantMsg: next, turns });
        i += 2;
      } else {
        groups.push({ kind: 'standalone', msg });
        i++;
      }
    } else {
      if (msg.role === 'assistant') {
        const turnSegs = msg.turn_segs ?? (msg.content ? [msg.content] : []);
        const turns = parseTurns(turnSegs);
        groups.push({
          kind: 'turn',
          userMsg: { id: '__synthetic__', role: 'user', content: '', status: 'completed' },
          assistantMsg: msg,
          turns,
        });
      } else {
        groups.push({ kind: 'standalone', msg });
      }
      i++;
    }
  }
  return groups;
}
