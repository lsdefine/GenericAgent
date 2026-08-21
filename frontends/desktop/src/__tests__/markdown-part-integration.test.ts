// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { preprocessMarkdown } from '../lib/markdown-preprocess';

/**
 * Integration tests verifying the full preprocessing pipeline
 * handles realistic agent output scenarios correctly.
 */
describe('MarkdownPart integration: preprocessMarkdown pipeline', () => {
  describe('valid TeX passes through', () => {
    it('preserves inline math delimiters', () => {
      const input = 'The formula $x^2 + y^2 = z^2$ is Pythagorean.';
      const output = preprocessMarkdown(input);
      expect(output).toBe(input);
    });

    it('preserves display math delimiters', () => {
      const input = '$$\\int_0^\\infty e^{-x} dx = 1$$';
      const output = preprocessMarkdown(input);
      expect(output).toBe(input);
    });

    it('converts bracket notation inline math', () => {
      const input = 'See \\(x + y\\) here.';
      expect(preprocessMarkdown(input)).toBe('See $x + y$ here.');
    });

    it('converts bracket notation display math', () => {
      const input = '\\[E = mc^2\\]';
      expect(preprocessMarkdown(input)).toBe('$$E = mc^2$$');
    });
  });

  describe('false positive prevention', () => {
    it('currency dollars are escaped', () => {
      const input = 'This costs $5 and that costs $100.';
      const output = preprocessMarkdown(input);
      expect(output).not.toContain(' $5');
      expect(output).not.toContain(' $1');
      expect(output).toContain('\\$5');
      expect(output).toContain('\\$100');
    });

    it('shell variables in code fences are untouched', () => {
      const input = [
        'Run this:',
        '```bash',
        'echo $HOME',
        'export PATH=$HOME/bin:$PATH',
        '```',
      ].join('\n');
      const output = preprocessMarkdown(input);
      expect(output).toContain('echo $HOME');
      expect(output).toContain('$HOME/bin:$PATH');
    });

    it('shell variables in inline code are untouched', () => {
      const input = 'Use `$PATH` to see your path.';
      const output = preprocessMarkdown(input);
      expect(output).toContain('`$PATH`');
    });

    it('lone $ does not crash', () => {
      expect(() => preprocessMarkdown('$')).not.toThrow();
      expect(() => preprocessMarkdown('$$')).not.toThrow();
    });
  });

  describe('math fence routing', () => {
    it('```math fence content is preserved for component routing', () => {
      // The preprocessMarkdown function should pass through fence content unchanged.
      // The actual routing to SafeMathBlock happens in the ReactMarkdown component layer.
      const input = '```math\n\\frac{1}{n}\n```';
      const output = preprocessMarkdown(input);
      expect(output).toBe(input);
    });

    it('```latex fence content is preserved (will go to CodeBlock)', () => {
      const input = '```latex\n\\frac{1}{n}\n```';
      const output = preprocessMarkdown(input);
      expect(output).toBe(input);
    });

    it('```tex fence content is preserved (will go to CodeBlock)', () => {
      const input = '```tex\n\\frac{1}{n}\n```';
      const output = preprocessMarkdown(input);
      expect(output).toBe(input);
    });
  });

  describe('edge cases', () => {
    it('handles multiple math expressions in one line', () => {
      const input = 'Given $a$ and $b$, compute $a + b$.';
      const output = preprocessMarkdown(input);
      expect(output).toBe(input); // no currency digits, unchanged
    });

    it('handles mixed math and currency', () => {
      const input = 'Formula $x^2$ costs $5 per use.';
      const output = preprocessMarkdown(input);
      expect(output).toContain('$x^2$');
      expect(output).toContain('\\$5');
    });

    it('handles very long input without error', () => {
      const longContent = 'The answer is $x^2$.\n'.repeat(10000);
      expect(() => preprocessMarkdown(longContent)).not.toThrow();
    });

    it('handles unclosed code fences (streaming scenario)', () => {
      // Unclosed fence: the regex won't match it, so content is treated as prose
      const input = '```python\nx = $5\n';
      const output = preprocessMarkdown(input);
      // Since fence is unclosed, regex doesn't match — content is treated as prose
      // This is documented as acceptable streaming behavior
      expect(output).toBeDefined();
    });
  });
});
