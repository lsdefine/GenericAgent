// @vitest-environment node
import { describe, it, expect } from 'vitest';
import katex from 'katex';

/**
 * Tests for SafeMathBlock rendering logic.
 * We test the katex.renderToString behavior directly since the project
 * does not have @testing-library/dom installed for full RTL rendering.
 * This validates the three-tier fallback strategy used in SafeMathBlock.
 */
describe('SafeMathBlock logic', () => {
  it('renders valid LaTeX without throwing (tier 1 - strict)', () => {
    const html = katex.renderToString('x^2 + y^2 = z^2', {
      displayMode: true,
      throwOnError: true,
    });
    expect(html).toContain('katex');
  });

  it('throws on invalid command in strict mode', () => {
    expect(() => {
      katex.renderToString('\\badcommand{x}', {
        displayMode: true,
        throwOnError: true,
      });
    }).toThrow();
  });

  it('does not throw on invalid command in lenient mode (tier 2)', () => {
    const html = katex.renderToString('\\badcommand{x}', {
      displayMode: true,
      throwOnError: false,
      strict: 'ignore',
    });
    expect(html).toContain('katex');
  });

  it('renders empty expression without throwing', () => {
    const html = katex.renderToString('', {
      displayMode: true,
      throwOnError: false,
      strict: 'ignore',
    });
    expect(html).toContain('katex');
  });

  it('renders complex valid LaTeX', () => {
    const html = katex.renderToString('\\frac{1}{n} \\sum_{i=1}^{n} x_i', {
      displayMode: true,
      throwOnError: true,
    });
    expect(html).toContain('katex');
    expect(html).toContain('frac');
  });

  it('simulates full fallback chain', () => {
    const expr = '\\badcommand{x}';
    let result: string;

    // Tier 1: strict — should throw
    try {
      result = katex.renderToString(expr, {
        displayMode: true,
        throwOnError: true,
      });
    } catch {
      // Tier 2: lenient — should succeed
      try {
        result = katex.renderToString(expr, {
          displayMode: true,
          throwOnError: false,
          strict: 'ignore',
        });
      } catch {
        // Tier 3: raw fallback
        result = expr;
      }
    }

    // Should have gotten lenient result (tier 2)
    expect(result!).toContain('katex');
  });
});
