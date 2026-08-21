import { useRef, useEffect, useState, useCallback } from 'react';
import './log.css';

interface LogTailProps {
  lines: string[] | null;
  emptyLabel?: string;
  className?: string;
}

export function LogTail({ lines, emptyLabel = 'No logs', className }: LogTailProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lines]);

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  }, []);

  const handleCopy = useCallback(() => {
    if (!lines?.length) return;
    navigator.clipboard.writeText(lines.join('\n')).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [lines]);

  return (
    <div className={`ga-log-tail ${className ?? ''}`}>
      <button
        type="button"
        className={`ga-log-tail-copy ${copied ? 'copied' : ''}`}
        onClick={handleCopy}
        title="Copy"
      >
        {copied ? '✓' : '⎘'}
      </button>
      <div
        ref={scrollRef}
        className="ga-log-tail-scroll"
        onScroll={handleScroll}
      >
        {lines === null ? (
          <p className="ga-log-tail-empty">…</p>
        ) : lines.length === 0 ? (
          <p className="ga-log-tail-empty">{emptyLabel}</p>
        ) : (
          <pre className="ga-log-tail-pre">
            {lines.map((line, i) => (
              <span
                key={i}
                className={line.startsWith('=====') ? 'ga-log-separator' : undefined}
              >
                {line}
                {'\n'}
              </span>
            ))}
          </pre>
        )}
      </div>
    </div>
  );
}
