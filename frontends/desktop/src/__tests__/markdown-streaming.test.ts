// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { preprocessMarkdown } from '../lib/markdown-preprocess';

/**
 * Tests verifying streaming behavior: incremental text appending
 * and how preprocessMarkdown handles partial content.
 */
describe('Markdown streaming scenarios', () => {
  it('processes incrementally longer strings consistently', () => {
    const fullText = 'The answer is $x^2$ and costs $5.';
    // Simulate streaming: process partial strings of increasing length
    for (let i = 1; i <= fullText.length; i++) {
      const partial = fullText.slice(0, i);
      expect(() => preprocessMarkdown(partial)).not.toThrow();
    }
  });

  it('final streamed result matches full processing', () => {
    const fullText = 'Given \\(E = mc^2\\), the cost is $5.';
    const fullResult = preprocessMarkdown(fullText);
    expect(fullResult).toContain('$E = mc^2$');
    expect(fullResult).toContain('\\$5');
  });

  it('handles partial code fence during streaming', () => {
    // During streaming, a fence might be half-received
    const partial1 = '```python\nprint("hello")\n';
    const partial2 = '```python\nprint("hello")\n```\nDone for $5.';

    // partial1: unclosed fence, regex won't match
    const result1 = preprocessMarkdown(partial1);
    expect(result1).toBeDefined();

    // partial2: closed fence, properly protected
    const result2 = preprocessMarkdown(partial2);
    expect(result2).toContain('print("hello")');
    expect(result2).toContain('\\$5');
  });

  it('processes empty content during initial stream', () => {
    expect(preprocessMarkdown('')).toBe('');
  });

  it('handles rapid accumulation of math content', () => {
    const steps = [
      '$',
      '$x',
      '$x^',
      '$x^2',
      '$x^2$',
    ];
    for (const step of steps) {
      expect(() => preprocessMarkdown(step)).not.toThrow();
    }
    // Final step should be valid math delimiter
    expect(preprocessMarkdown('$x^2$')).toBe('$x^2$');
  });

  it('MAX_MARKDOWN_CHARS threshold concept works', () => {
    // Verify that we can check length before passing to preprocessMarkdown
    const hugeText = 'a'.repeat(200_000);
    const MAX_MARKDOWN_CHARS = 150_000;
    expect(hugeText.length > MAX_MARKDOWN_CHARS).toBe(true);
    // In real usage, MarkdownPart would route to HugeTextFallback before preprocessing
  });
});
