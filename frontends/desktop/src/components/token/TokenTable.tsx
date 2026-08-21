import { useMemo } from 'react';
import { Table, Tag, Empty } from '@douyinfe/semi-ui';
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table';
import { useI18n } from '../../i18n';
import { useTokenStore, type HistoryEntry } from '../../stores/token';
import { useChatStore } from '../../stores/chat';
import { formatTokenCount } from '../../utils/format';

interface AggregatedEntry {
  id: string;
  title: string;
  input: number;
  output: number;
  cacheWrite: number;
  cacheRead: number;
  model: string;
  ts: number;
  deleted?: boolean;
}

function aggregateBySession(entries: HistoryEntry[], sessionTitleMap: Map<string, string>): AggregatedEntry[] {
  const map = new Map<string, AggregatedEntry>();
  for (const e of entries) {
    // Group by sessionId (the real session identifier)
    const key = e.id;
    const existing = map.get(key);
    if (existing) {
      existing.input += e.input;
      existing.output += e.output;
      existing.cacheWrite += e.cacheWrite;
      existing.cacheRead += e.cacheRead;
      if (e.ts > existing.ts) existing.ts = e.ts;
      if (e.deleted) existing.deleted = true;
    } else {
      // Resolve display title: prefer the real session title from chat store
      const realTitle = sessionTitleMap.get(e.id);
      map.set(key, {
        id: e.id,
        title: realTitle || e.title || e.id,
        input: e.input,
        output: e.output,
        cacheWrite: e.cacheWrite,
        cacheRead: e.cacheRead,
        model: e.model,
        ts: e.ts,
        deleted: e.deleted,
      });
    }
  }
  return [...map.values()];
}

interface Props {
  /** If provided, renders this data instead of the store's chat history */
  dataSource?: HistoryEntry[];
  loading?: boolean;
}

export function TokenTable({ dataSource, loading: loadingProp }: Props) {
  const { t } = useI18n();
  const storeHistory = useTokenStore((s) => s.history);
  const storeLoading = useTokenStore((s) => s.loading);
  const dateRange = useTokenStore((s) => s.dateRange);
  const sessions = useChatStore((s) => s.sessions);

  const history = dataSource ?? storeHistory;
  const loading = loadingProp ?? storeLoading;

  const sessionTitleMap = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of sessions) {
      if (s.title) m.set(s.id, s.title);
    }
    return m;
  }, [sessions]);

  const processedData = useMemo(() => {
    let entries = history;

    // Apply date filter (only for store history, not externally-provided data)
    if (!dataSource) {
      const [from, to] = dateRange;
      if (from || to) {
        entries = entries.filter((entry) => {
          const ts = entry.ts < 1e12 ? entry.ts * 1000 : entry.ts;
          if (from && ts < from.getTime()) return false;
          if (to && ts > to.getTime()) return false;
          return true;
        });
      }
    }

    // Aggregate entries with same sessionId into one row per session
    const aggregated = aggregateBySession(entries, sessionTitleMap);

    // Default sort: most recent first
    aggregated.sort((a, b) => b.ts - a.ts);

    return aggregated;
  }, [history, dateRange, dataSource, sessionTitleMap]);

  const columns: ColumnProps<AggregatedEntry>[] = [
    {
      title: t('tok.colSession'),
      dataIndex: 'title',
      key: 'title',
      render: (_text: unknown, record: AggregatedEntry) => (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span>{record.title || record.id}</span>
          {record.deleted && (
            <Tag size="small" color="orange" type="ghost">
              {t('tok.deleted')}
            </Tag>
          )}
        </span>
      ),
    },
    {
      title: t('tok.colIn'),
      dataIndex: 'input',
      key: 'input',
      width: 100,
      sorter: (a?: AggregatedEntry, b?: AggregatedEntry) => (a?.input ?? 0) - (b?.input ?? 0),
      render: (_text: unknown, record: AggregatedEntry) => (
        <span className="ga-token-mono">{formatTokenCount(record.input)}</span>
      ),
    },
    {
      title: t('tok.colOut'),
      dataIndex: 'output',
      key: 'output',
      width: 100,
      sorter: (a?: AggregatedEntry, b?: AggregatedEntry) => (a?.output ?? 0) - (b?.output ?? 0),
      render: (_text: unknown, record: AggregatedEntry) => (
        <span className="ga-token-mono">{formatTokenCount(record.output)}</span>
      ),
    },
    {
      title: t('tok.colCacheW'),
      dataIndex: 'cacheWrite',
      key: 'cacheWrite',
      width: 110,
      sorter: (a?: AggregatedEntry, b?: AggregatedEntry) => (a?.cacheWrite ?? 0) - (b?.cacheWrite ?? 0),
      render: (_text: unknown, record: AggregatedEntry) => (
        <span className="ga-token-mono">{formatTokenCount(record.cacheWrite)}</span>
      ),
    },
    {
      title: t('tok.colCache'),
      dataIndex: 'cacheRead',
      key: 'cacheRead',
      width: 110,
      sorter: (a?: AggregatedEntry, b?: AggregatedEntry) => (a?.cacheRead ?? 0) - (b?.cacheRead ?? 0),
      render: (_text: unknown, record: AggregatedEntry) => (
        <span className="ga-token-mono">{formatTokenCount(record.cacheRead)}</span>
      ),
    },
    {
      title: t('tok.cost'),
      key: 'cacheRate',
      width: 100,
      render: (_text: unknown, record: AggregatedEntry) => {
        const inputSide = record.input + record.cacheWrite + record.cacheRead;
        const rate = inputSide > 0 ? ((record.cacheRead / inputSide) * 100).toFixed(1) : '0';
        return <span className="ga-token-mono">{rate}%</span>;
      },
    },
  ];

  if (!loading && processedData.length === 0) {
    return <Empty description={t('tok.noData')} style={{ marginTop: 32 }} />;
  }

  return (
    <Table
      columns={columns}
      dataSource={processedData}
      rowKey="id"
      loading={loading}
      pagination={{ pageSize: 15, showTotal: true }}
      size="small"
      bordered={false}
    />
  );
}
