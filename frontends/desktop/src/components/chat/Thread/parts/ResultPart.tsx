import { memo, useState, useRef } from 'react';
import { useEnterAnimation } from '../../../../hooks/useEnterAnimation';

interface Props {
  content: string;
  inFlight: boolean;
  segmentKey?: string;
  isStreaming?: boolean;
}

export const ResultPart = memo(function ResultPart({ content, inFlight, segmentKey = '', isStreaming = false }: Props) {
  const [expanded, setExpanded] = useState(false);
  const isLong = content.length > 200;
  const ref = useRef<HTMLDivElement>(null);
  useEnterAnimation(ref, segmentKey, isStreaming);

  return (
    <div ref={ref} data-slot="tool-block" data-tool-row data-status={inFlight ? 'running' : 'success'}>
      <div data-slot="tool-header" onClick={() => isLong && setExpanded(!expanded)}>
        <span data-slot="tool-title">{inFlight ? 'Output…' : 'Output'}</span>
        {isLong && !expanded && (
          <span data-slot="tool-duration">{content.length} chars</span>
        )}
      </div>
      {(expanded || !isLong) && (
        <pre data-slot="tool-body">{content}</pre>
      )}
    </div>
  );
});
