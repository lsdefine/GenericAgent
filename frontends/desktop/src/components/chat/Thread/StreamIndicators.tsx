import { memo, useState, useEffect, useRef } from 'react';

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

export const ResponseLoadingIndicator = memo(function ResponseLoadingIndicator() {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  useEffect(() => {
    const id = setInterval(() => setElapsed(Date.now() - startRef.current), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div data-slot="stream-indicator">
      <span data-slot="dither-square" />
      <span data-slot="indicator-timer">{formatElapsed(elapsed)}</span>
    </div>
  );
});

interface StallProps {
  contentLength: number;
}

export const StreamStallIndicator = memo(function StreamStallIndicator({ contentLength }: StallProps) {
  const [show, setShow] = useState(false);
  const [stallElapsed, setStallElapsed] = useState(0);
  const lastLengthRef = useRef(contentLength);
  const lastChangeRef = useRef(Date.now());
  const stallStartRef = useRef<number | null>(null);

  useEffect(() => {
    if (contentLength !== lastLengthRef.current) {
      lastLengthRef.current = contentLength;
      lastChangeRef.current = Date.now();
      stallStartRef.current = null;
      setShow(false);
      setStallElapsed(0);
    }
  }, [contentLength]);

  useEffect(() => {
    const id = setInterval(() => {
      const sinceChange = Date.now() - lastChangeRef.current;
      if (sinceChange >= 2000) {
        if (!stallStartRef.current) stallStartRef.current = lastChangeRef.current + 2000;
        setShow(true);
        setStallElapsed(Date.now() - stallStartRef.current);
      }
    }, 500);
    return () => clearInterval(id);
  }, []);

  if (!show) return null;

  return (
    <div data-slot="stream-indicator" data-stall>
      <span data-slot="dither-square" />
      <span data-slot="indicator-timer">+{formatElapsed(stallElapsed)}</span>
    </div>
  );
});
