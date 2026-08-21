import { useConductorStore } from '../../stores/conductor';

export function WorkerRail() {
  const workers = useConductorStore((s) => s.workers);
  const running = workers.filter((w) => w.status === 'running').length;
  const done = workers.filter((w) => w.status === 'reported').length;
  const issue = workers.filter((w) => w.status === 'failed').length;

  return (
    <div className="collab-rail" data-slot="collab-rail">
      {running > 0 && (
        <span className="collab-rail-badge collab-rail-badge--running" data-slot="collab-rail-run">
          <span className="collab-rail-dot collab-rail-dot--running" />
          <span className="collab-rail-n">{running}</span>
          <span className="collab-rail-label">active</span>
        </span>
      )}
      {done > 0 && (
        <span className="collab-rail-badge collab-rail-badge--done" data-slot="collab-rail-done">
          <span className="collab-rail-dot collab-rail-dot--done" />
          <span className="collab-rail-n">{done}</span>
          <span className="collab-rail-label">reported</span>
        </span>
      )}
      {issue > 0 && (
        <span className="collab-rail-badge collab-rail-badge--issue" data-slot="collab-rail-issue">
          <span className="collab-rail-dot collab-rail-dot--issue" />
          <span className="collab-rail-n">{issue}</span>
          <span className="collab-rail-label">failed</span>
        </span>
      )}
    </div>
  );
}
