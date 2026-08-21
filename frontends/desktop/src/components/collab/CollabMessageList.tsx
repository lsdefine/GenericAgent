import { useRef, useState, useCallback, useLayoutEffect, useEffect } from 'react';
import { useConductorStore, type ConductorMessage } from '../../stores/conductor';
import { MarkdownPart } from '../chat/Thread/parts/MarkdownPart';
import { useStickToBottom } from '../../hooks/useStickToBottom';
import { LiveDuration } from '../layout/LiveDuration';
import { useI18n } from '../../i18n';
import '../chat/Thread/thread.css';

const RENDER_BUDGET = 200;

function MessageBubble({ message }: { message: ConductorMessage }) {
  const isUser = message.role === 'user';
  const isConductor = message.role === 'conductor';

  return (
    <div className={`collab-msg collab-msg--${message.role}`} data-slot="collab-msg">
      <div className={`collab-bubble ${isUser ? 'collab-bubble--user' : isConductor ? 'collab-bubble--conductor' : 'collab-bubble--system'}`}>
        {message.images && message.images.length > 0 && (
          <div className="collab-msg-images">
            {message.images.map((img, i) => (
              <img key={i} src={img.base64 || img.path} alt={img.name} className="collab-msg-img" />
            ))}
          </div>
        )}
        {message.files && message.files.length > 0 && (
          <div className="collab-msg-files">
            {message.files.map((f, i) => (
              <span key={i} className="collab-msg-file-chip">{f.name}</span>
            ))}
          </div>
        )}
        {isConductor || message.role === 'system' ? (
          <MarkdownPart content={message.msg} />
        ) : (
          <span className="collab-msg-text">{message.msg}</span>
        )}
      </div>
    </div>
  );
}

function TypingIndicator({ since }: { since: number }) {
  const { t } = useI18n();
  return (
    <div className="collab-msg collab-msg--conductor" data-slot="collab-typing">
      <div className="collab-thinking-bar">
        <span className="collab-thinking-dot" />
        <span className="collab-thinking-label">{t('collab.typing')}</span>
        <span className="collab-thinking-time"><LiveDuration since={since} /></span>
      </div>
    </div>
  );
}

export function CollabMessageList() {
  const messages = useConductorStore((s) => s.messages);
  const conductorTyping = useConductorStore((s) => s.conductorTyping);
  const connectionStatus = useConductorStore((s) => s.connectionStatus);
  const { t } = useI18n();
  const { scrollRef } = useStickToBottom();

  // --- Render budget state ---
  const [budgetMultiplier, setBudgetMultiplier] = useState(1);
  const scrollDistanceFromBottomRef = useRef<number | null>(null);
  const prevCutoffRef = useRef(0);

  // Reset budget when reconnecting or messages cleared
  useEffect(() => {
    if (connectionStatus === 'connecting' || messages.length === 0) {
      setBudgetMultiplier(1);
    }
  }, [connectionStatus, messages.length]);

  // Compute cutoff
  const budget = RENDER_BUDGET * budgetMultiplier;
  const cutoffIndex = Math.max(0, messages.length - budget);
  const visibleMessages = messages.slice(cutoffIndex);
  const hiddenCount = cutoffIndex;

  // Show Earlier handler — save scroll position before expanding
  const handleShowEarlier = useCallback(() => {
    const el = scrollRef.current;
    if (el) {
      scrollDistanceFromBottomRef.current = el.scrollHeight - el.scrollTop;
    }
    setBudgetMultiplier((m) => m + 1);
  }, [scrollRef]);

  // Scroll-position restore after expanding earlier messages
  useLayoutEffect(() => {
    if (scrollDistanceFromBottomRef.current == null) return;
    if (cutoffIndex >= prevCutoffRef.current) {
      // Budget didn't actually reveal more messages (or shrunk), skip restore
      scrollDistanceFromBottomRef.current = null;
      prevCutoffRef.current = cutoffIndex;
      return;
    }
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight - scrollDistanceFromBottomRef.current;
    }
    scrollDistanceFromBottomRef.current = null;
    prevCutoffRef.current = cutoffIndex;
  }, [cutoffIndex, scrollRef]);

  // Keep prevCutoffRef in sync when cutoff changes for other reasons
  useEffect(() => {
    prevCutoffRef.current = cutoffIndex;
  }, [cutoffIndex]);

  // Derive thinking start from the latest user message timestamp
  // ts may be in seconds (local: Date.now()/1000) or ms (some backends)
  const lastUserMsg = [...messages].reverse().find((m) => m.role === 'user');
  const tsToMs = (ts: number) => ts > 1e12 ? ts : ts * 1000;
  const thinkingSinceRef = useRef(Date.now());
  if (lastUserMsg?.ts) {
    thinkingSinceRef.current = tsToMs(lastUserMsg.ts);
  }

  if (connectionStatus === 'connecting') {
    return (
      <div className="collab-messages-area" data-slot="collab-messages">
        <div className="collab-connecting">
          <span className="collab-connecting-dot" />
          <span>{t('status.connecting')}</span>
        </div>
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="collab-messages-area" data-slot="collab-messages">
        <div className="collab-empty">
          <p>{t('collab.placeholder')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="collab-messages-area" data-slot="collab-messages" ref={scrollRef}>
      <div className="collab-messages-scroll">
        {hiddenCount > 0 && (
          <button
            type="button"
            data-slot="show-earlier-btn"
            onClick={handleShowEarlier}
          >
            Show {hiddenCount} earlier
          </button>
        )}
        {visibleMessages.map((msg, i) => (
          <MessageBubble key={msg.id || (cutoffIndex + i)} message={msg} />
        ))}
        {conductorTyping && <TypingIndicator since={thinkingSinceRef.current} />}
      </div>
    </div>
  );
}
