import { useI18n } from '../../i18n';
import { Codicon } from '../../lib/icons';

const STEPS = [
  { key: '1', icon: 'comment' },
  { key: '2', icon: 'symbol-misc' },
  { key: '3', icon: 'graph' },
  { key: '4', icon: 'edit' },
] as const;

const CHIPS = [
  'collab.chipProgress',
  'collab.chipPause',
  'collab.chipSummary',
] as const;

interface Props {
  onChipClick: (text: string) => void;
}

export function CollabWelcome({ onChipClick }: Props) {
  const { t } = useI18n();

  return (
    <div className="collab-welcome" data-slot="collab-welcome">
      <h2 className="collab-welcome-title">{t('collab.guideTitle')}</h2>
      <p className="collab-welcome-sub">{t('collab.guideWhen')}</p>

      <div className="collab-welcome-steps">
        {STEPS.map((step) => (
          <div key={step.key} className="collab-welcome-step">
            <span className="collab-welcome-step-icon">
              <Codicon name={step.icon} size="1rem" />
            </span>
            <span className="collab-welcome-step-text">
              <span className="collab-welcome-step-label">
                {t(`collab.guideStep${step.key}t`)}
              </span>
              <span className="collab-welcome-step-desc">
                {t(`collab.guideStep${step.key}d`)}
              </span>
            </span>
          </div>
        ))}
      </div>

      <div className="collab-welcome-chips">
        {CHIPS.map((key) => (
          <button
            key={key}
            type="button"
            className="collab-welcome-chip"
            onClick={() => onChipClick(t(key))}
          >
            {t(key)}
          </button>
        ))}
      </div>
    </div>
  );
}
