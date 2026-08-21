import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Message } from '../../../services/chat';
import './UserTurnRail.css';

const MIN_TURNS = 3;
const MAX_PREVIEW_CHARS = 40;
const JUMP_DURATION = 170;
const SCROLL_TOP_MARGIN = 12;

interface Props {
  messages: Message[];
  stopScroll: () => void;
  onJumpToCollapsed: (msgId: string) => void;
}

interface UserTurn {
  id: string;
  content: string;
}

function previewText(content: string): string {
  const normalized = content.replace(/\s+/g, ' ').trim();
  return normalized.length <= MAX_PREVIEW_CHARS
    ? normalized
    : normalized.slice(0, MAX_PREVIEW_CHARS) + '…';
}

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

let jumpRaf = 0;

function jumpScroll(el: HTMLElement, targetTop: number, duration: number) {
  cancelAnimationFrame(jumpRaf);
  const start = el.scrollTop;
  const diff = targetTop - start;
  if (Math.abs(diff) < 1) return;
  const startTime = performance.now();

  function step(now: number) {
    const elapsed = now - startTime;
    const t = Math.min(elapsed / duration, 1);
    el.scrollTop = start + diff * easeOutCubic(t);
    if (t < 1) jumpRaf = requestAnimationFrame(step);
  }
  jumpRaf = requestAnimationFrame(step);
}

export const UserTurnRail = memo(function UserTurnRail({ messages, stopScroll, onJumpToCollapsed }: Props) {
  const userTurns: UserTurn[] = useMemo(
    () => messages
      .filter((m) => m.role === 'user')
      .map((m) => ({ id: m.id, content: m.content })),
    [messages],
  );

  const [activeId, setActiveId] = useState<string | null>(null);
  const [hovered, setHovered] = useState(false);
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrollRaf = useRef(0);

  const handleMouseEnter = useCallback(() => {
    if (leaveTimer.current) {
      clearTimeout(leaveTimer.current);
      leaveTimer.current = null;
    }
    setHovered(true);
  }, []);

  const handleMouseLeave = useCallback(() => {
    leaveTimer.current = setTimeout(() => {
      setHovered(false);
      leaveTimer.current = null;
    }, 150);
  }, []);

  // Scroll-based active tracking: find the last user message whose top is at or above viewport top.
  useEffect(() => {
    if (userTurns.length < MIN_TURNS) return;

    const viewport = document.querySelector<HTMLElement>('[data-slot="aui_thread-viewport"]');
    if (!viewport) return;

    function updateActive() {
      scrollRaf.current = 0;
      if (!viewport) return;

      const vpTop = viewport.getBoundingClientRect().top;
      let bestId: string | null = null;

      for (const turn of userTurns) {
        const el = document.getElementById(`msg-${turn.id}`);
        if (!el) continue;
        const elTop = el.getBoundingClientRect().top - vpTop;
        // Pick the last user message whose top edge is within SCROLL_TOP_MARGIN of viewport top
        if (elTop <= SCROLL_TOP_MARGIN) {
          bestId = turn.id;
        } else {
          break;
        }
      }

      // If nothing qualifies (user hasn't scrolled past any), pick the first
      if (!bestId && userTurns.length > 0) {
        bestId = userTurns[0].id;
      }

      if (bestId) setActiveId(bestId);
    }

    function onScroll() {
      if (!scrollRaf.current) {
        scrollRaf.current = requestAnimationFrame(updateActive);
      }
    }

    viewport.addEventListener('scroll', onScroll, { passive: true });
    // Initial calculation
    updateActive();

    return () => {
      viewport.removeEventListener('scroll', onScroll);
      cancelAnimationFrame(scrollRaf.current);
    };
  }, [userTurns]);

  const handleJump = useCallback((id: string) => {
    const viewport = document.querySelector<HTMLElement>('[data-slot="aui_thread-viewport"]');
    const el = document.getElementById(`msg-${id}`);

    if (!el) {
      onJumpToCollapsed(id);
      return;
    }

    if (!viewport) return;
    stopScroll();

    // Use the turn-pair container's offsetTop to avoid sticky positioning offset
    const turnPair = el.closest<HTMLElement>('[data-slot="aui_turn-pair"]');
    const scrollTarget = turnPair || el;
    const target = scrollTarget.offsetTop - SCROLL_TOP_MARGIN;
    jumpScroll(viewport, target, JUMP_DURATION);
  }, [stopScroll, onJumpToCollapsed]);

  if (userTurns.length < MIN_TURNS) return null;

  return (
    <nav
      data-slot="user-turn-rail"
      data-expanded={hovered || undefined}
      aria-label="User message navigation"
    >
      <div
        data-slot="rail-hitarea"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        <div data-slot="rail-panel" aria-hidden={!hovered}>
          {userTurns.map((turn) => (
            <button
              key={turn.id}
              data-slot="rail-panel-item"
              data-active={turn.id === activeId || undefined}
              onClick={() => handleJump(turn.id)}
            >
              {previewText(turn.content)}
            </button>
          ))}
        </div>

        <div data-slot="rail-marks">
          {userTurns.map((turn) => (
            <button
              key={turn.id}
              data-slot="rail-mark"
              data-active={turn.id === activeId || undefined}
              aria-label={previewText(turn.content)}
              onClick={() => handleJump(turn.id)}
            >
              <span data-slot="rail-mark-line" />
            </button>
          ))}
        </div>
      </div>
    </nav>
  );
});
