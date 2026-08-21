import { useEffect, type RefObject } from 'react';

const playedKeys = new Set<string>();
const MAX_KEYS = 2048;

export function useEnterAnimation(
  ref: RefObject<HTMLElement | null>,
  key: string,
  shouldPlay: boolean,
): void {
  useEffect(() => {
    if (!shouldPlay || !ref.current || playedKeys.has(key)) return;

    if (playedKeys.size >= MAX_KEYS) {
      const toDelete = Array.from(playedKeys).slice(0, MAX_KEYS / 2);
      for (const k of toDelete) playedKeys.delete(k);
    }
    playedKeys.add(key);

    ref.current.animate(
      [
        { opacity: 0, transform: 'translateY(0.375rem)' },
        { opacity: 1, transform: 'translateY(0)' },
      ],
      { duration: 180, easing: 'cubic-bezier(0.16, 1, 0.3, 1)', fill: 'both' },
    );
  }, []);
}
