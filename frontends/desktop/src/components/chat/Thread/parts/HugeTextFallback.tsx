import { memo, useMemo } from 'react';

interface Props {
  text: string;
}

const LINES_PER_CHUNK = 200;

/**
 * HugeTextFallback renders extremely long messages (>150K chars) as plain
 * monospace text, split into virtualized chunks with content-visibility: auto
 * to prevent browser layout thrashing.
 */
export const HugeTextFallback = memo(function HugeTextFallback({ text }: Props) {
  const chunks = useMemo(() => {
    const lines = text.split('\n');
    const result: string[] = [];
    for (let i = 0; i < lines.length; i += LINES_PER_CHUNK) {
      result.push(lines.slice(i, i + LINES_PER_CHUNK).join('\n'));
    }
    return result;
  }, [text]);

  return (
    <div data-slot="huge-text-fallback">
      {chunks.map((chunk, i) => (
        <pre
          key={i}
          style={{
            contentVisibility: 'auto',
            containIntrinsicSize: '0 400px',
            margin: 0,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontFamily: 'var(--font-mono, monospace)',
            fontSize: 'var(--font-size-code, 13px)',
            lineHeight: 1.5,
          }}
        >
          {chunk}
        </pre>
      ))}
    </div>
  );
});
