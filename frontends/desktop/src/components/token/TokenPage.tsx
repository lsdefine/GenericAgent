import { useEffect } from 'react';
import { Tabs, TabPane } from '@douyinfe/semi-ui';
import { useI18n } from '../../i18n';
import { useTokenStore } from '../../stores/token';
import { TokenStats } from './TokenStats';
import { TokenTable } from './TokenTable';
import { TokenFilter } from './TokenFilter';
import { ConductorTab } from './ConductorTab';
import './token.css';

export function TokenPage() {
  const { t } = useI18n();
  const fetchHistory = useTokenStore((s) => s.fetchHistory);
  const startPolling = useTokenStore((s) => s.startPolling);
  const stopPolling = useTokenStore((s) => s.stopPolling);

  useEffect(() => {
    fetchHistory();
    startPolling();
    return () => stopPolling();
  }, [fetchHistory, startPolling, stopPolling]);

  return (
    <div className="ga-token-page">
      <Tabs type="line" defaultActiveKey="chat">
        <TabPane tab={t('tok.tabAll')} itemKey="chat">
          <div className="ga-token-content">
            <TokenStats />
            <TokenFilter />
            <TokenTable />
          </div>
        </TabPane>
        <TabPane tab={t('tok.tabConductor')} itemKey="conductor">
          <ConductorTab />
        </TabPane>
      </Tabs>
      <div className="ga-token-disclaimer">{t('tok.disclaimer')}</div>
    </div>
  );
}
