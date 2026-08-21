import { useState, useEffect, useCallback } from 'react';
import { Button, Toast, Tooltip } from '@douyinfe/semi-ui';
import { useI18n } from '../../i18n';
import * as bridge from '../../services/bridge';
import { useChatStore } from '../../stores/chat';

type SourceState = 'idle' | 'connected' | 'switching';

function truncatePath(p: string, max = 40): string {
  if (p.length <= max) return p;
  const head = p.slice(0, 12);
  const tail = p.slice(-(max - 15));
  return `${head}…${tail}`;
}

function mapSourceError(msg: string, t: (k: string) => string): string {
  if (msg.includes('agentmain.py')) return t('data.localRepoErrNoAgent');
  if (msg.includes('not compatible') || msg.includes('compatibility probe')) {
    return t('data.localRepoErrIncompatible');
  }
  if (msg.includes('20s') || msg.includes('ready')) return t('data.localRepoErrTimeout');
  if (msg.includes('no GenericAgent source')) return t('data.localRepoErrNoResolve');
  return t('data.localRepoSwitchFailed');
}

export function GaSourceBlock() {
  const { t } = useI18n();
  const [state, setState] = useState<SourceState>('idle');
  const [sourcePath, setSourcePath] = useState<string | null>(null);

  useEffect(() => {
    bridge.tauriInvoke('get_ga_source', {}).then((path) => {
      if (path) {
        setState('connected');
        setSourcePath(path as string);
      }
    }).catch(() => {});
  }, []);

  const refreshSessions = useCallback(() => {
    useChatStore.getState().loadSessions();
  }, []);

  const handlePick = useCallback(async () => {
    try {
      const picked = await bridge.tauriInvoke('pick_directory', {}) as string | null;
      if (!picked) return;

      const prevState = state;
      const prevPath = sourcePath;
      setState('switching');

      try {
        await bridge.tauriInvoke('set_ga_source', { dir: picked });
        setState('connected');
        setSourcePath(picked);
        Toast.success({ content: t('data.localRepoSuccess') });
        refreshSessions();
      } catch (e: any) {
        console.error('[GaSource] set_ga_source failed:', e);
        setState(prevState);
        setSourcePath(prevPath);
        Toast.error({ content: mapSourceError(e?.message || '', t) });
      }
    } catch (e: any) {
      console.error('[GaSource] pick_directory failed:', e);
      if (e?.message?.includes('Tauri')) return;
    }
  }, [state, sourcePath, t, refreshSessions]);

  const handleDisconnect = useCallback(async () => {
    setState('switching');
    try {
      await bridge.tauriInvoke('clear_ga_source', {});
      setState('idle');
      setSourcePath(null);
      Toast.info({ content: t('data.localRepoCleared') });
      refreshSessions();
    } catch {
      setState('connected');
      Toast.error({ content: t('data.localRepoSwitchFailed') });
    }
  }, [t, refreshSessions]);

  const disabled = state === 'switching';

  return (
    <div className="ga-source-block">
      <Tooltip content={t('data.localRepoTip')}>
        <span className="ga-data-row-label">{t('data.localRepo')}</span>
      </Tooltip>
      {state !== 'idle' && (
        <div className="ga-source-status">
          <span className={`ga-source-dot ${state === 'connected' ? 'ga-source-dot--on' : 'ga-source-dot--switching'}`} />
          <span className="ga-source-status-text">
            {state === 'connected' ? t('data.localRepoConnected') : t('data.localRepoSwitching')}
          </span>
          {sourcePath && state === 'connected' && (
            <Tooltip content={sourcePath}>
              <span className="ga-source-path">{truncatePath(sourcePath)}</span>
            </Tooltip>
          )}
        </div>
      )}
      <div className="ga-source-actions">
        <Button size="small" type="tertiary" onClick={handlePick} disabled={disabled}>
          {state === 'connected' ? t('data.localRepoChange') : t('data.localRepoPick')}
        </Button>
        {state === 'connected' && (
          <Button size="small" type="tertiary" onClick={handleDisconnect} disabled={disabled}>
            {t('data.localRepoDisconnect')}
          </Button>
        )}
      </div>
    </div>
  );
}
