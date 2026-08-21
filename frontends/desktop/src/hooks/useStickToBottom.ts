import { useRef, useState, useCallback, useEffect } from 'react';

const BOTTOM_THRESHOLD = 24;

export function useStickToBottom() {
  const scrollRef = useRef<HTMLDivElement>(null!);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const stickingRef = useRef(true);
  const rafRef = useRef<number>(0);

  const checkBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < BOTTOM_THRESHOLD;
    setIsAtBottom(atBottom);
    stickingRef.current = atBottom;
  }, []);

  const scrollToBottom = useCallback((behavior: 'instant' | 'smooth' = 'instant') => {
    const el = scrollRef.current;
    if (!el) return;
    if (behavior === 'instant') {
      el.scrollTop = el.scrollHeight;
    } else {
      jumpScroll(el, el.scrollHeight - el.clientHeight, 170);
    }
    stickingRef.current = true;
    setIsAtBottom(true);
  }, []);

  const stopScroll = useCallback(() => {
    stickingRef.current = false;
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = () => checkBottom();

    const observer = new MutationObserver(() => {
      if (stickingRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = requestAnimationFrame(() => {
          el.scrollTop = el.scrollHeight;
        });
      }
    });

    el.addEventListener('scroll', onScroll, { passive: true });
    observer.observe(el, { childList: true, subtree: true, characterData: true });

    return () => {
      el.removeEventListener('scroll', onScroll);
      observer.disconnect();
      cancelAnimationFrame(rafRef.current);
    };
  }, [checkBottom]);

  return { scrollRef, isAtBottom, scrollToBottom, stopScroll };
}

function jumpScroll(el: HTMLElement, targetTop: number, duration: number) {
  const start = el.scrollTop;
  const diff = targetTop - start;
  const startTime = performance.now();

  function step(now: number) {
    const elapsed = now - startTime;
    const t = Math.min(elapsed / duration, 1);
    const ease = 1 - Math.pow(1 - t, 3);
    el.scrollTop = start + diff * ease;
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

export function useSessionScrollStability(
  scrollRef: React.RefObject<HTMLDivElement>,
  scrollToBottom: (b?: 'instant') => void,
  stopScroll: () => void,
  sessionKey: string | null,
) {
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !sessionKey) return;

    stopScroll();
    el.scrollTop = el.scrollHeight;

    let stableFrames = 0;
    let lastHeight = el.scrollHeight;
    let frame = 0;

    function check() {
      if (!el) return;
      frame++;
      if (el.scrollHeight === lastHeight) {
        stableFrames++;
      } else {
        stableFrames = 0;
        lastHeight = el.scrollHeight;
        el.scrollTop = el.scrollHeight;
      }
      if (stableFrames >= 5 || frame >= 90) {
        scrollToBottom('instant');
        return;
      }
      requestAnimationFrame(check);
    }
    requestAnimationFrame(check);
  }, [sessionKey, scrollRef, scrollToBottom, stopScroll]);
}
