// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from 'vitest';
import { composerPlainText, normalizeComposerDom } from '../components/chat/Composer/rich-editor';

describe('composerPlainText', () => {
  let el: HTMLDivElement;

  beforeEach(() => {
    el = document.createElement('div');
  });

  it('extracts plain text from text nodes', () => {
    el.textContent = 'Hello world';
    expect(composerPlainText(el)).toBe('Hello world');
  });

  it('extracts data-ref-text from skill chips', () => {
    const chip = document.createElement('span');
    chip.className = 'skill-chip';
    chip.contentEditable = 'false';
    chip.dataset.refText = 'Enter Plan mode: full prompt here';
    chip.textContent = '/plan';
    el.appendChild(chip);
    expect(composerPlainText(el)).toBe('Enter Plan mode: full prompt here');
  });

  it('handles BR as newline', () => {
    el.appendChild(document.createTextNode('Line 1'));
    el.appendChild(document.createElement('br'));
    el.appendChild(document.createTextNode('Line 2'));
    expect(composerPlainText(el)).toBe('Line 1\nLine 2');
  });

  it('handles mixed content: text + chip + text', () => {
    el.appendChild(document.createTextNode('Before '));
    const chip = document.createElement('span');
    chip.dataset.refText = '@file:`/tmp/x.ts`';
    chip.textContent = '@x.ts';
    el.appendChild(chip);
    el.appendChild(document.createTextNode(' after'));
    expect(composerPlainText(el)).toBe('Before @file:`/tmp/x.ts` after');
  });

  it('handles nested div content with newline separator', () => {
    const div = document.createElement('div');
    div.textContent = 'Inside div';
    el.appendChild(document.createTextNode('First'));
    el.appendChild(div);
    expect(composerPlainText(el)).toBe('First\nInside div');
  });

  it('returns empty string for empty element', () => {
    expect(composerPlainText(el)).toBe('');
  });
});

describe('normalizeComposerDom', () => {
  let el: HTMLDivElement;

  beforeEach(() => {
    el = document.createElement('div');
  });

  it('unwraps browser-inserted DIVs', () => {
    const div = document.createElement('div');
    div.textContent = 'Wrapped content';
    el.appendChild(div);
    normalizeComposerDom(el);
    // After normalization: BR + text node, no div
    expect(el.querySelector('div')).toBeNull();
    expect(el.textContent).toContain('Wrapped content');
  });

  it('unwraps P tags', () => {
    const p = document.createElement('p');
    p.textContent = 'Paragraph';
    el.appendChild(p);
    normalizeComposerDom(el);
    expect(el.querySelector('p')).toBeNull();
    expect(el.textContent).toContain('Paragraph');
  });

  it('preserves ref-chip spans', () => {
    const chip = document.createElement('span');
    chip.dataset.refText = 'prompt text';
    chip.textContent = '/skill';
    el.appendChild(chip);
    normalizeComposerDom(el);
    expect(el.querySelector('[data-ref-text]')).not.toBeNull();
  });

  it('preserves BR elements', () => {
    el.appendChild(document.createElement('br'));
    normalizeComposerDom(el);
    expect(el.querySelector('br')).not.toBeNull();
  });

  it('merges adjacent text nodes via normalize()', () => {
    el.appendChild(document.createTextNode('A'));
    el.appendChild(document.createTextNode('B'));
    expect(el.childNodes.length).toBe(2);
    normalizeComposerDom(el);
    expect(el.childNodes.length).toBe(1);
    expect(el.textContent).toBe('AB');
  });
});
