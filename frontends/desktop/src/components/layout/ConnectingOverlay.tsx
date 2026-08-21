import { useState, useEffect } from 'react';
import { Spin } from '@douyinfe/semi-ui';
import { useBridgeStatus } from '../../hooks/useBridgeStatus';
import { useBridgeEverConnected } from '../../hooks/useBridgeEverConnected';
import { useBridgeFailCount } from '../../hooks/useBridgeFailCount';
import { useI18n } from '../../i18n';
import './connectingOverlay.css';

export function ConnectingOverlay() {
  const { t } = useI18n();
  const bridgeStatus = useBridgeStatus();
  const everConnected = useBridgeEverConnected();
  const failCount = useBridgeFailCount();
  const [fadeOut, setFadeOut] = useState(false);
  const [unmount, setUnmount] = useState(false);

  const shouldShow = !everConnected && bridgeStatus !== 'ready';
  const isOffline = !everConnected && failCount >= 5;

  useEffect(() => {
    if (!shouldShow && !unmount) {
      setFadeOut(true);
      const timer = setTimeout(() => setUnmount(true), 400);
      return () => clearTimeout(timer);
    }
  }, [shouldShow, unmount]);

  if (unmount || everConnected) return null;

  if (isOffline) {
    return (
      <div className="ga-connecting-overlay">
        <div className="ga-connecting-overlay-card">
          <h2 className="ga-connecting-overlay-title">{t('bridge.offline')}</h2>
          <p className="ga-connecting-overlay-sub">
            {t('bridge.offlineHint')}
          </p>
          <button
            className="ga-connecting-overlay-retry"
            onClick={() => window.location.reload()}
          >
            {t('collab.retry')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`ga-connecting-overlay ${fadeOut ? 'ga-connecting-overlay--fade' : ''}`}>
      <div className="ga-connecting-overlay-content">
        <div className="ga-connecting-overlay-brand">GENERIC AGENT</div>
        <Spin size="large" />
        <span className="ga-connecting-overlay-text">{t('bridge.connecting')}</span>
      </div>
    </div>
  );
}
