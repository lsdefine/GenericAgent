import { useState, useCallback } from 'react';
import { Button, Tag, Spin, Empty } from '@douyinfe/semi-ui';
import { IconPlay, IconStop, IconFile, IconSetting, IconAlertTriangle } from '@douyinfe/semi-icons';
import { useI18n } from '../../i18n';
import { useBridgeStatus } from '../../hooks/useBridgeStatus';
import { useServicesStore, type ServiceInfo } from '../../stores/services';
import { showError, showSuccess } from '../../utils/toast';
import { isTauri, invokeStartBridge } from '../../utils/tauri';
import { ChannelLogModal } from './ChannelLogModal';
import { MykeyConfigModal } from './MykeyConfigModal';

import qqIcon from '../../assets/channels/qq.svg';
import wechatIcon from '../../assets/channels/wechat.svg';
import wecomIcon from '../../assets/channels/wecom.svg';
import dingtalkIcon from '../../assets/channels/dingtalk.svg';
import telegramIcon from '../../assets/channels/telegram.svg';
import discordIcon from '../../assets/channels/discord.svg';
import feishuIcon from '../../assets/channels/feishu.svg';

interface ChannelMeta {
  label: string;
  icon: string;
}

/** Map service IDs to display labels and icons */
const CHANNEL_META: Record<string, ChannelMeta> = {
  'frontends/qqapp.py': { label: 'ch.qq', icon: qqIcon },
  'frontends/wechatapp.py': { label: 'ch.wechat', icon: wechatIcon },
  'frontends/wecomapp.py': { label: 'ch.wecom', icon: wecomIcon },
  'frontends/dingtalkapp.py': { label: 'ch.dingtalk', icon: dingtalkIcon },
  'frontends/tgapp.py': { label: 'ch.telegram', icon: telegramIcon },
  'frontends/dcapp.py': { label: 'ch.discord', icon: discordIcon },
  'frontends/fsapp.py': { label: 'ch.lark', icon: feishuIcon },
};

const CHANNEL_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(CHANNEL_META).map(([k, v]) => [k, v.label]),
);

/** Only show IM channel processes in this tab */
const CHANNEL_IDS = new Set(Object.keys(CHANNEL_LABELS));

export function isChannelService(svc: ServiceInfo): boolean {
  return CHANNEL_IDS.has(svc.id) || CHANNEL_IDS.has(svc.name);
}

export function ChannelList() {
  const { t } = useI18n();
  const bridgeStatus = useBridgeStatus();
  const services = useServicesStore((s) => s.services);
  const loading = useServicesStore((s) => s.loading);
  const startService = useServicesStore((s) => s.startService);
  const stopService = useServicesStore((s) => s.stopService);

  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [logTarget, setLogTarget] = useState<string | null>(null);
  const [showMykey, setShowMykey] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const channels = services.filter(isChannelService);

  const handleRestartBridge = useCallback(async () => {
    setRestarting(true);
    try {
      await invokeStartBridge();
    } catch {
      showError(t('err.bridge'));
    } finally {
      setRestarting(false);
    }
  }, [t]);

  const handleToggle = useCallback(
    async (svc: ServiceInfo) => {
      setBusyIds((prev) => new Set([...prev, svc.id]));
      try {
        if (svc.running) {
          const ok = await stopService(svc.id);
          if (ok) showSuccess(t('sys.channelStopped'));
          else showError(t('err.channelStop'));
        } else {
          const ok = await startService(svc.id);
          if (ok) showSuccess(t('sys.channelStarted'));
          else showError(t('err.channelStart'));
        }
      } finally {
        setBusyIds((prev) => {
          const next = new Set(prev);
          next.delete(svc.id);
          return next;
        });
      }
    },
    [startService, stopService, t],
  );

  const isOffline = bridgeStatus !== 'ready';

  if (isOffline && channels.length === 0) {
    return (
      <div className="ga-services-loading ga-services-loading--col">
        <IconAlertTriangle style={{ color: 'var(--semi-color-warning)', fontSize: 24 }} />
        <span>{t('bridge.notRunning')}</span>
        {isTauri() ? (
          <Button
            data-testid="bridge-restart"
            loading={restarting}
            onClick={handleRestartBridge}
            theme="light"
            type="primary"
          >
            {t('bridge.restart')}
          </Button>
        ) : (
          <code className="ga-bridge-hint">{t('bridge.notRunningHint')}</code>
        )}
      </div>
    );
  }

  if (loading && channels.length === 0) {
    return (
      <div className="ga-services-loading">
        <Spin size="large" />
        <span>{t('ch.loading')}</span>
      </div>
    );
  }

  if (!isOffline && channels.length === 0) {
    return <Empty description={t('ch.empty')} />;
  }

  return (
    <div className="ga-channel-list">
      {isOffline && (
        <div className="ga-offline-banner">
          <IconAlertTriangle size="small" />
          <span>{t('bridge.staleData')}</span>
          {isTauri() && (
            <Button
              data-testid="bridge-restart"
              size="small"
              loading={restarting}
              onClick={handleRestartBridge}
              theme="light"
            >
              {t('bridge.restart')}
            </Button>
          )}
        </div>
      )}
      {channels.map((svc) => {
        const meta = CHANNEL_META[svc.id] || CHANNEL_META[svc.name];
        const labelKey = meta?.label || '';
        const label = labelKey ? t(labelKey) : svc.name;
        const icon = meta?.icon;
        const busy = busyIds.has(svc.id);

        return (
          <div key={svc.id} className="ga-channel-card">
            <div className="ga-channel-card-info">
              {icon && (
                <img
                  src={icon}
                  alt=""
                  className="ga-channel-icon"
                />
              )}
              <span className="ga-channel-card-name">{label}</span>
              <Tag size="small" color={svc.running ? 'green' : 'grey'} type="ghost">
                {svc.running ? t('st.online') : t('st.offline')}
              </Tag>
              {svc.lastError && (
                <Tag size="small" color="red" type="ghost">
                  {svc.lastError}
                </Tag>
              )}
            </div>
            <div className="ga-channel-card-actions">
              <Button
                size="small"
                icon={svc.running ? <IconStop /> : <IconPlay />}
                loading={busy}
                disabled={isOffline}
                onClick={() => handleToggle(svc)}
                type={svc.running ? 'danger' : 'primary'}
                theme="light"
              >
                {svc.running ? t('act.stop') : t('act.start')}
              </Button>
              <Button
                size="small"
                icon={<IconFile />}
                theme="borderless"
                onClick={() => setLogTarget(svc.id)}
              >
                {t('act.logs')}
              </Button>
              <Button
                size="small"
                icon={<IconSetting />}
                theme="borderless"
                onClick={() => setShowMykey(true)}
              >
                {t('act.configure')}
              </Button>
            </div>
          </div>
        );
      })}

      <ChannelLogModal
        serviceId={logTarget}
        onClose={() => setLogTarget(null)}
      />
      <MykeyConfigModal
        visible={showMykey}
        onClose={() => setShowMykey(false)}
      />
    </div>
  );
}
