export type DiffLineKind = 'add' | 'remove' | 'context' | 'header';

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
  oldLine?: number;
  newLine?: number;
}

export function parseDiff(raw: string): DiffLine[] {
  const lines = raw.split('\n');
  const result: DiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;

  for (const line of lines) {
    // Skip git diff headers
    if (
      line.startsWith('diff --git') ||
      line.startsWith('index ') ||
      line.startsWith('--- ') ||
      line.startsWith('+++ ') ||
      line.startsWith('new file') ||
      line.startsWith('deleted file') ||
      line.startsWith('similarity index') ||
      line.startsWith('rename from') ||
      line.startsWith('rename to')
    ) {
      continue;
    }

    // Hunk header
    const hunkMatch = line.match(/^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/);
    if (hunkMatch) {
      oldLine = parseInt(hunkMatch[1], 10);
      newLine = parseInt(hunkMatch[2], 10);
      result.push({ kind: 'header', text: line });
      continue;
    }

    if (line.startsWith('+')) {
      result.push({ kind: 'add', text: line.slice(1), newLine: newLine++ });
    } else if (line.startsWith('-')) {
      result.push({ kind: 'remove', text: line.slice(1), oldLine: oldLine++ });
    } else {
      // Context line (starts with space or is empty)
      const text = line.startsWith(' ') ? line.slice(1) : line;
      result.push({ kind: 'context', text, oldLine: oldLine++, newLine: newLine++ });
    }
  }

  return result;
}
