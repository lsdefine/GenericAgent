// @vitest-environment node
import { describe, it, expect } from 'vitest';
import {
  parseToolCallBlock,
  foldAgentProtocolBlocks,
  parseAgentContent,
  stripTurnMarker,
} from '../components/chat/agentProtocol';

describe('stripTurnMarker', () => {
  it('removes bold turn marker', () => {
    expect(stripTurnMarker('**LLM Running (Turn 3) ...**\nHello')).toBe('Hello');
  });

  it('removes plain turn marker', () => {
    expect(stripTurnMarker('LLM Running (Turn 1) ...\nWorld')).toBe('World');
  });

  it('leaves normal text untouched', () => {
    expect(stripTurnMarker('just some text')).toBe('just some text');
  });

  it('handles empty string', () => {
    expect(stripTurnMarker('')).toBe('');
  });
});

describe('parseToolCallBlock', () => {
  it('parses a complete tool call block', () => {
    const lines = [
      '🛠️ Tool: `file_read`',
      '```text',
      'path: /tmp/hello.txt',
      '```',
      'some other content',
    ];
    const result = parseToolCallBlock(lines, 0);
    expect(result).not.toBeNull();
    expect(result!.name).toBe('file_read');
    expect(result!.body).toBe('path: /tmp/hello.txt');
    expect(result!.nextLine).toBe(4);
  });

  it('returns null for non-tool lines', () => {
    const lines = ['Hello world', '```text', 'foo', '```'];
    expect(parseToolCallBlock(lines, 0)).toBeNull();
  });

  it('returns null when no opening fence', () => {
    const lines = ['🛠️ Tool: `code_run`', 'not a fence'];
    expect(parseToolCallBlock(lines, 0)).toBeNull();
  });

  it('handles multi-line tool body', () => {
    const lines = [
      '🛠️ Tool: `code_run`',
      '```text',
      'line 1',
      'line 2',
      'line 3',
      '```',
    ];
    const result = parseToolCallBlock(lines, 0);
    expect(result).not.toBeNull();
    expect(result!.body).toBe('line 1\nline 2\nline 3');
    expect(result!.nextLine).toBe(6);
  });
});

describe('foldAgentProtocolBlocks', () => {
  it('folds tool and result blocks with callbacks', () => {
    const input = [
      'Before tool',
      '🛠️ Tool: `file_read`',
      '```text',
      '/tmp/test.txt',
      '```',
      '`````',
      'File content here',
      '`````',
      'After result',
    ].join('\n');

    const tools: string[] = [];
    const results: string[] = [];
    foldAgentProtocolBlocks(input, {
      onTool(name, body) {
        tools.push(`${name}:${body}`);
        return '[TOOL]';
      },
      onResult(body) {
        results.push(body);
        return '[RESULT]';
      },
    });

    expect(tools).toEqual(['file_read:/tmp/test.txt']);
    expect(results).toEqual(['File content here']);
  });

  it('passes through text with no protocol blocks', () => {
    const input = 'Hello world\nNo tools here';
    const output = foldAgentProtocolBlocks(input, {
      onTool: () => '[T]',
      onResult: () => '[R]',
    });
    expect(output).toBe(input);
  });
});

describe('parseAgentContent', () => {
  it('parses plain prose', () => {
    const segments = parseAgentContent('Hello world');
    expect(segments).toHaveLength(1);
    expect(segments[0].type).toBe('prose');
    expect(segments[0].content).toBe('Hello world');
  });

  it('extracts thinking blocks', () => {
    const raw = '<thinking>I need to think</thinking>\nHere is my answer';
    const segments = parseAgentContent(raw);
    const thinking = segments.find((s) => s.type === 'thinking');
    const prose = segments.find((s) => s.type === 'prose');
    expect(thinking).toBeDefined();
    expect(thinking!.content).toBe('I need to think');
    expect(prose).toBeDefined();
    expect(prose!.content).toBe('Here is my answer');
  });

  it('extracts summary blocks', () => {
    const raw = 'Text before\n<summary>Task complete</summary>\nText after';
    const segments = parseAgentContent(raw);
    const summary = segments.find((s) => s.type === 'summary');
    expect(summary).toBeDefined();
    expect(summary!.content).toBe('Task complete');
  });

  it('parses tool call blocks', () => {
    const raw = [
      'Let me read the file.',
      '🛠️ Tool: `file_read`',
      '```text',
      '/tmp/data.csv',
      '```',
      '`````',
      'col1,col2',
      '`````',
      'The file contains data.',
    ].join('\n');

    const segments = parseAgentContent(raw);
    const tool = segments.find((s) => s.type === 'tool');
    const result = segments.find((s) => s.type === 'result');
    expect(tool).toBeDefined();
    expect(tool!.label).toBe('file_read');
    expect(tool!.content).toBe('/tmp/data.csv');
    expect(result).toBeDefined();
    expect(result!.content).toBe('col1,col2');
  });

  it('handles ask_user tool as approval segment', () => {
    const raw = [
      '🛠️ Tool: `ask_user`',
      '```text',
      'Do you want to proceed?',
      'candidates:',
      '- Yes',
      '- No',
      '```',
    ].join('\n');

    const segments = parseAgentContent(raw);
    const approval = segments.find((s) => s.type === 'approval');
    expect(approval).toBeDefined();
    expect(approval!.content).toContain('proceed');
    expect(approval!.candidates).toEqual(['Yes', 'No']);
  });

  it('strips turn marker before parsing', () => {
    const raw = '**LLM Running (Turn 2) ...**\nHello from turn 2';
    const segments = parseAgentContent(raw);
    expect(segments).toHaveLength(1);
    expect(segments[0].content).toBe('Hello from turn 2');
  });

  it('handles empty content', () => {
    const segments = parseAgentContent('');
    expect(segments).toHaveLength(0);
  });

  it('handles multiple thinking blocks', () => {
    const raw = '<thinking>First thought</thinking>\nAction\n<thinking>Second thought</thinking>\nResult';
    const segments = parseAgentContent(raw);
    const thinkings = segments.filter((s) => s.type === 'thinking');
    expect(thinkings).toHaveLength(2);
    expect(thinkings[0].content).toBe('First thought');
    expect(thinkings[1].content).toBe('Second thought');
  });

  it('handles function_calls XML blocks', () => {
    const raw = 'Text\n<function_calls><invoke name="test"><param>val</param></invoke></function_calls>\nAfter';
    const segments = parseAgentContent(raw);
    const tool = segments.find((s) => s.type === 'tool');
    expect(tool).toBeDefined();
    expect(tool!.label).toBe('function_call');
  });
});
