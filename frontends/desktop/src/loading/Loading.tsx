import { t } from './i18n';
import type { BootstrapMode } from './types';

export function LoadingScreen({ mode }: { mode: BootstrapMode }) {
  return (
    <div className="bs-screen bs-loading">
      <div className="bs-spinner" />
      <p className="bs-text">{mode === 'hot_start' ? t('resuming') : t('starting')}</p>
    </div>
  );
}
