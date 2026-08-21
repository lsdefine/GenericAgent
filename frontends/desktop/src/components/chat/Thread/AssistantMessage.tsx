import { memo, useCallback, useMemo, useRef } from 'react';
import type { Message } from '../../../services/chat';
import { parseAgentContent, ParsedSegment } from '../agentProtocol';
import { MessageParts } from './parts';
import { AssistantActionBar } from './AssistantActionBar';

interface Props {
  message: Message;
  isStreaming: boolean;
}

export const AssistantMessage = memo(function AssistantMessage({ message, isStreaming }: Props) {
  const segments = useMemo(() => {
    const turnSegs = message.turn_segs;
    if (turnSegs && turnSegs.length > 0) {
      return turnSegs.flatMap((seg) => parseAgentContent(seg));
    }
    return parseAgentContent(message.content);
  }, [message.content, message.turn_segs]);

  const segmentsRef = useRef<ParsedSegment[]>(segments);
  segmentsRef.current = segments;

  const getMessageText = useCallback(() => {
    const segs = segmentsRef.current;
    const texts: string[] = [];
    for (const seg of segs) {
      if (seg.type === 'prose' || seg.type === 'summary') {
        texts.push(seg.content);
      }
    }
    return texts.join('\n\n');
  }, []);

  return (
    <div
      data-slot="aui_assistant-message-root"
      data-role="assistant"
      data-streaming={isStreaming || undefined}
    >
      <MessageParts segments={segments} isStreaming={isStreaming} messageId={String(message.id)} />
      <AssistantActionBar getMessageText={getMessageText} />
    </div>
  );
});
