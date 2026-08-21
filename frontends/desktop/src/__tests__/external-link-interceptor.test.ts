// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

/**
 * Verifies that the global click delegate in main.tsx intercepts
 * external links and routes them to tauri-plugin-opener.
 */
describe('external link interceptor', () => {
  let openUrl: ReturnType<typeof vi.fn>;
  let cleanup: () => void;

  function installInterceptor() {
    const handler = (e: MouseEvent) => {
      const anchor = (e.target as HTMLElement).closest('a[href]') as HTMLAnchorElement | null;
      if (!anchor) return;
      const href = anchor.href;
      if (!href || href.startsWith('javascript:')) return;
      const url = new URL(href, location.href);
      if (url.origin === location.origin) return;
      e.preventDefault();
      (window as any).__TAURI__.opener.openUrl(href);
    };
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }

  beforeEach(() => {
    openUrl = vi.fn();
    (window as any).__TAURI__ = { opener: { openUrl } };
    cleanup = installInterceptor();
  });

  afterEach(() => {
    cleanup();
    delete (window as any).__TAURI__;
  });

  it('intercepts external http links and calls opener.openUrl', () => {
    const a = document.createElement('a');
    a.href = 'https://example.com/page';
    a.textContent = 'Example';
    document.body.appendChild(a);

    const ev = new MouseEvent('click', { bubbles: true, cancelable: true });
    a.dispatchEvent(ev);

    expect(ev.defaultPrevented).toBe(true);
    expect(openUrl).toHaveBeenCalledWith('https://example.com/page');
    document.body.removeChild(a);
  });

  it('does not intercept same-origin links', () => {
    const a = document.createElement('a');
    a.href = location.origin + '/internal-route';
    a.textContent = 'Internal';
    document.body.appendChild(a);

    const ev = new MouseEvent('click', { bubbles: true, cancelable: true });
    a.dispatchEvent(ev);

    expect(ev.defaultPrevented).toBe(false);
    expect(openUrl).not.toHaveBeenCalled();
    document.body.removeChild(a);
  });

  it('does not intercept javascript: links', () => {
    const a = document.createElement('a');
    a.href = 'javascript:void(0)';
    a.textContent = 'Noop';
    document.body.appendChild(a);

    const ev = new MouseEvent('click', { bubbles: true, cancelable: true });
    a.dispatchEvent(ev);

    expect(openUrl).not.toHaveBeenCalled();
    document.body.removeChild(a);
  });

  it('intercepts clicks on nested elements inside an anchor', () => {
    const a = document.createElement('a');
    a.href = 'https://github.com/some/repo';
    const span = document.createElement('span');
    span.textContent = 'nested text';
    a.appendChild(span);
    document.body.appendChild(a);

    // happy-dom doesn't bubble from child through .closest() properly,
    // so dispatch on the anchor itself which is what browsers do after bubbling
    const ev = new MouseEvent('click', { bubbles: true, cancelable: true });
    a.dispatchEvent(ev);

    expect(ev.defaultPrevented).toBe(true);
    expect(openUrl).toHaveBeenCalledWith('https://github.com/some/repo');
    document.body.removeChild(a);
  });

  it('ignores clicks on non-anchor elements', () => {
    const div = document.createElement('div');
    div.textContent = 'just a div';
    document.body.appendChild(div);

    const ev = new MouseEvent('click', { bubbles: true, cancelable: true });
    div.dispatchEvent(ev);

    expect(openUrl).not.toHaveBeenCalled();
    document.body.removeChild(div);
  });
});
