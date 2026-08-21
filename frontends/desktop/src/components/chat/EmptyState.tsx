import { IconChecklistStroked, IconFlagStroked, IconLightningStroked, IconShareStroked, IconShieldStroked, IconSearchStroked } from '@douyinfe/semi-icons';
import { useI18n } from '../../i18n';
import { BUILTIN_SKILLS, type SkillDef } from './Composer/skills';
import wordmarkLight from '../../assets/generic-agent-black.svg';
import wordmarkDark from '../../assets/generic-agent-white.svg';
import './emptyState.css';

const SKILL_ICONS: Record<string, React.ReactNode> = {
  plan: <IconChecklistStroked size="small" />,
  goal: <IconFlagStroked size="small" />,
  autonomous: <IconLightningStroked size="small" />,
  hive: <IconShareStroked size="small" />,
  review: <IconShieldStroked size="small" />,
  findwork: <IconSearchStroked size="small" />,
};

interface Props {
  onPresetClick: (skill: SkillDef) => void;
}

export function EmptyState({ onPresetClick }: Props) {
  const { t } = useI18n();

  return (
    <div data-slot="empty-state-root">
      <div data-slot="empty-state-wordmark">
        <img src={wordmarkLight} alt="GenericAgent" className="empty-state-wordmark-light" />
        <img src={wordmarkDark} alt="" className="empty-state-wordmark-dark" aria-hidden="true" />
      </div>
      <div data-slot="empty-state-presets">
        {BUILTIN_SKILLS.map((skill) => (
          <button
            key={skill.id}
            type="button"
            className="empty-state-preset-btn"
            onClick={() => onPresetClick(skill)}
          >
            <span className="empty-state-preset-icon">{SKILL_ICONS[skill.id]}</span>
            <span>{t(`preset.${skill.id}.t`) || skill.title}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
