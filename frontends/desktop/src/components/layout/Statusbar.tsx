import { useState, useCallback, type ReactNode } from 'react';
import { useChatStore } from '../../stores/chat';
import { useConductorStore } from '../../stores/conductor';
import { useI18n } from '../../i18n';
import { useBridgeStatus } from '../../hooks/useBridgeStatus';
import { LiveDuration } from './LiveDuration';
import { BridgeMenuPanel } from './BridgeMenuPanel';
import { ConductorMenuPanel } from './ConductorMenuPanel';

type Variant = 'action' | 'text' | 'menu' | 'link';

interface StatusItemProps {
  variant?: Variant;
  icon?: ReactNode;
  label: string;
  detail?: ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  href?: string;
}

function StatusItem({ variant = 'text', icon, label, detail, disabled, onClick, href }: StatusItemProps) {
  const cls = `ga-statusbar-item ${variant}${disabled ? ' disabled' : ''}`;

  const content = (
    <>
      {icon && <span className="ga-statusbar-icon">{icon}</span>}
      <span className="ga-statusbar-label">{label}</span>
      {detail && <span className="ga-statusbar-detail">{detail}</span>}
    </>
  );

  if (variant === 'link' && href) {
    return <a className={cls} href={href} target="_blank" rel="noopener noreferrer">{content}</a>;
  }

  if (variant === 'action' || variant === 'menu') {
    return <button type="button" className={cls} onClick={onClick} disabled={disabled}>{content}</button>;
  }

  return <span className={cls}>{content}</span>;
}

type DotStatus = 'ready' | 'connecting' | 'offline' | 'error' | 'degraded';

function DotIcon({ status }: { status: DotStatus }) {
  const colorMap: Record<DotStatus, string> = {
    ready: 'var(--ui-accent)',
    connecting: 'var(--semi-color-warning, #f59e0b)',
    degraded: 'var(--semi-color-warning, #f59e0b)',
    offline: 'var(--ui-text-quaternary)',
    error: 'var(--ui-text-quaternary)',
  };
  const pulse = status === 'connecting';

  return (
    <svg
      width="8"
      height="8"
      viewBox="0 0 8 8"
      fill="none"
      className={pulse ? 'ga-statusbar-dot--pulse' : undefined}
    >
      <circle cx="4" cy="4" r="3" fill={colorMap[status]} />
    </svg>
  );
}

function SpinnerIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" className="ga-statusbar-spinner">
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" strokeDasharray="28 10" strokeLinecap="round" />
    </svg>
  );
}

export function Statusbar() {
  const { t } = useI18n();
  const chatStatus = useChatStore((s) => s.status);
  const turnStartedAt = useChatStore((s) => s.turnStartedAt);
  const [panelOpen, setPanelOpen] = useState(false);
  const [conductorPanelOpen, setConductorPanelOpen] = useState(false);

  const bridgeStatus = useBridgeStatus();
  const conductorStatus = useConductorStore((s) => s.connectionStatus);

  const togglePanel = useCallback(() => { setPanelOpen((v) => !v); setConductorPanelOpen(false); }, []);
  const closePanel = useCallback(() => setPanelOpen(false), []);
  const toggleConductorPanel = useCallback(() => { setConductorPanelOpen((v) => !v); setPanelOpen(false); }, []);
  const closeConductorPanel = useCallback(() => setConductorPanelOpen(false), []);

  // Bridge dot: sole source of truth is WS channel health — NOT service-level errors.
  const bridgeDot: DotStatus = bridgeStatus === 'ready' ? 'ready'
    : bridgeStatus === 'connecting' ? 'connecting'
    : 'offline';
  const bridgeDetail = bridgeStatus === 'ready' ? undefined
    : bridgeStatus === 'connecting' ? t('bridge.connecting') : t('bridge.offline');

  // Conductor dot: sole source of truth is conductor WS connection state.
  const conductorDot: DotStatus = conductorStatus === 'ready' ? 'ready'
    : conductorStatus === 'error' ? 'error'
    : conductorStatus === 'connecting' ? 'connecting'
    : 'offline';
  const conductorDetail = conductorStatus === 'ready' ? undefined
    : conductorStatus === 'connecting' ? t('bridge.connecting')
    : conductorStatus === 'error' ? t('bridge.inferenceError')
    : t('bridge.offline');

  return (
    <footer className="ga-statusbar">
      <div className="ga-statusbar-group">
        <div className="ga-statusbar-menu-anchor">
          <StatusItem
            variant="menu"
            icon={<DotIcon status={bridgeDot} />}
            label="Bridge"
            detail={bridgeDetail}
            onClick={togglePanel}
          />
          {panelOpen && <BridgeMenuPanel onClose={closePanel} />}
        </div>
        <div className="ga-statusbar-menu-anchor">
          <StatusItem
            variant="menu"
            icon={<DotIcon status={conductorDot} />}
            label="Conductor"
            detail={conductorDetail}
            onClick={toggleConductorPanel}
          />
          {conductorPanelOpen && <ConductorMenuPanel onClose={closeConductorPanel} />}
        </div>
      </div>
      <div className="ga-statusbar-group">
        {chatStatus === 'running' && turnStartedAt && (
          <StatusItem
            icon={<SpinnerIcon />}
            label="Turn"
            detail={<LiveDuration since={turnStartedAt} />}
          />
        )}
        <StatusItem label="v0.1.0" />
      </div>
    </footer>
  );
}
