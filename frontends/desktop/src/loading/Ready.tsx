import { t } from './i18n';

export function ReadyScreen() {
  return (
    <div className="bs-screen bs-ready">
      <div className="bs-check" aria-hidden="true">&#10003;</div>
      <p className="bs-text">{t('ready')}</p>
      <p className="bs-subtext">{t('readyDetail')}</p>
    </div>
  );
}
