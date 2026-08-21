// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { preprocessMarkdown } from '../lib/markdown-preprocess';

describe('preprocessMarkdown', () => {
  describe('currency dollar protection', () => {
    it('escapes $5 in prose', () => {
      expect(preprocessMarkdown('costs $5')).toBe('costs \\$5');
    });

    it('escapes $10 and $1,299 in a sentence', () => {
      const input = 'The price is $10 or $1,299 total.';
      const output = preprocessMarkdown(input);
      expect(output).toContain('\\$10');
      expect(output).toContain('\\$1');
    });

    it('does not escape $ not followed by digit', () => {
      expect(preprocessMarkdown('$x^2$')).toBe('$x^2$');
    });

    it('does not double-escape already escaped \\$5', () => {
      expect(preprocessMarkdown('\\$5')).toBe('\\$5');
    });

    it('escapes currency at start of string', () => {
      expect(preprocessMarkdown('$5 is the cost')).toBe('\\$5 is the cost');
    });
  });

  describe('code fence protection', () => {
    it('does not modify $ inside fenced code blocks', () => {
      const input = '```bash\nexport PATH=$HOME/bin:$PATH\n```';
      expect(preprocessMarkdown(input)).toBe(input);
    });

    it('does not modify $ inside tilde fenced code blocks', () => {
      const input = '~~~\n$HOME\n~~~';
      const output = preprocessMarkdown(input);
      // normalizeFenceBlocks rewrites ~~~ to ``` (standard normalization)
      expect(output).toContain('$HOME');
      expect(output).not.toContain('\\$HOME');
    });

    it('processes prose outside code fences normally', () => {
      const input = 'costs $5\n```\n$HOME\n```\ncosts $10';
      const output = preprocessMarkdown(input);
      expect(output).toContain('\\$5');
      expect(output).toContain('$HOME');
      expect(output).toContain('\\$10');
    });
  });

  describe('inline code protection', () => {
    it('does not modify $ inside inline code', () => {
      const input = 'Use `$HOME` variable and $5 cost';
      const output = preprocessMarkdown(input);
      expect(output).toContain('`$HOME`');
      expect(output).toContain('\\$5');
    });

    it('does not modify $ inside inline code with path', () => {
      const input = 'Run `echo $PATH` for $3';
      const output = preprocessMarkdown(input);
      expect(output).toContain('`echo $PATH`');
      expect(output).toContain('\\$3');
    });
  });

  describe('LaTeX delimiter rewriting', () => {
    it('rewrites \\(...\\) to $...$', () => {
      expect(preprocessMarkdown('result is \\(x^2\\)')).toBe('result is $x^2$');
    });

    it('rewrites \\[...\\] to $$...$$', () => {
      expect(preprocessMarkdown('formula: \\[x^2 + y^2\\]')).toBe(
        'formula: $$x^2 + y^2$$'
      );
    });

    it('does not rewrite delimiters inside code fences', () => {
      const input = '```\n\\(x\\)\n```';
      expect(preprocessMarkdown(input)).toBe(input);
    });

    it('does not rewrite delimiters inside inline code', () => {
      const input = 'Use `\\(x\\)` for inline math';
      expect(preprocessMarkdown(input)).toBe('Use `\\(x\\)` for inline math');
    });

    it('handles multiline display math', () => {
      const input = '\\[\n  a + b\n  = c\n\\]';
      expect(preprocessMarkdown(input)).toBe('$$\n  a + b\n  = c\n$$');
    });
  });

  describe('combined scenarios', () => {
    it('handles real-world mixed content', () => {
      const input = [
        'The cost is $5 per unit.',
        '\\(E = mc^2\\) is famous.',
        '```python',
        'x = $100',
        '```',
        'Total: $3.',
      ].join('\n');
      const output = preprocessMarkdown(input);
      expect(output).toContain('\\$5');
      expect(output).toContain('$E = mc^2$');
      expect(output).toContain('x = $100'); // inside fence, unchanged
      expect(output).toContain('\\$3');
    });

    it('handles empty string', () => {
      expect(preprocessMarkdown('')).toBe('');
    });

    it('handles string with only dollars', () => {
      expect(preprocessMarkdown('$$')).toBe('$$');
    });

    it('handles lone $ without digit', () => {
      expect(preprocessMarkdown('$ ')).toBe('$ ');
    });
  });
});
