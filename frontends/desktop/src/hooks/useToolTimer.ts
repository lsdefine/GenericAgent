import { useState, useEffect, useRef } from 'react';

const timings = new Map<string, { start: number; end?: number }>();

function formatDuration(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

export function useToolTimer(
  segmentKey: string,
  inFlight: boolean,
): { elapsed: string | null; duration: string | null } {
  const [, forceUpdate] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let entry = timings.get(segmentKey);

    if (inFlight && !entry) {
      entry = { start: Date.now() };
      timings.set(segmentKey, entry);
    }

    if (!inFlight && entry && !entry.end) {
      entry.end = Date.now();
    }

    if (inFlight && !intervalRef.current) {
      intervalRef.current = setInterval(() => forceUpdate((n) => n + 1), 1000);
    }

    return () => {
      if (!inFlight && intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [segmentKey, inFlight]);

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const entry = timings.get(segmentKey);
  if (!entry) return { elapsed: null, duration: null };

  if (inFlight) {
    const ms = Date.now() - entry.start;
    return { elapsed: formatDuration(ms), duration: null };
  }

  if (entry.end) {
    const ms = entry.end - entry.start;
    if (ms < 1000) return { elapsed: null, duration: null };
    return { elapsed: null, duration: formatDuration(ms) };
  }

  return { elapsed: null, duration: null };
}
