import { memo, useMemo } from 'react';
import { parseDiff } from '../../../../lib/parse-diff';
import './diffLines.css';

interface Props {
  code: string;
}

export const DiffLines = memo(function DiffLines({ code }: Props) {
  const lines = useMemo(() => parseDiff(code), [code]);

  return (
    <div data-slot="diff-block">
      {lines.map((line, i) => (
        <div key={i} data-slot="diff-line" data-diff-kind={line.kind}>
          {line.kind !== 'header' && (
            <span data-slot="diff-gutter">
              <span data-slot="diff-line-old">{line.oldLine ?? ''}</span>
              <span data-slot="diff-line-new">{line.newLine ?? ''}</span>
            </span>
          )}
          <span data-slot="diff-content">
            {line.kind === 'add' && <span data-slot="diff-sign">+</span>}
            {line.kind === 'remove' && <span data-slot="diff-sign">-</span>}
            {line.text}
          </span>
        </div>
      ))}
    </div>
  );
});
