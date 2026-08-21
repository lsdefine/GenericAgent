/**
 * KaTeX LRU Memo Cache.
 *
 * Module-level singleton cache that stores rendered KaTeX HTML strings,
 * keyed by displayMode + expression value. Eliminates redundant
 * katex.renderToString calls during streaming re-renders.
 *
 * Uses a 3-level fallback strategy: strict → lenient → error span.
 */

import katex from 'katex';

// ---------------------------------------------------------------------------
// LRU Cache
// ---------------------------------------------------------------------------

const CACHE_LIMIT = 512;

class LruCache<K, V> {
  private readonly map = new Map<K, V>();

  get(key: K): V | undefined {
    const value = this.map.get(key);
    if (value === undefined) return undefined;
    // Move to end (most recently used)
    this.map.delete(key);
    this.map.set(key, value);
    return value;
  }

  set(key: K, value: V): void {
    if (this.map.has(key)) {
      this.map.delete(key);
    } else if (this.map.size >= CACHE_LIMIT) {
      // Evict oldest entry
      const oldest = this.map.keys().next().value;
      if (oldest !== undefined) this.map.delete(oldest);
    }
    this.map.set(key, value);
  }

  get size(): number {
    return this.map.size;
  }
}

const cache = new LruCache<string, string>();

function cacheKey(displayMode: boolean, value: string): string {
  return `${displayMode ? 'd' : 'i'}\x00${value}`;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface RenderMathOptions {
  errorColor?: string;
  macros?: Record<string, string>;
}

/**
 * Render KaTeX with LRU caching and 3-level fallback.
 * Returns HTML string. Caches successful renders at all levels.
 */
export function renderMathCached(
  value: string,
  displayMode: boolean,
  options: RenderMathOptions = {},
): string {
  const key = cacheKey(displayMode, value);
  const cached = cache.get(key);
  if (cached !== undefined) return cached;

  const { errorColor = 'var(--semi-color-text-2)', macros } = options;
  let html: string;

  // Level 1: strict
  try {
    html = katex.renderToString(value, { displayMode, throwOnError: true, macros });
    cache.set(key, html);
    return html;
  } catch {
    // fall through to lenient
  }

  // Level 2: lenient
  try {
    html = katex.renderToString(value, {
      displayMode,
      throwOnError: false,
      strict: 'ignore',
      errorColor,
      macros,
    });
    cache.set(key, html);
    return html;
  } catch {
    // fall through to raw fallback
  }

  // Level 3: error span with raw text
  html = `<span class="katex-error" style="color:${errorColor}" title="KaTeX parse error">${escapeHtml(value)}</span>`;
  cache.set(key, html);
  return html;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
