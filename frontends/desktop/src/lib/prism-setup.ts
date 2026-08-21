/**
 * Prism.js setup — language imports and utility helpers.
 *
 * The vite.config.ts plugin `prismjsComponentFix` ensures that each language
 * component file receives the core `Prism` object via an injected import,
 * preventing the "Prism is not defined" error during dev pre-bundling.
 */
import Prism from 'prismjs';

// --- Order matters! Each language depends on those above it. ---
// Base languages (no deps beyond core)
import 'prismjs/components/prism-markup';
import 'prismjs/components/prism-css';
import 'prismjs/components/prism-c';
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-yaml';
import 'prismjs/components/prism-toml';
import 'prismjs/components/prism-diff';
import 'prismjs/components/prism-sql';
import 'prismjs/components/prism-rust';
import 'prismjs/components/prism-go';
import 'prismjs/components/prism-python';

// Depends on: c
import 'prismjs/components/prism-cpp';

// Depends on: (core)
import 'prismjs/components/prism-java';

// Depends on: markup (via clike → javascript chain)
import 'prismjs/components/prism-javascript';

// Depends on: javascript
import 'prismjs/components/prism-typescript';

// Depends on: markup + javascript
import 'prismjs/components/prism-jsx';

// Depends on: jsx + typescript
import 'prismjs/components/prism-tsx';

// Depends on: markup
import 'prismjs/components/prism-markdown';

const LANG_ALIASES: Record<string, string> = {
  py: 'python',
  ts: 'typescript',
  js: 'javascript',
  sh: 'bash',
  shell: 'bash',
  yml: 'yaml',
  html: 'markup',
  xml: 'markup',
  svg: 'markup',
  text: 'plaintext',
  txt: 'plaintext',
};

export function resolveLanguage(lang: string): string {
  const lower = lang.toLowerCase().trim();
  const resolved = LANG_ALIASES[lower] || lower;
  if (Prism.languages[resolved]) return resolved;
  if (Prism.languages[lower]) return lower;
  return 'plaintext';
}

export function isLanguageLoaded(lang: string): boolean {
  try {
    const resolved = resolveLanguage(lang);
    return resolved !== 'plaintext' || lang === 'plaintext' || lang === 'txt' || lang === 'text';
  } catch {
    return false;
  }
}

/** Skip highlighting for very large code blocks to avoid UI jank. */
const HIGHLIGHT_BUDGET_CHARS = 50_000;

export function exceedsHighlightBudget(code: string): boolean {
  return code.length > HIGHLIGHT_BUDGET_CHARS;
}

export function highlightCode(code: string, language: string): string {
  const grammar = Prism.languages[language];
  if (!grammar) return escapeHtml(code);
  return Prism.highlight(code, grammar, language);
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

export { Prism };
