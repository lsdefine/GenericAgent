import { useCallback } from 'react';
import type { Worker } from '../../stores/conductor';
import { useConductorStore } from '../../stores/conductor';

function relTime(ts?: number): string {
  if (!ts) return '';
  const ms = ts > 1e12 ? ts : ts * 1000;
  const sec = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (sec < 10) return 'just now';
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  return hr < 24 ? `${hr}h ago` : `${Math.floor(hr / 24)}d ago`;
}

function StatusGlyph({ status }: { status: Worker['status'] }) {
  switch (status) {
    case 'running':
      return <span className="collab-card-glyph collab-card-glyph--running" />;
    case 'reported':
      return <span className="collab-card-glyph collab-card-glyph--done">✓</span>;
    case 'paused':
      return <span className="collab-card-glyph collab-card-glyph--paused">⏸</span>;
    case 'failed':
      return <span className="collab-card-glyph collab-card-glyph--failed">!</span>;
    case 'terminated':
      return <span className="collab-card-glyph collab-card-glyph--terminated">×</span>;
  }
}

interface Props {
  worker: Worker;
  onClick: (w: Worker) => void;
}

export function WorkerCard({ worker, onClick }: Props) {
  const killWorker = useConductorStore((s) => s.killWorker);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    if (confirm(`Kill agent "${worker.title}"?`)) {
      killWorker(worker.id);
    }
  }, [worker, killWorker]);

  return (
    <article
      className={`collab-card collab-card--${worker.status}`}
      data-slot="collab-card"
      onClick={() => onClick(worker)}
      onContextMenu={handleContextMenu}
    >
      <div className="collab-card-status">
        <StatusGlyph status={worker.status} />
        <span className="collab-card-status-text">{worker.status}</span>
        {worker.updatedAt && <span className="collab-card-time">{relTime(worker.updatedAt)}</span>}
      </div>
      <div className="collab-card-title">{worker.title}</div>
      <div className="collab-card-summary">{worker.summary}</div>
    </article>
  );
}
