import { memo, useMemo, useRef, useLayoutEffect } from 'react';
import type { Message } from '../../../services/chat';
import { buildThreadGroups, type ThreadGroup } from '../../../lib/thread-grouping';
import { TurnPair } from './TurnPair';
import { UserMessage } from './UserMessage';
import { InlineError } from './InlineError';

const RENDER_BUDGET = 300;

interface Props {
  messages: Message[];
  isRunning: boolean;
  budgetMultiplier: number;
  onShowEarlier: () => void;
  scrollRef: React.RefObject<HTMLDivElement>;
}

function getGroupPartCount(group: ThreadGroup): number {
  if (group.kind === 'turn') {
    return group.turns.reduce((sum, t) => sum + t.segments.length, 0);
  }
  return 1;
}

export const MessageList = memo(function MessageList({
  messages,
  isRunning,
  budgetMultiplier,
  onShowEarlier,
  scrollRef,
}: Props) {
  const groups = useMemo(() => buildThreadGroups(messages), [messages]);
  const savedDistanceRef = useRef<number | null>(null);

  // Compute cutoff index
  const cutoffIndex = useMemo(() => {
    if (!isFinite(budgetMultiplier)) return 0;
    const totalBudget = RENDER_BUDGET * budgetMultiplier;
    let accumulated = 0;
    for (let i = groups.length - 1; i >= 0; i--) {
      accumulated += getGroupPartCount(groups[i]);
      if (accumulated > totalBudget) {
        return i + 1;
      }
    }
    return 0;
  }, [groups, budgetMultiplier]);

  const visibleGroups = useMemo(() => groups.slice(cutoffIndex), [groups, cutoffIndex]);
  const hiddenCount = cutoffIndex;

  // Scroll position restore after expanding earlier messages
  useLayoutEffect(() => {
    if (savedDistanceRef.current !== null && scrollRef?.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight - savedDistanceRef.current;
      savedDistanceRef.current = null;
    }
  });

  const handleShowEarlier = () => {
    const viewport = scrollRef?.current;
    if (viewport) {
      savedDistanceRef.current = viewport.scrollHeight - viewport.scrollTop;
    }
    onShowEarlier();
  };

  if (messages.length === 0) {
    return (
      <div data-slot="thread-empty">
        <p>Send a message to begin.</p>
      </div>
    );
  }

  return (
    <>
      {hiddenCount > 0 && (
        <button data-slot="show-earlier-btn" onClick={handleShowEarlier}>
          Show {hiddenCount} earlier messages
        </button>
      )}
      {visibleGroups.map((group, i) => {
        const globalIndex = cutoffIndex + i;
        if (group.kind === 'turn') {
          return (
            <TurnPair
              key={group.assistantMsg.id}
              userMsg={group.userMsg}
              assistantMsg={group.assistantMsg}
              isStreaming={isRunning && globalIndex === groups.length - 1}
            />
          );
        }
        if (group.msg.role === 'user') {
          return (
            <div key={group.msg.id} data-slot="aui_turn-pair">
              <UserMessage content={group.msg.content} msgId={group.msg.id} images={group.msg.images} files={group.msg.files} />
            </div>
          );
        }
        if (group.msg.role === 'error') {
          return <InlineError key={group.msg.id} error={group.msg.content} msgId={group.msg.id} />;
        }
        return (
          <div key={group.msg.id} data-slot="standalone-message" data-status={group.msg.status}>
            {group.msg.content}
          </div>
        );
      })}
    </>
  );
});
