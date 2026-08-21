import { useEffect, useState, useCallback } from 'react';
import { useConductorStore } from '../../stores/conductor';
import { CollabMessageList } from './CollabMessageList';
import { CollabComposer } from './CollabComposer';
import { CollabWelcome } from './CollabWelcome';
import { WorkerRail } from './WorkerRail';
import { WorkerPanel } from './WorkerPanel';
import { useI18n } from '../../i18n';
import './collab.css';

export function CollabPage() {
  const { t } = useI18n();
  const connectionStatus = useConductorStore((s) => s.connectionStatus);
  const messages = useConductorStore((s) => s.messages);
  const connect = useConductorStore((s) => s.connect);
  const sendMessage = useConductorStore((s) => s.sendMessage);
  const [panelOpen, setPanelOpen] = useState(true);

  useEffect(() => {
    connect();
  }, [connect]);

  const handleChipClick = useCallback((text: string) => {
    sendMessage(text);
  }, [sendMessage]);

  if (connectionStatus === 'offline') {
    return (
      <div className="collab-page" data-slot="collab-page">
        <div className="collab-offline">
          <div className="collab-offline-icon">⚡</div>
          <h3>{t('collab.offlineTitle')}</h3>
          <p>{t('collab.offlineSub')}</p>
          <button className="collab-retry-btn" onClick={connect}>
            {t('collab.retry')}
          </button>
        </div>
      </div>
    );
  }

  const isEmpty = connectionStatus === 'ready' && messages.length === 0;

  return (
    <div className="collab-page" data-slot="collab-page" data-empty={isEmpty || undefined}>
      <div className="collab-main">
        <WorkerRail />
        <div className="collab-chat-area">
          {isEmpty ? <CollabWelcome onChipClick={handleChipClick} /> : <CollabMessageList />}
          <CollabComposer />
        </div>
      </div>
      <WorkerPanel collapsed={!panelOpen} onToggle={() => setPanelOpen((o) => !o)} />
    </div>
  );
}
