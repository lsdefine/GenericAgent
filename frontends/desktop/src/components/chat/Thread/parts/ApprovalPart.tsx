import { memo, useState, useCallback, useEffect, useRef } from 'react';
import { useChatStore } from '../../../../stores/chat';
import './approvalPart.css';

interface Props {
  question: string;
  candidates: string[];
}

/* ─── Badge letter helper ─── */
function badgeLetter(index: number): string | null {
  return index < 26 ? String.fromCharCode(65 + index) : null; // A-Z
}

/* ─── Settled view (after user responded) ─── */
function ApprovalSettled({ question, answer }: { question: string; answer: string | null }) {
  return (
    <div data-slot="approval-card" data-settled>
      <div data-slot="approval-question">{question}</div>
      <div data-slot="approval-settled">
        {answer ? answer : <em>Skipped</em>}
      </div>
    </div>
  );
}

/* ─── Main component ─── */
export const ApprovalPart = memo(function ApprovalPart({ question, candidates }: Props) {
  const sendMessage = useChatStore((s) => s.sendMessage);

  // State
  const [selectedChoice, setSelectedChoice] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [responded, setResponded] = useState(false);
  const [respondedAnswer, setRespondedAnswer] = useState<string | null>(null);

  const otherRef = useRef<HTMLTextAreaElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  // Derived
  const pendingAnswer = selectedChoice ?? (draft.trim() || null);
  const hasCandidates = candidates.length > 0;

  /* ─── Actions ─── */
  const selectChoice = useCallback((choice: string) => {
    setSelectedChoice(choice);
    setDraft('');
  }, []);

  const submitAnswer = useCallback(async (answer: string) => {
    if (submitting || responded) return;
    setSubmitting(true);
    await sendMessage(answer);
    setRespondedAnswer(answer);
    setResponded(true);
    setSubmitting(false);
  }, [submitting, responded, sendMessage]);

  const handleSkip = useCallback(async () => {
    if (submitting || responded) return;
    setSubmitting(true);
    await sendMessage('');
    setRespondedAnswer(null);
    setResponded(true);
    setSubmitting(false);
  }, [submitting, responded, sendMessage]);

  const handleConfirm = useCallback(() => {
    if (pendingAnswer !== null) {
      submitAnswer(pendingAnswer);
    }
  }, [pendingAnswer, submitAnswer]);

  /* ─── Other textarea handlers ─── */
  const handleOtherFocus = useCallback(() => {
    setSelectedChoice(null);
  }, []);

  const handleOtherChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setDraft(e.target.value);
    setSelectedChoice(null);
  }, []);

  const handleOtherKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const trimmed = draft.trim();
      if (trimmed) {
        submitAnswer(trimmed);
      }
    }
  }, [draft, submitAnswer]);

  /* ─── Global keyboard shortcuts ─── */
  useEffect(() => {
    if (responded || submitting) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;

      const active = document.activeElement;
      if (active) {
        const tag = active.tagName.toLowerCase();
        if (tag === 'input' || tag === 'textarea' || (active as HTMLElement).isContentEditable) {
          return;
        }
      }

      const key = e.key.toLowerCase();

      // Letter key a-z
      if (key.length === 1 && key >= 'a' && key <= 'z') {
        const index = key.charCodeAt(0) - 97; // 0-25
        if (index < candidates.length) {
          e.preventDefault();
          selectChoice(candidates[index]);
        } else if (index === candidates.length) {
          // Focus "Other" textarea
          e.preventDefault();
          otherRef.current?.focus();
        }
        return;
      }

      // Enter to confirm
      if (key === 'enter' && !e.shiftKey) {
        const currentAnswer = selectedChoice ?? (draft.trim() || null);
        if (currentAnswer !== null) {
          e.preventDefault();
          submitAnswer(currentAnswer);
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [responded, submitting, candidates, selectedChoice, draft, selectChoice, submitAnswer]);

  /* ─── Render ─── */
  if (responded) {
    return <ApprovalSettled question={question} answer={respondedAnswer} />;
  }

  // Badge index for "Other" row
  const otherBadgeIndex = candidates.length;
  const otherBadge = badgeLetter(otherBadgeIndex);
  const otherActive = draft.trim().length > 0 && selectedChoice === null;

  return (
    <div data-slot="approval-card" ref={cardRef} data-submitting={submitting || undefined}>
      <div data-slot="approval-question">{question}</div>

      {hasCandidates ? (
        <div data-slot="approval-options">
          {candidates.map((c, i) => {
            const letter = badgeLetter(i);
            const isSelected = selectedChoice === c;
            return (
              <button
                key={i}
                data-slot="approval-option-row"
                data-selected={isSelected || undefined}
                disabled={submitting}
                onClick={() => selectChoice(c)}
                type="button"
              >
                {letter && (
                  <kbd data-slot="approval-badge" data-active={isSelected || undefined}>
                    {letter}
                  </kbd>
                )}
                <span>{c}</span>
              </button>
            );
          })}
          {/* Other row */}
          <div data-slot="approval-other">
            {otherBadge && (
              <kbd data-slot="approval-badge" data-active={otherActive || undefined}>
                {otherBadge}
              </kbd>
            )}
            <textarea
              ref={otherRef}
              data-slot="approval-other-input"
              placeholder="Other…"
              value={draft}
              onChange={handleOtherChange}
              onFocus={handleOtherFocus}
              onKeyDown={handleOtherKeyDown}
              disabled={submitting}
              rows={1}
            />
          </div>
        </div>
      ) : (
        /* No candidates — freeform only */
        <div data-slot="approval-options">
          <textarea
            ref={otherRef}
            data-slot="approval-other-input"
            data-fullwidth
            placeholder="Type your response…"
            value={draft}
            onChange={handleOtherChange}
            onKeyDown={handleOtherKeyDown}
            disabled={submitting}
            rows={1}
          />
        </div>
      )}

      <div data-slot="approval-actions">
        <button
          type="button"
          data-slot="approval-skip-btn"
          disabled={submitting}
          onClick={handleSkip}
        >
          Skip
        </button>
        <button
          type="button"
          data-slot="approval-confirm-btn"
          disabled={submitting || pendingAnswer === null}
          onClick={handleConfirm}
        >
          {submitting ? (
            <span data-slot="approval-spinner" />
          ) : null}
          Continue
        </button>
      </div>
    </div>
  );
});
