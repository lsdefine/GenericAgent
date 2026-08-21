/**
 * Composer Rich Editor — DOM utilities for contentEditable input.
 * Not a React component. Pure DOM manipulation functions.
 */

// ═══ DOM → PlainText round-trip ═══

export function composerPlainText(el: HTMLElement): string {
  let text = '';
  for (const node of el.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) {
      text += node.textContent || '';
    } else if (node instanceof HTMLElement) {
      if (node.dataset.refText) {
        text += node.dataset.refText;
      } else if (node.tagName === 'BR') {
        text += '\n';
      } else {
        const inner = composerPlainText(node);
        if (inner) text += '\n' + inner;
      }
    }
  }
  return text;
}

// ═══ DOM Normalization ═══

export function normalizeComposerDom(el: HTMLElement): void {
  const children = Array.from(el.childNodes);
  for (const child of children) {
    if (child instanceof HTMLElement) {
      if (child.dataset.refText) continue;
      if (child.tagName === 'BR') continue;
      // Unwrap browser-inserted divs/paragraphs: move their children up
      if (child.tagName === 'DIV' || child.tagName === 'P') {
        const br = document.createElement('br');
        el.insertBefore(br, child);
        while (child.firstChild) {
          el.insertBefore(child.firstChild, child);
        }
        el.removeChild(child);
      }
    }
  }
  // Merge adjacent text nodes
  el.normalize();
}

// ═══ Caret Utils ═══

export function placeCaretEnd(el: HTMLElement): void {
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  const sel = window.getSelection();
  if (sel) {
    sel.removeAllRanges();
    sel.addRange(range);
  }
}

export function placeCaretAt(el: HTMLElement, offset: number): void {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let pos = 0;
  let node: Text | null = null;
  while (walker.nextNode()) {
    node = walker.currentNode as Text;
    const len = node.textContent?.length || 0;
    if (pos + len >= offset) {
      const range = document.createRange();
      range.setStart(node, offset - pos);
      range.collapse(true);
      const sel = window.getSelection();
      if (sel) { sel.removeAllRanges(); sel.addRange(range); }
      return;
    }
    pos += len;
  }
  placeCaretEnd(el);
}

export function getCaretOffset(el: HTMLElement): number {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return 0;
  const range = sel.getRangeAt(0).cloneRange();
  range.selectNodeContents(el);
  range.setEnd(sel.getRangeAt(0).startContainer, sel.getRangeAt(0).startOffset);
  return range.toString().length;
}

// ═══ Insert at Caret ═══

export function insertAtCaret(el: HTMLElement, node: Node): void {
  el.focus();
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) {
    el.appendChild(node);
    return;
  }
  const range = sel.getRangeAt(0);
  range.deleteContents();
  range.insertNode(node);
  // Move caret after inserted node
  range.setStartAfter(node);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

export function replaceAllContent(el: HTMLElement, text: string): void {
  el.textContent = text;
  placeCaretEnd(el);
}

// ═══ Chip Creation ═══

export function refChipElement(kind: string, value: string, label?: string): HTMLSpanElement {
  const chip = document.createElement('span');
  chip.contentEditable = 'false';
  chip.dataset.refText = `@${kind}:\`${value}\``;
  chip.dataset.refKind = kind;
  chip.className = 'ref-chip';
  chip.innerHTML = `<span class="ref-chip-icon">${kindIconSvg(kind)}</span><span class="ref-chip-label">${escapeHtml(label || value)}</span>`;
  return chip;
}

export function insertChipWithSpace(el: HTMLElement, kind: string, value: string, label?: string): void {
  const chip = refChipElement(kind, value, label);
  insertAtCaret(el, chip);
  // Insert a trailing space so caret doesn't get stuck
  const space = document.createTextNode(' ');
  insertAtCaret(el, space);
}

// ═══ Skill Chip ═══

export function skillChipElement(id: string, prompt: string): HTMLSpanElement {
  const chip = document.createElement('span');
  chip.contentEditable = 'false';
  chip.dataset.refText = prompt;
  chip.dataset.skillId = id;
  chip.className = 'skill-chip';
  chip.textContent = `/${id}`;
  return chip;
}

export function replaceWithSkillChip(el: HTMLElement, id: string, prompt: string): void {
  el.textContent = '';
  const chip = skillChipElement(id, prompt);
  el.appendChild(chip);
  const space = document.createTextNode(' ');
  el.appendChild(space);
  placeCaretEnd(el);
}

// ═══ Value Quoting ═══

export function quoteRefValue(value: string): string {
  if (!value.includes('`')) return `\`${value}\``;
  if (!value.includes('"')) return `"${value}"`;
  if (!value.includes("'")) return `'${value}'`;
  return `\`${value.replace(/`/g, '\\`')}\``;
}

// ═══ REF_RE ═══

export const REF_RE = /@(file|url|image):(`[^`\n]+`|"[^"\n]+"|'[^'\n]+'|\S+)/g;

// ═══ Helpers ═══

export function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function kindIconSvg(kind: string): string {
  switch (kind) {
    case 'file':
      return '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M4 2h5l4 4v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" stroke="currentColor" stroke-width="1.2"/><path d="M9 2v4h4" stroke="currentColor" stroke-width="1.2"/></svg>';
    case 'url':
      return '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M6.5 9.5l3-3M7 11l-1.5 1.5a2.12 2.12 0 1 1-3-3L4 8m5-3l1.5-1.5a2.12 2.12 0 1 1 3 3L12 8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>';
    case 'image':
      return '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><rect x="2" y="2" width="12" height="12" rx="1" stroke="currentColor" stroke-width="1.2"/><circle cx="5.5" cy="5.5" r="1" fill="currentColor"/><path d="M2 11l3-3 2 2 3-3 4 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>';
    default:
      return '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="5" stroke="currentColor" stroke-width="1.2"/></svg>';
  }
}
