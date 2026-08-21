import type { ProviderPreset } from '../../data/model-presets';
import { useI18n } from '../../i18n';

interface Props {
  preset: ProviderPreset;
  onClick: () => void;
}

export function ProviderCard({ preset, onClick }: Props) {
  const { t } = useI18n();

  return (
    <button
      type="button"
      className="ga-provider-card"
      onClick={onClick}
      style={{ '--provider-color': preset.color } as React.CSSProperties}
    >
      <svg
        className="ga-provider-card-icon"
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill={preset.color}
        fillRule="evenodd"
        xmlns="http://www.w3.org/2000/svg"
      >
        {Array.isArray(preset.iconPath)
          ? preset.iconPath.map((d, i) => <path key={i} d={d} />)
          : <path d={preset.iconPath} />
        }
      </svg>
      <span className="ga-provider-card-body">
        <span className="ga-provider-card-label">{preset.label}</span>
        <span className="ga-provider-card-desc">{t(preset.descKey)}</span>
      </span>
      <span className="ga-provider-card-caret">›</span>
    </button>
  );
}
