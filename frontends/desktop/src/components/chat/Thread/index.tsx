import { useCallback, useRef, useState, useEffect } from 'react';
import { useChatStore } from '../../../stores/chat';
import { useStickToBottom, useSessionScrollStability } from '../../../hooks/useStickToBottom';
import { ThreadContent } from './ThreadContent';
import { MessageList } from './MessageList';
import { UserTurnRail } from './UserTurnRail';
import './thread.css';

export function Thread() {
  const { messages, status, activeSessionId } = useChatStore();
  const { scrollRef, isAtBottom, scrollToBottom, stopScroll } = useStickToBottom();
  const [budgetMultiplier, setBudgetMultiplier] = useState(1);
  const pendingJumpRef = useRef<string | null>(null);

  useSessionScrollStability(scrollRef, scrollToBottom, stopScroll, activeSessionId);

  // Reset budget when session changes
  useEffect(() => {
    setBudgetMultiplier(1);
    pendingJumpRef.current = null;
  }, [activeSessionId]);

  // After budget expands and DOM updates, execute pending jump
  useEffect(() => {
    if (!pendingJumpRef.current) return;
    const id = pendingJumpRef.current;

    // Wait a frame for DOM to render newly expanded messages
    const raf = requestAnimationFrame(() => {
      const el = document.getElementById(`msg-${id}`);
      if (el) {
        pendingJumpRef.current = null;
        const viewport = scrollRef.current;
        if (viewport) {
          const turnPair = el.closest<HTMLElement>('[data-slot="aui_turn-pair"]');
          const scrollTarget = turnPair || el;
          viewport.scrollTop = scrollTarget.offsetTop - 12;
        }
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [budgetMultiplier, scrollRef]);

  const expandAllMessages = useCallback(() => {
    setBudgetMultiplier(Infinity);
  }, []);

  const requestJumpToCollapsed = useCallback((msgId: string) => {
    pendingJumpRef.current = msgId;
    expandAllMessages();
  }, [expandAllMessages]);

  const handleShowEarlier = useCallback(() => {
    const viewport = scrollRef.current;
    if (viewport) {
      // MessageList will restore scroll via its own layout effect
    }
    setBudgetMultiplier(m => m + 1);
  }, [scrollRef]);

  return (
    <div data-slot="thread-root">
      <div
        ref={scrollRef}
        data-slot="aui_thread-viewport"
        data-following={isAtBottom}
      >
        <ThreadContent>
          <MessageList
            messages={messages}
            isRunning={status === 'running'}
            budgetMultiplier={budgetMultiplier}
            onShowEarlier={handleShowEarlier}
            scrollRef={scrollRef}
          />
          <div data-slot="aui_composer-clearance" />
        </ThreadContent>
      </div>

      <UserTurnRail
        messages={messages}
        stopScroll={stopScroll}
        onJumpToCollapsed={requestJumpToCollapsed}
      />

      {!isAtBottom && (
        <button data-slot="scroll-to-bottom" onClick={() => scrollToBottom('smooth')}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <path d="M8 3v10m0 0l-3.5-3.5M8 13l3.5-3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
    </div>
  );
}
