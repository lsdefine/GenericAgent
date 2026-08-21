interface FenceLine {
  ticks: number;
  tag: string;
}

interface ToolBlock {
  name: string;
  body: string;
  nextLine: number;
  inFlight?: boolean;
}

interface ResultBlock {
  body: string;
  nextLine: number;
  inFlight?: boolean;
}

export interface FoldCallbacks {
  onTool: (name: string, body: string, meta?: { inFlight?: boolean }) => string;
  onResult: (body: string, meta?: { inFlight?: boolean }) => string;
}

function parseAgentFenceLine(line: string | undefined): FenceLine | null {
  const m = /^[ \t]*(`{3,})([^\n`]*)[ \t]*$/.exec(line ?? '');
  if (!m) return null;
  return { ticks: m[1].length, tag: m[2] };
}

function isAgentStructureBoundaryLine(line: string, opts?: { forToolResult?: boolean }): boolean {
  if (/^🛠️ Tool:/.test(line)) return true;
  if (!opts?.forToolResult) {
    const f = parseAgentFenceLine(line);
    if (f && f.ticks >= 5 && f.tag === '') return true;
  }
  if (/^\*\*LLM Running \(Turn \d+\)/.test(line)) return true;
  if (/^<thinking>/i.test(line)) return true;
  return false;
}

function indexOfNextAgentStructureLine(lines: string[], from: number, opts?: { forToolResult?: boolean }): number {
  for (let i = from; i < lines.length; i++) {
    if (isAgentStructureBoundaryLine(lines[i], opts)) return i;
  }
  return lines.length;
}

function lastFenceCloseLineIndex(lines: string[], from: number, toExclusive: number, tickCount: number): number {
  let last = -1;
  for (let i = from; i < toExclusive; i++) {
    const f = parseAgentFenceLine(lines[i]);
    if (f && f.ticks === tickCount && f.tag === '') last = i;
  }
  return last;
}

export function parseToolCallBlock(lines: string[], i: number): ToolBlock | null {
  const m = /^🛠️ Tool: `([^`]+)`/.exec(lines[i] || '');
  if (!m) return null;
  const open = parseAgentFenceLine(lines[i + 1]);
  if (!open || open.tag !== 'text') return null;
  const bodyStart = i + 2;
  const zoneEnd = indexOfNextAgentStructureLine(lines, bodyStart);
  const closeIdx = lastFenceCloseLineIndex(lines, bodyStart, zoneEnd, open.ticks);
  if (closeIdx < 0) return null;
  return { name: m[1], body: lines.slice(bodyStart, closeIdx).join('\n'), nextLine: closeIdx + 1 };
}

function parseToolResultBlock(lines: string[], i: number): ResultBlock | null {
  const open = parseAgentFenceLine(lines[i]);
  if (!open || open.ticks < 5 || open.tag !== '') return null;
  const bodyStart = i + 1;
  const zoneEnd = indexOfNextAgentStructureLine(lines, bodyStart, { forToolResult: true });
  const closeIdx = lastFenceCloseLineIndex(lines, bodyStart, zoneEnd, open.ticks);
  if (closeIdx < 0) return null;
  return { body: lines.slice(bodyStart, closeIdx).join('\n'), nextLine: closeIdx + 1 };
}

function parseInFlightToolCall(lines: string[], i: number): ToolBlock | null {
  if (parseToolCallBlock(lines, i)) return null;
  const m = /^🛠️ Tool: `([^`]+)`/.exec(lines[i] || '');
  if (!m) return null;
  const open = parseAgentFenceLine(lines[i + 1]);
  let bodyStart: number;
  let zoneEnd: number;
  if (open && open.tag === 'text') {
    bodyStart = i + 2;
    zoneEnd = indexOfNextAgentStructureLine(lines, bodyStart);
    if (lastFenceCloseLineIndex(lines, bodyStart, zoneEnd, open.ticks) >= 0) return null;
  } else {
    bodyStart = i + 1;
    zoneEnd = lines.length;
    for (let j = i + 1; j < lines.length; j++) {
      if (isAgentStructureBoundaryLine(lines[j])) { zoneEnd = j; break; }
    }
  }
  return { name: m[1], body: lines.slice(bodyStart, zoneEnd).join('\n'), nextLine: zoneEnd, inFlight: true };
}

function parseInFlightToolResult(lines: string[], i: number): ResultBlock | null {
  if (parseToolResultBlock(lines, i)) return null;
  const open = parseAgentFenceLine(lines[i]);
  if (!open || open.ticks < 5 || open.tag !== '') return null;
  const bodyStart = i + 1;
  const zoneEnd = indexOfNextAgentStructureLine(lines, bodyStart, { forToolResult: true });
  if (lastFenceCloseLineIndex(lines, bodyStart, zoneEnd, open.ticks) >= 0) return null;
  return { body: lines.slice(bodyStart, zoneEnd).join('\n'), nextLine: zoneEnd, inFlight: true };
}

export function stripTurnMarker(body: string): string {
  return body.replace(/^\s*\**LLM Running \(Turn \d+\) \.\.\.\**\s*/i, '');
}

export function foldAgentProtocolBlocks(body: string, callbacks: FoldCallbacks): string {
  const lines = String(body || '').split('\n');
  const out: string[] = [];
  let proseFrom = 0;
  let i = 0;

  const flushProse = (until: number) => {
    if (until <= proseFrom) return;
    out.push(lines.slice(proseFrom, until).join('\n'));
    proseFrom = until;
  };

  while (i < lines.length) {
    const tool = parseToolCallBlock(lines, i);
    if (tool) {
      flushProse(i);
      out.push(callbacks.onTool(tool.name, tool.body));
      i = tool.nextLine;
      proseFrom = i;
      continue;
    }
    const result = parseToolResultBlock(lines, i);
    if (result) {
      flushProse(i);
      out.push(callbacks.onResult(result.body));
      i = result.nextLine;
      proseFrom = i;
      continue;
    }
    const liveTool = parseInFlightToolCall(lines, i);
    if (liveTool) {
      flushProse(i);
      out.push(callbacks.onTool(liveTool.name, liveTool.body, { inFlight: true }));
      i = liveTool.nextLine;
      proseFrom = i;
      continue;
    }
    const liveResult = parseInFlightToolResult(lines, i);
    if (liveResult) {
      flushProse(i);
      out.push(callbacks.onResult(liveResult.body, { inFlight: true }));
      i = liveResult.nextLine;
      proseFrom = i;
      continue;
    }
    i++;
  }
  flushProse(lines.length);
  return out.join('');
}

export interface ParsedSegment {
  type: 'prose' | 'thinking' | 'tool' | 'result' | 'summary' | 'approval';
  content: string;
  label?: string;
  inFlight?: boolean;
  candidates?: string[];
}

function parseAskUserCandidates(body: string): string[] {
  const lines = body.split('\n');
  const candidates: string[] = [];
  let inCandidates = false;
  for (const line of lines) {
    if (/candidates:/i.test(line)) { inCandidates = true; continue; }
    if (inCandidates) {
      const m = /^\s*-\s*(.+)/.exec(line);
      if (m) candidates.push(m[1].trim());
    }
  }
  if (candidates.length === 0) {
    try {
      const parsed = JSON.parse(body);
      if (Array.isArray(parsed?.candidates)) return parsed.candidates.map(String);
    } catch {}
  }
  return candidates;
}

function extractAskUserQuestion(body: string): string {
  const lines = body.split('\n');
  const questionLines: string[] = [];
  for (const line of lines) {
    if (/candidates:/i.test(line)) break;
    const cleaned = line.replace(/^["{\s]*question[":\s]*/i, '').replace(/[",}\s]*$/, '');
    if (cleaned) questionLines.push(cleaned);
  }
  if (questionLines.length > 0) return questionLines.join('\n');
  try {
    const parsed = JSON.parse(body);
    if (parsed?.question) return String(parsed.question);
  } catch {}
  return body.trim();
}

export function parseAgentContent(raw: string): ParsedSegment[] {
  const segments: ParsedSegment[] = [];
  let text = stripTurnMarker(raw);

  // Extract thinking blocks
  const thinkingParts: string[] = [];
  text = text.replace(/<thinking>([\s\S]*?)<\/thinking>/gi, (_, inner) => {
    thinkingParts.push(inner);
    return `\n§§THINK:${thinkingParts.length - 1}§§\n`;
  });

  // Extract summary blocks
  const summaryParts: string[] = [];
  text = text.replace(/<summary>([\s\S]*?)<\/summary>/gi, (_, inner) => {
    summaryParts.push(inner);
    return `\n§§SUMMARY:${summaryParts.length - 1}§§\n`;
  });

  // Fold tool/result blocks
  const toolParts: { name: string; body: string; inFlight?: boolean }[] = [];
  const resultParts: { body: string; inFlight?: boolean }[] = [];

  text = foldAgentProtocolBlocks(text, {
    onTool(name, body, meta) {
      toolParts.push({ name, body, inFlight: meta?.inFlight });
      return `\n§§TOOL:${toolParts.length - 1}§§\n`;
    },
    onResult(body, meta) {
      resultParts.push({ body, inFlight: meta?.inFlight });
      return `\n§§RESULT:${resultParts.length - 1}§§\n`;
    },
  });

  // Also handle <function_calls>/<function_results> style blocks
  text = text.replace(/<function_calls>[\s\S]*?<\/function_calls>/gi, (m) => {
    toolParts.push({ name: 'function_call', body: m });
    return `\n§§TOOL:${toolParts.length - 1}§§\n`;
  });
  text = text.replace(/<function_results>[\s\S]*?<\/function_results>/gi, (m) => {
    resultParts.push({ body: m });
    return `\n§§RESULT:${resultParts.length - 1}§§\n`;
  });

  // Split on placeholders and build segments
  const parts = text.split(/\n?(§§(?:THINK|TOOL|RESULT|SUMMARY):\d+§§)\n?/);
  for (const part of parts) {
    const thinkMatch = /^§§THINK:(\d+)§§$/.exec(part);
    if (thinkMatch) {
      segments.push({ type: 'thinking', content: thinkingParts[Number(thinkMatch[1])] });
      continue;
    }
    const toolMatch = /^§§TOOL:(\d+)§§$/.exec(part);
    if (toolMatch) {
      const t = toolParts[Number(toolMatch[1])];
      if (t.name === 'ask_user') {
        const candidates = parseAskUserCandidates(t.body);
        const question = extractAskUserQuestion(t.body);
        segments.push({ type: 'approval', content: question, candidates });
      } else {
        segments.push({ type: 'tool', content: t.body, label: t.name, inFlight: t.inFlight });
      }
      continue;
    }
    const resultMatch = /^§§RESULT:(\d+)§§$/.exec(part);
    if (resultMatch) {
      const r = resultParts[Number(resultMatch[1])];
      segments.push({ type: 'result', content: r.body, inFlight: r.inFlight });
      continue;
    }
    const summaryMatch = /^§§SUMMARY:(\d+)§§$/.exec(part);
    if (summaryMatch) {
      segments.push({ type: 'summary', content: summaryParts[Number(summaryMatch[1])] });
      continue;
    }
    const trimmed = part.trim();
    if (trimmed) {
      segments.push({ type: 'prose', content: trimmed });
    }
  }
  return segments;
}
