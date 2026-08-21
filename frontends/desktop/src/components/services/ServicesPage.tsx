import { useEffect } from 'react';
import { Tabs, TabPane } from '@douyinfe/semi-ui';
import { useI18n } from '../../i18n';
import { useServicesStore } from '../../stores/services';
import { useAppStore } from '../../stores/app';
import { ChannelList } from './ChannelList';
import { StatusPanel } from './StatusPanel';
import './services.css';

export function ServicesPage() {
  const { t } = useI18n();
  const fetchServices = useServicesStore((s) => s.fetchServices);
  const servicesTab = useAppStore((s) => s.servicesTab);
  const setServicesTab = useAppStore((s) => s.setServicesTab);

  useEffect(() => {
    fetchServices();
  }, [fetchServices]);

  return (
    <div className="ga-services-page">
      <Tabs type="line" activeKey={servicesTab} onChange={setServicesTab}>
        <TabPane tab={t('nav.channels')} itemKey="channels">
          <ChannelList />
        </TabPane>
        <TabPane tab={t('nav.status')} itemKey="status">
          <StatusPanel />
        </TabPane>
      </Tabs>
    </div>
  );
}
