import { useMemo } from 'react';
import { useI18n } from '../../i18n';
import { useTokenStore, type TokenSnapshot, type HistoryEntry } from '../../stores/token';
import { formatNumber } from '../../utils/format';

export interface StatCard {
  labelKey: string;
  value: string;
}

interface Props {
  snapshot?: TokenSnapshot;
  history?: HistoryEntry[];
  cards?: StatCard[];
}

export function TokenStats({ snapshot: snapshotProp, history: historyProp, cards }: Props) {
  const { t } = useI18n();
  const storeSnapshot = useTokenStore((s) => s.snapshot);
  const storeHistory = useTokenStore((s) => s.history);
  const dateRange = useTokenStore((s) => s.dateRange);

  const snapshot = snapshotProp ?? storeSnapshot;
  const history = historyProp ?? storeHistory;

  const filteredStats = useMemo(() => {
    const [from, to] = dateRange;
    const hasFilter = !snapshotProp && (from || to);

    if (hasFilter) {
      const filtered = history.filter((e) => {
        const ts = e.ts < 1e12 ? e.ts * 1000 : e.ts;
        if (from && ts < from.getTime()) return false;
        if (to && ts > to.getTime()) return false;
        return true;
      });
      const totalInput = filtered.reduce((s, e) => s + e.input, 0);
      const totalOutput = filtered.reduce((s, e) => s + e.output, 0);
      const totalCacheWrite = filtered.reduce((s, e) => s + e.cacheWrite, 0);
      const totalCacheRead = filtered.reduce((s, e) => s + e.cacheRead, 0);
      return { totalInput, totalOutput, totalCacheWrite, totalCacheRead };
    }

    return snapshot;
  }, [history, snapshot, dateRange, snapshotProp]);

  const todayTokens = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const todayTs = today.getTime();
    return history
      .filter((e) => {
        const ts = e.ts < 1e12 ? e.ts * 1000 : e.ts;
        return ts >= todayTs;
      })
      .reduce((sum, e) => sum + e.input + e.output, 0);
  }, [history]);

  const totalTokens = filteredStats.totalInput + filteredStats.totalOutput;
  const inputSide = filteredStats.totalInput + filteredStats.totalCacheWrite + filteredStats.totalCacheRead;
  const cacheRate =
    inputSide > 0
      ? ((filteredStats.totalCacheRead / inputSide) * 100).toFixed(1)
      : '0';

  const defaultCards: StatCard[] = [
    { labelKey: 'tok.total', value: formatNumber(totalTokens) },
    { labelKey: 'tok.cost', value: `${cacheRate}%` },
    { labelKey: 'tok.today', value: formatNumber(todayTokens) },
  ];

  const displayCards = cards ?? defaultCards;

  return (
    <div className="ga-token-stats">
      {displayCards.map((card) => (
        <div
          key={card.labelKey}
          className="ga-token-stat-card"
          data-testid={`token-stat-${card.labelKey}`}
        >
          <div className="ga-token-stat-label">{t(card.labelKey)}</div>
          <div className="ga-token-stat-value" data-testid={`token-stat-value-${card.labelKey}`}>
            {card.value}
          </div>
        </div>
      ))}
    </div>
  );
}
