import { memo, useCallback, useLayoutEffect, useRef, useState } from 'react';
import { resolveLanguage, exceedsHighlightBudget, highlightCode } from '../../../../lib/prism-setup';
import './CodeBlock.css';

interface Props {
  language?: string;
  code: string;
  isStreaming: boolean;
}

export const CodeBlock = memo(function CodeBlock({ language: rawLang, code, isStreaming }: Props) {
  const lang = rawLang ? resolveLanguage(rawLang) : 'plaintext';
  const displayLang = rawLang || '';
  const shouldHighlight = !isStreaming && lang !== 'plaintext' && !exceedsHighlightBudget(code);

  const bodyRef = useRef<HTMLDivElement>(null);
  const [overflowing, setOverflowing] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const measure = () => setOverflowing(el.scrollHeight > 121);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div data-slot="code-card" data-streaming={isStreaming || undefined}>
      <div data-slot="code-card-header">
        {displayLang && <span data-slot="code-card-lang">{displayLang}</span>}
        <CopyButton text={code} />
      </div>
      <div data-slot="code-card-body" ref={bodyRef} data-expanded={expanded || undefined}>
        {shouldHighlight ? (
          <code dangerouslySetInnerHTML={{ __html: highlightCode(code, lang) }} />
        ) : (
          <code>{code}</code>
        )}
      </div>
      {overflowing && (
        <button
          data-slot="code-card-expand"
          aria-expanded={expanded}
          aria-label={expanded ? 'Collapse' : 'Expand'}
          onClick={() => setExpanded(v => !v)}
        >
          <svg viewBox="0 0 16 16" fill="none">
            <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
    </div>
  );
});

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  if (typeof navigator === 'undefined' || !navigator.clipboard) return null;

  return (
    <button data-slot="code-card-copy" onClick={handleCopy} title={copied ? 'Copied' : 'Copy'}>
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <rect x="5.5" y="5.5" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.2" />
          <path d="M3.5 10.5v-7a1 1 0 011-1h7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
      )}
    </button>
  );
}
