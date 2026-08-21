/**
 * Markdown preprocessing pipeline.
 *
 * Transforms raw agent text before it reaches remark-math / rehype-katex,
 * eliminating false-positive math triggers (currency dollars, code fences)
 * and normalising LaTeX bracket delimiters.
 *
 * Pipeline order:
 *   scrubBacktickNoise → normalizeFenceBlocks → stripEmptyFenceBlocks
 *   → (split by fence) → per-prose-segment: escapeCurrencyDollars + rewriteLatexBracketDelimiters
 */

// ---------------------------------------------------------------------------
// Regex constants
// ---------------------------------------------------------------------------

// Matches a complete fenced code block (``` or ~~~) including its content.
const CODE_FENCE_SPLIT_RE = /((?:```|~~~)[\s\S]*?(?:```|~~~))/g;

// Matches inline code spans (single backtick, no newlines inside).
const INLINE_CODE_SPLIT_RE = /(`[^`\n]+`)/g;

// Matches a $ immediately before a digit (currency pattern like $5, $10, $1,299).
// Captures an optional preceding character to avoid matching escaped \$.
const CURRENCY_DOLLAR_RE = /(^|[^\\])\$(?=\d)/g;

// LaTeX bracket delimiters to be rewritten into $ / $$.
const LATEX_INLINE_RE = /\\\((.+?)\\\)/g;
const LATEX_DISPLAY_RE = /\\\[([\s\S]+?)\\\]/g;

// Fence line pattern: optional indent, 3+ backticks or tildes, optional info string
const FENCE_LINE_RE = /^([ \t]*)(`{3,}|~{3,})([^\n]*)$/;

// Valid language tag pattern (e.g. "python", "c++", "c#", "f#", "objective-c")
const LANG_TAG_RE = /^[a-z][a-z0-9+#.\-]{0,15}$/i;

// ---------------------------------------------------------------------------
// Helper: sanitizeLanguageTag
// ---------------------------------------------------------------------------

function sanitizeLanguageTag(tag: string): string | null {
  const cleaned = tag.toLowerCase().trim();
  return LANG_TAG_RE.test(cleaned) ? cleaned : null;
}

// ---------------------------------------------------------------------------
// Helper: isLikelyProseFence
// ---------------------------------------------------------------------------

function isLikelyProseFence(info: string): boolean {
  const lang = info.split(/\s+/, 1)[0] || '';
  return !sanitizeLanguageTag(lang);
}

// ---------------------------------------------------------------------------
// scrubBacktickNoise
// ---------------------------------------------------------------------------

/**
 * Remove orphaned triple-backtick noise produced by LLMs outside of valid
 * fenced code blocks. Protects balanced fences and dangling fences that
 * appear to contain streaming code content.
 */
export function scrubBacktickNoise(text: string): string {
  const lines = text.split('\n');
  const protected_ranges: Array<[number, number]> = [];

  // Pass 1: identify balanced fence blocks and valid dangling fences
  let i = 0;
  while (i < lines.length) {
    const openMatch = lines[i].match(FENCE_LINE_RE);
    if (!openMatch) {
      i++;
      continue;
    }

    const openChar = openMatch[2][0]; // ` or ~
    const openLen = openMatch[2].length;
    const openIndent = openMatch[1];
    const startLine = i;

    // Search for matching close fence
    let closeIdx = -1;
    for (let j = i + 1; j < lines.length; j++) {
      const closeMatch = lines[j].match(FENCE_LINE_RE);
      if (
        closeMatch &&
        closeMatch[2][0] === openChar &&
        closeMatch[2].length >= openLen &&
        closeMatch[1] === openIndent &&
        closeMatch[3].trim() === '' // close fence has no info string
      ) {
        closeIdx = j;
        break;
      }
    }

    if (closeIdx !== -1) {
      // Balanced fence — protect entire range
      protected_ranges.push([startLine, closeIdx]);
      i = closeIdx + 1;
    } else {
      // Dangling fence — protect if it has a valid lang tag and non-empty body
      const info = openMatch[3].trim();
      const lang = info.split(/\s+/, 1)[0] || '';
      const hasValidLang = sanitizeLanguageTag(lang) !== null;
      const hasBody = i + 1 < lines.length && lines.slice(i + 1).some(l => l.trim() !== '');

      if (hasValidLang && hasBody) {
        // Streaming scenario: protect from opener to end of text
        protected_ranges.push([startLine, lines.length - 1]);
        break; // nothing after a dangling fence can be processed
      }
      i++;
    }
  }

  // Pass 2: remove triple-backtick noise outside protected ranges
  function isProtected(lineIdx: number): boolean {
    return protected_ranges.some(([start, end]) => lineIdx >= start && lineIdx <= end);
  }

  const result = lines.map((line, idx) => {
    if (isProtected(idx)) return line;
    // Remove sequences of 3+ backticks
    let cleaned = line.replace(/`{3,}/g, '');
    // Remove dangling double-backtick artifacts
    cleaned = cleaned.replace(/``\s*``/g, '');
    cleaned = cleaned.replace(/``(?=[.,;:!?\s]|$)/g, '');
    return cleaned;
  });

  return result.join('\n');
}

// ---------------------------------------------------------------------------
// normalizeFenceBlocks
// ---------------------------------------------------------------------------

/**
 * Parse and normalize fenced code blocks:
 * - Strip empty fence blocks
 * - Detect prose-fences (invalid lang tag) and unwrap them
 * - Keep dangling fences with content (streaming) as code blocks
 * - Normalize language tags
 * - Preserve ```math fences for SafeMathBlock routing
 */
export function normalizeFenceBlocks(text: string): string {
  const lines = text.split('\n');
  const output: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const openMatch = lines[i].match(FENCE_LINE_RE);
    if (!openMatch) {
      output.push(lines[i]);
      i++;
      continue;
    }

    const indent = openMatch[1];
    const marker = openMatch[2];
    const openChar = marker[0];
    const openLen = marker.length;
    const info = openMatch[3].trim();

    // Search for matching close fence
    let closeIdx = -1;
    for (let j = i + 1; j < lines.length; j++) {
      const closeMatch = lines[j].match(FENCE_LINE_RE);
      if (
        closeMatch &&
        closeMatch[2][0] === openChar &&
        closeMatch[2].length >= openLen &&
        closeMatch[1] === indent &&
        closeMatch[3].trim() === ''
      ) {
        closeIdx = j;
        break;
      }
    }

    if (closeIdx !== -1) {
      // Balanced fence found
      const bodyLines = lines.slice(i + 1, closeIdx);
      const hasBody = bodyLines.some(l => l.trim() !== '');

      if (!hasBody) {
        // Empty fence block — skip entirely
        i = closeIdx + 1;
        continue;
      }

      // Check for math language tag — preserve as-is
      const langToken = info.split(/\s+/, 1)[0] || '';
      if (langToken.toLowerCase() === 'math') {
        output.push(`${indent}\`\`\`math`);
        for (const bl of bodyLines) output.push(bl);
        output.push(`${indent}\`\`\``);
        i = closeIdx + 1;
        continue;
      }

      // Check if this is a prose-fence (invalid lang tag)
      if (info && isLikelyProseFence(info)) {
        // Emit body without fence markers (treat as prose)
        for (const bl of bodyLines) output.push(bl);
        i = closeIdx + 1;
        continue;
      }

      // Valid code block — normalize language tag
      const normalizedLang = info ? sanitizeLanguageTag(langToken) : null;
      const langSuffix = normalizedLang ? normalizedLang : '';
      output.push(`${indent}\`\`\`${langSuffix}`);
      for (const bl of bodyLines) output.push(bl);
      output.push(`${indent}\`\`\``);
      i = closeIdx + 1;
    } else {
      // Dangling fence (no close found)
      const bodyLines = lines.slice(i + 1);
      const hasBody = bodyLines.some(l => l.trim() !== '');

      if (!hasBody) {
        // Empty dangling opener — skip it
        i++;
        continue;
      }

      const langToken = info.split(/\s+/, 1)[0] || '';
      const validLang = sanitizeLanguageTag(langToken);

      if (validLang || langToken.toLowerCase() === 'math') {
        // Valid streaming code block — emit opener + remaining body (no close)
        const tag = langToken.toLowerCase() === 'math' ? 'math' : validLang;
        output.push(`${indent}\`\`\`${tag}`);
        for (const bl of bodyLines) output.push(bl);
      } else if (info && isLikelyProseFence(info)) {
        // Prose fence — emit body as prose
        for (const bl of bodyLines) output.push(bl);
      } else {
        // No info string but has body — treat as generic code block (streaming)
        output.push(`${indent}\`\`\``);
        for (const bl of bodyLines) output.push(bl);
      }

      // Consumed everything to end of input
      break;
    }
  }

  return output.join('\n');
}

// ---------------------------------------------------------------------------
// stripEmptyFenceBlocks
// ---------------------------------------------------------------------------

/**
 * Final pass: strip any remaining empty fence blocks (opener + closer with
 * only whitespace between) that may have survived normalizeFenceBlocks.
 */
export function stripEmptyFenceBlocks(text: string): string {
  return text.replace(
    /(^|\n)[ \t]*(?:`{3,}|~{3,})[^\n]*\n[ \t]*\n?[ \t]*(?:`{3,}|~{3,})[ \t]*(?=\n|$)/g,
    '$1',
  );
}

// ---------------------------------------------------------------------------
// escapeCurrencyDollars
// ---------------------------------------------------------------------------

/**
 * Escape currency dollar signs so remark-math ignores them.
 * `$5` becomes `\$5`.
 */
function escapeCurrencyDollars(text: string): string {
  return text.replace(CURRENCY_DOLLAR_RE, '$1\\$');
}

// ---------------------------------------------------------------------------
// rewriteLatexBracketDelimiters
// ---------------------------------------------------------------------------

/**
 * Rewrite LaTeX bracket delimiters to standard $ / $$ delimiters.
 * `\(x\)` -> `$x$`
 * `\[x\]` -> `$$x$$`
 */
function rewriteLatexBracketDelimiters(text: string): string {
  let result = text;
  result = result.replace(LATEX_DISPLAY_RE, (_, expr) => `$$${expr}$$`);
  result = result.replace(LATEX_INLINE_RE, (_, expr) => `$${expr}$`);
  return result;
}

// ---------------------------------------------------------------------------
// preprocessMarkdown (main export)
// ---------------------------------------------------------------------------

/**
 * Main preprocessing function.
 *
 * Pipeline: scrubBacktickNoise → normalizeFenceBlocks → stripEmptyFenceBlocks
 *   → split by fences → per-prose-segment: escapeCurrencyDollars + rewriteLatexBracketDelimiters
 */
export function preprocessMarkdown(text: string): string {
  const scrubbed = scrubBacktickNoise(text);
  const normalizedFences = normalizeFenceBlocks(scrubbed);
  const strippedEmpty = stripEmptyFenceBlocks(normalizedFences);

  // Split by fenced code blocks, transform only prose segments
  return strippedEmpty
    .split(CODE_FENCE_SPLIT_RE)
    .map((segment, i) => {
      if (i % 2 === 1) return segment; // fence block — pass through
      if (!segment.trim()) return segment; // whitespace — preserve

      // Prose: split by inline code, transform plain text only
      return segment
        .split(INLINE_CODE_SPLIT_RE)
        .map((part, j) => {
          if (j % 2 === 1) return part; // inline code — pass through
          return rewriteLatexBracketDelimiters(escapeCurrencyDollars(part));
        })
        .join('');
    })
    .join('');
}
