import type { Stage } from './store';
import { t, tOr } from './i18n';

interface Props {
  stages: Stage[];
  overallPct: number;
  logs: string[];
}

export function ProgressScreen({ stages, overallPct, logs }: Props) {
  return (
    <div className="bs-screen bs-progress">
      <p className="bs-text">{t('preparing')}</p>
      <div className="bs-bar-track" role="progressbar" aria-valuenow={overallPct} aria-valuemin={0} aria-valuemax={100}>
        <div className="bs-bar-fill" style={{ width: `${Math.max(0, Math.min(100, overallPct))}%` }} />
      </div>
      <ul className="bs-stages" aria-label="Bootstrap stages">
        {stages.map((s) => (
          <li key={s.key} data-state={s.state}>
            <span className="bs-stage-dot" aria-hidden="true" />
            <span className="bs-stage-label">{tOr(`stage_${s.key}`, s.key)}</span>
          </li>
        ))}
      </ul>
      {logs.length > 0 && (
        <details className="bs-log">
          <summary>{t('logTitle')}</summary>
          <pre>{logs.slice(-20).join('\n')}</pre>
        </details>
      )}
    </div>
  );
}
