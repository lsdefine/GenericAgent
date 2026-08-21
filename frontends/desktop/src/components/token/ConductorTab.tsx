import { useEffect, useMemo } from 'react';
import { Empty, Spin, Banner } from '@douyinfe/semi-ui';
import { useI18n } from '../../i18n';
import { useTokenStore } from '../../stores/token';
import { formatNumber } from '../../utils/format';
import { TokenStats, type StatCard } from './TokenStats';
import { TokenTable } from './TokenTable';

function ConductorTable() {
  const { t } = useI18n();
  const history = useTokenStore((s) => s.conductorHistory);
  const loading = useTokenStore((s) => s.conductorLoading);

  if (!loading && history.length === 0) {
    return <Empty description={t('tok.noData')} style={{ marginTop: 32 }} />;
  }

  if (loading) {
    return (
      <div className="ga-token-loading">
        <Spin />
      </div>
    );
  }

  return <TokenTable dataSource={history} loading={false} />;
}

export function ConductorTab() {
  const { t } = useI18n();
  const fetchConductorHistory = useTokenStore((s) => s.fetchConductorHistory);
  const conductorOffline = useTokenStore((s) => s.conductorOffline);
  const snap = useTokenStore((s) => s.conductorSnapshot);

  useEffect(() => {
    fetchConductorHistory();
  }, [fetchConductorHistory]);

  const cards: StatCard[] = useMemo(() => {
    const total = snap.totalInput + snap.totalOutput;
    return [
      { labelKey: 'tok.condTotal', value: formatNumber(total) },
      { labelKey: 'tok.colIn', value: formatNumber(snap.totalInput) },
      { labelKey: 'tok.colOut', value: formatNumber(snap.totalOutput) },
    ];
  }, [snap]);

  return (
    <div className="ga-token-content">
      <Banner
        type="info"
        description={t('tok.condTip')}
        style={{ marginBottom: 12 }}
      />
      {conductorOffline ? (
        <Banner type="warning" description={t('tok.condOffline')} />
      ) : (
        <>
          <TokenStats cards={cards} />
          <ConductorTable />
        </>
      )}
    </div>
  );
}
