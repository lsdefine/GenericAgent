import { useEffect } from 'react';
import { LocaleProvider } from '@douyinfe/semi-ui';
import zh_CN from '@douyinfe/semi-ui/lib/es/locale/source/zh_CN';
import en_US from '@douyinfe/semi-ui/lib/es/locale/source/en_US';
import { useSettingsStore } from './stores/settings';
import { AppLayout } from './components/layout/AppLayout';
import { NotificationStack } from './components/layout/NotificationStack';
import { SettingsModal } from './components/settings/SettingsModal';

const SEMI_LOCALES = { zh: zh_CN, en: en_US };

export function App() {
  const lang = useSettingsStore((s) => s.lang);
  const loadFromBridge = useSettingsStore((s) => s.loadFromBridge);

  useEffect(() => {
    loadFromBridge();
  }, [loadFromBridge]);

  return (
    <LocaleProvider locale={SEMI_LOCALES[lang]}>
      <AppLayout />
      <SettingsModal />
      <NotificationStack />
    </LocaleProvider>
  );
}
