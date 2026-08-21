// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { buildThreadGroups } from '../lib/thread-grouping';
import type { Message } from '../services/chat';

function msg(overrides: Partial<Message> & { id: string; role: Message['role'] }): Message {
  return { content: '', status: 'completed', ...overrides };
}

describe('buildThreadGroups', () => {
  it('pairs consecutive user+assistant into a turn group', () => {
    const messages: Message[] = [
      msg({ id: '1', role: 'user', content: 'Hello' }),
      msg({ id: '2', role: 'assistant', content: 'Hi there' }),
    ];
    const groups = buildThreadGroups(messages);
    expect(groups).toHaveLength(1);
    expect(groups[0].kind).toBe('turn');
    if (groups[0].kind === 'turn') {
      expect(groups[0].userMsg.id).toBe('1');
      expect(groups[0].assistantMsg.id).toBe('2');
      expect(groups[0].turns).toHaveLength(1);
      expect(groups[0].turns[0].segments).toHaveLength(1);
    }
  });

  it('creates standalone group for user without following assistant', () => {
    const messages: Message[] = [
      msg({ id: '1', role: 'user', content: 'Question' }),
    ];
    const groups = buildThreadGroups(messages);
    expect(groups).toHaveLength(1);
    expect(groups[0].kind).toBe('standalone');
    if (groups[0].kind === 'standalone') {
      expect(groups[0].msg.id).toBe('1');
    }
  });

  it('handles assistant without preceding user (synthetic user)', () => {
    const messages: Message[] = [
      msg({ id: '1', role: 'assistant', content: 'System greeting' }),
    ];
    const groups = buildThreadGroups(messages);
    expect(groups).toHaveLength(1);
    expect(groups[0].kind).toBe('turn');
    if (groups[0].kind === 'turn') {
      expect(groups[0].userMsg.id).toBe('__synthetic__');
      expect(groups[0].assistantMsg.id).toBe('1');
    }
  });

  it('handles multiple turn pairs', () => {
    const messages: Message[] = [
      msg({ id: '1', role: 'user', content: 'Q1' }),
      msg({ id: '2', role: 'assistant', content: 'A1' }),
      msg({ id: '3', role: 'user', content: 'Q2' }),
      msg({ id: '4', role: 'assistant', content: 'A2' }),
    ];
    const groups = buildThreadGroups(messages);
    expect(groups).toHaveLength(2);
    expect(groups[0].kind).toBe('turn');
    expect(groups[1].kind).toBe('turn');
  });

  it('parses turn_segs into multiple turns', () => {
    const messages: Message[] = [
      msg({ id: '1', role: 'user', content: 'Do it' }),
      msg({ id: '2', role: 'assistant', content: 'Turn1\nTurn2', turn_segs: ['Turn 1 content', 'Turn 2 content'] }),
    ];
    const groups = buildThreadGroups(messages);
    expect(groups).toHaveLength(1);
    if (groups[0].kind === 'turn') {
      expect(groups[0].turns).toHaveLength(2);
      expect(groups[0].turns[0].index).toBe(0);
      expect(groups[0].turns[1].index).toBe(1);
    }
  });

  it('handles system messages as standalone', () => {
    const messages: Message[] = [
      msg({ id: '1', role: 'system', content: 'System init' }),
      msg({ id: '2', role: 'user', content: 'Hello' }),
      msg({ id: '3', role: 'assistant', content: 'Hi' }),
    ];
    const groups = buildThreadGroups(messages);
    expect(groups).toHaveLength(2);
    expect(groups[0].kind).toBe('standalone');
    expect(groups[1].kind).toBe('turn');
  });

  it('handles consecutive user messages (second user is standalone)', () => {
    const messages: Message[] = [
      msg({ id: '1', role: 'user', content: 'First' }),
      msg({ id: '2', role: 'user', content: 'Second' }),
      msg({ id: '3', role: 'assistant', content: 'Reply' }),
    ];
    const groups = buildThreadGroups(messages);
    expect(groups).toHaveLength(2);
    expect(groups[0].kind).toBe('standalone');
    if (groups[0].kind === 'standalone') expect(groups[0].msg.id).toBe('1');
    expect(groups[1].kind).toBe('turn');
  });

  it('handles empty message array', () => {
    expect(buildThreadGroups([])).toEqual([]);
  });

  it('calculates weight from segment content length', () => {
    const messages: Message[] = [
      msg({ id: '1', role: 'user', content: 'q' }),
      msg({ id: '2', role: 'assistant', content: 'A long answer with many characters' }),
    ];
    const groups = buildThreadGroups(messages);
    if (groups[0].kind === 'turn') {
      expect(groups[0].turns[0].weight).toBeGreaterThan(0);
    }
  });
});
