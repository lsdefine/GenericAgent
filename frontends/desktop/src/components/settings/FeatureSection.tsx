import { Button } from '@douyinfe/semi-ui';
import { useI18n } from '../../i18n';

export function FeatureSection() {
  const { t } = useI18n();

  const handleOpenServices = () => {
    window.dispatchEvent(new CustomEvent('ga:go-page', { detail: { page: 'services' } }));
    window.dispatchEvent(new Event('ga:close-settings'));
  };

  return (
    <div className="ga-set-block">
      <div className="ga-set-sec-t">{t('modal.features') || '功能'}</div>
      <div className="ga-feature-buttons">
        <Button type="tertiary" onClick={handleOpenServices}>
          {t('nav.services')}
        </Button>
      </div>
    </div>
  );
}
