import { useState, useRef, useEffect } from 'react';

const REVEAL_DRAIN_MS = 500;
const REVEAL_MAX_CHARS_PER_FRAME = 30;
const REVEAL_MIN_COMMIT_MS = 33;
const REVEAL_SNAP_THRESHOLD = 5000;

export function useSmoothReveal(fullText: string, isStreaming: boolean): string {
  const [displayed, setDisplayed] = useState(fullText);
  const shownRef = useRef(fullText);
  const lastCommitRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const fullTextRef = useRef(fullText);
  fullTextRef.current = fullText;

  useEffect(() => {
    if (!isStreaming) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      shownRef.current = fullText;
      setDisplayed(fullText);
      return;
    }

    if (!fullText.startsWith(shownRef.current)) {
      shownRef.current = fullText;
      setDisplayed(fullText);
      return;
    }

    if (fullText.length - shownRef.current.length > REVEAL_SNAP_THRESHOLD) {
      shownRef.current = fullText;
      setDisplayed(fullText);
      return;
    }

    function tick() {
      rafRef.current = null;
      const now = performance.now();
      if (now - lastCommitRef.current < REVEAL_MIN_COMMIT_MS) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }

      const target = fullTextRef.current;
      const remaining = target.length - shownRef.current.length;
      if (remaining <= 0) return;

      const framesLeft = Math.max(1, Math.ceil(REVEAL_DRAIN_MS / 16.67));
      const charsThisFrame = Math.min(
        REVEAL_MAX_CHARS_PER_FRAME,
        Math.ceil(remaining / framesLeft),
      );
      shownRef.current = target.slice(0, shownRef.current.length + charsThisFrame);
      setDisplayed(shownRef.current);
      lastCommitRef.current = now;

      if (shownRef.current.length < target.length) {
        rafRef.current = requestAnimationFrame(tick);
      }
    }

    if (shownRef.current.length < fullText.length && rafRef.current === null) {
      rafRef.current = requestAnimationFrame(tick);
    }

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [fullText, isStreaming]);

  return isStreaming ? displayed : fullText;
}
