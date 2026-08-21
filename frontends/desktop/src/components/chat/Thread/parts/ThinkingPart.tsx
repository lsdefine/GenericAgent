import { memo, useState, useRef, useCallback, useEffect } from 'react';

interface Props {
  content: string;
  isStreaming: boolean;
}

export const ThinkingPart = memo(function ThinkingPart({ content, isStreaming }: Props) {
  const [userPinned, setUserPinned] = useState<boolean | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  const isOpen = userPinned !== null ? userPinned : isStreaming;

  const handleToggle = useCallback(() => {
    setUserPinned((prev) => {
      if (prev === null) return !isStreaming;
      return !prev;
    });
  }, [isStreaming]);

  useEffect(() => {
    if (isStreaming && isOpen && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [content, isStreaming, isOpen]);

  if (!content.trim()) return null;

  return (
    <details
      data-slot="aui_thinking-disclosure"
      open={isOpen}
      onToggle={handleToggle}
    >
      <summary data-slot="thinking-summary">
        <span className={isStreaming ? 'thinking-shimmer' : ''}>Thinking</span>
      </summary>
      <div
        ref={bodyRef}
        data-slot="thinking-body"
        data-streaming={isStreaming || undefined}
      >
        {content}
      </div>
    </details>
  );
});
