import { useRef, useEffect } from 'react';
import { useConductorStore } from '../../stores/conductor';
import { useAppStore } from '../../stores/app';
import { useI18n } from '../../i18n';
import { LogView } from '../log';

type StatusTone = 'good' | 'warn' | 'bad' | 'muted';

function StatusDot({ tone }: { tone: StatusTone }) {
  const colors: Record<StatusTone, string> = {
    good: 'var(--ui-accent, #0053fd)',
    warn: '#f59e0b',
    bad: '#cf2d56',
    muted: 'color-mix(in srgb, var(--ui-text-tertiary) 40%, transparent)',
  };
  return (
    <span
      aria-hidden="true"
      className={tone === 'warn' ? 'ga-statusbar-dot--pulse' : undefined}
      style={{
        display: 'inline-block',
        width: '6px',
        height: '6px',
        borderRadius: '50%',
        background: colors[tone],
        flexShrink: 0,
      }}
    />
  );
}

interface Props {
  onClose: () => void;
}

export function ConductorMenuPanel({ onClose }: Props) {
  const { t } = useI18n();
  const status = useConductorStore((s) => s.connectionStatus);
  const workers = useConductorStore((s) => s.workers);
  const messages = useConductorStore((s) => s.messages);
  const typing = useConductorStore((s) => s.conductorTyping);
  const setPage = useAppStore((s) => s.setPage);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('mousedown', onClickOutside);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onClickOutside);
      document.removeEventListener('keydown', onEsc);
    };
  }, [onClose]);

  const tone: StatusTone = status === 'ready' ? 'good'
    : status === 'connecting' ? 'warn'
    : status === 'error' ? 'bad' : 'muted';

  const statusLabel = status === 'ready' ? t('bridge.connected')
    : status === 'connecting' ? t('bridge.connecting')
    : status === 'error' ? t('bridge.inferenceError') : t('bridge.offline');

  const running = workers.filter((w) => w.status === 'running').length;
  const done = workers.filter((w) => w.status === 'reported').length;
  const failed = workers.filter((w) => w.status === 'failed').length;

  const recentMessages = messages
    .filter((m) => m.role === 'conductor' || m.role === 'system')
    .slice(-5)
    .map((m) => {
      const text = m.msg.replace(/\s+/g, ' ').trim();
      return text.length > 60 ? text.slice(0, 60) + '…' : text;
    });

  const handleOpenCollab = () => {
    onClose();
    setPage('collab');
  };

  return (
    <div ref={panelRef} className="ga-bridge-panel" data-slot="conductor-panel">
      {/* Header */}
      <div className="ga-bridge-panel-header">
        <div className="ga-bridge-panel-status-rows">
          <span className="ga-bridge-panel-row ga-bridge-panel-row--primary">
            <StatusDot tone={tone} />
            {statusLabel}
          </span>
          {typing && (
            <span className="ga-bridge-panel-row ga-bridge-panel-row--secondary">
              {t('collab.typing')}
            </span>
          )}
        </div>
        {workers.length > 0 && (
          <div className="ga-conductor-panel-stats">
            {running > 0 && <span className="ga-conductor-stat ga-conductor-stat--run">{running}</span>}
            {done > 0 && <span className="ga-conductor-stat ga-conductor-stat--done">{done}</span>}
            {failed > 0 && <span className="ga-conductor-stat ga-conductor-stat--fail">{failed}</span>}
          </div>
        )}
      </div>

      {/* Recent messages */}
      <div className="ga-bridge-panel-section">
        <div className="ga-bridge-panel-section-head">
          <div className="ga-panel-section-label">{t('bridge.recentActivity')}</div>
          <button className="ga-bridge-panel-link-btn" onClick={handleOpenCollab}>
            {t('conductor.openPage')}
          </button>
        </div>
        {recentMessages.length > 0 ? (
          <LogView className="ga-bridge-panel-log">
            {recentMessages.join('\n')}
          </LogView>
        ) : (
          <div className="ga-bridge-panel-log-empty">{t('bridge.noActivity')}</div>
        )}
      </div>
    </div>
  );
}
