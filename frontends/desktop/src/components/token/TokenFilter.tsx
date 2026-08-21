import { DatePicker, Button } from '@douyinfe/semi-ui';
import { IconRefresh } from '@douyinfe/semi-icons';
import { useI18n } from '../../i18n';
import { useTokenStore } from '../../stores/token';

export function TokenFilter() {
  const { t } = useI18n();
  const dateRange = useTokenStore((s) => s.dateRange);
  const setDateRange = useTokenStore((s) => s.setDateRange);
  const resetFilters = useTokenStore((s) => s.resetFilters);

  return (
    <div className="ga-token-filter">
      <DatePicker
        type="dateTimeRange"
        value={dateRange[0] && dateRange[1] ? [dateRange[0], dateRange[1]] : undefined}
        onChange={(dates) => {
          if (Array.isArray(dates) && dates.length === 2) {
            setDateRange([
              dates[0] ? new Date(dates[0] as Date) : null,
              dates[1] ? new Date(dates[1] as Date) : null,
            ]);
          } else {
            setDateRange([null, null]);
          }
        }}
        placeholder={[t('tok.from'), t('tok.to')]}
        density="compact"
        style={{ width: 340 }}
      />
      <Button
        size="small"
        icon={<IconRefresh />}
        theme="borderless"
        onClick={resetFilters}
      >
        {t('tok.reset')}
      </Button>
    </div>
  );
}
