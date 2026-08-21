import { useState, useCallback } from 'react';
import { Button, Toast, Tag } from '@douyinfe/semi-ui';
import { useSettingsStore } from '../../stores/settings';
import { useI18n } from '../../i18n';
import * as bridge from '../../services/bridge';
import type { ModelProfile } from '../../services/bridge';
import { getProviderIcon, providerFromModel } from '../../data/provider-icons';

function ModelIcon({ model, size = 16 }: { model: string; size?: number }) {
  const key = providerFromModel(model);
  const def = key ? getProviderIcon(key) : undefined;
  if (!def?.Component) return null;
  const Comp = def.Component;
  return <Comp size={size} />;
}

function profileLabel(p: ModelProfile): string {
  const m = p.model || '';
  const slash = m.lastIndexOf('/');
  if (m) return slash >= 0 ? m.slice(slash + 1) : m;
  const s = (p.name || '').trim();
  const i = s.indexOf('/');
  return (i >= 0 ? s.slice(i + 1) : s) || '(unnamed)';
}

interface Props {
  onAdd: () => void;
  onEdit: (id: number) => void;
}

export function ModelSection({ onAdd, onEdit }: Props) {
  const { t } = useI18n();
  const modelProfiles = useSettingsStore((s) => s.modelProfiles);
  const selectedModelNo = useSettingsStore((s) => s.defaultModelNo);
  const setDefaultModel = useSettingsStore((s) => s.setDefaultModel);
  const setModelProfiles = useSettingsStore((s) => s.setModelProfiles);

  const [mixinExpanded, setMixinExpanded] = useState(true);

  const mixin = modelProfiles.find((p) => p.kind === 'mixin');
  const natives = modelProfiles.filter((p) => p.kind !== 'mixin');
  const mixinIdx = mixin ? modelProfiles.indexOf(mixin) : -1;

  const handleSelect = useCallback((idx: number) => {
    setDefaultModel(idx);
  }, [setDefaultModel]);

  const handleDelete = useCallback(async (id: number, name: string) => {
    if (!confirm(`${t('common.delete')} "${name}"？`)) return;
    try {
      const profiles = await bridge.deleteModelProfile(id);
      setModelProfiles(profiles);
      Toast.success({ content: t('common.delete') });
    } catch {
      Toast.error({ content: t('err.modelDelete') });
    }
  }, [setModelProfiles, t]);

  const handleEdit = useCallback((id: number) => {
    onEdit(id);
  }, [onEdit]);

  const handleAdd = useCallback(() => {
    onAdd();
  }, [onAdd]);

  const handleAddToMixin = useCallback(async (id: number) => {
    try {
      const profiles = await bridge.addToMixin(id);
      setModelProfiles(profiles);
    } catch {
      Toast.error({ content: t('err.mixinFailed') });
    }
  }, [setModelProfiles, t]);

  const handleRemoveFromMixin = useCallback(async (id: number) => {
    try {
      const profiles = await bridge.removeFromMixin(id);
      setModelProfiles(profiles);
    } catch {
      Toast.error({ content: t('err.mixinFailed') });
    }
  }, [setModelProfiles, t]);

  const handleMoveUp = useCallback(async (memberName: string) => {
    if (!mixin?.members) return;
    const members = [...mixin.members];
    const idx = members.indexOf(memberName);
    if (idx <= 0) return;
    [members[idx - 1], members[idx]] = [members[idx], members[idx - 1]];
    try {
      const profiles = await bridge.reorderMixin(members);
      setModelProfiles(profiles);
    } catch {
      Toast.error({ content: t('err.mixinFailed') });
    }
  }, [mixin, setModelProfiles, t]);

  const handleMoveDown = useCallback(async (memberName: string) => {
    if (!mixin?.members) return;
    const members = [...mixin.members];
    const idx = members.indexOf(memberName);
    if (idx < 0 || idx >= members.length - 1) return;
    [members[idx], members[idx + 1]] = [members[idx + 1], members[idx]];
    try {
      const profiles = await bridge.reorderMixin(members);
      setModelProfiles(profiles);
    } catch {
      Toast.error({ content: t('err.mixinFailed') });
    }
  }, [mixin, setModelProfiles, t]);

  return (
    <div className="ga-set-block">
      <div className="ga-set-sec-t">{t('set.model')}</div>

      {/* ── Mixin / 渠道组 ── */}
      {mixin && (
        <div className="ga-mixin-group">
          <div
            className={`ga-mixin-head${mixinIdx === selectedModelNo ? ' ga-mixin-head--active' : ''}`}
            onClick={() => handleSelect(mixinIdx)}
          >
            <button
              type="button"
              className="ga-mixin-toggle"
              onClick={(e) => { e.stopPropagation(); setMixinExpanded((v) => !v); }}
              aria-label="toggle"
            >
              <CaretIcon expanded={mixinExpanded} />
            </button>
            <span className="ga-mixin-label">{t('model.aggregation')}</span>
            {mixinIdx === selectedModelNo && <Tag color="green" size="small">{t('set.current')}</Tag>}
          </div>

          {mixinExpanded && (
            <div className="ga-mixin-body">
              {(!mixin.members || mixin.members.length === 0) ? (
                <div className="ga-mixin-empty">{t('model.emptyMixin')}</div>
              ) : (
                <div className="ga-mixin-members">
                  {mixin.members.map((memberName, i) => {
                    const memberProfile = natives.find((p) => p.name === memberName);
                    const label = memberProfile ? profileLabel(memberProfile) : memberName;
                    return (
                      <div key={memberName} className="ga-mixin-member">
                        <span className="ga-mixin-member-rank">{i + 1}</span>
                        <ModelIcon model={memberProfile?.model || ''} size={14} />
                        <span className="ga-mixin-member-name">{label}</span>
                        <span className="ga-mixin-member-actions">
                          <button
                            type="button"
                            className="ga-icon-btn"
                            disabled={i === 0}
                            onClick={() => handleMoveUp(memberName)}
                            title="↑"
                          >↑</button>
                          <button
                            type="button"
                            className="ga-icon-btn"
                            disabled={i === mixin.members!.length - 1}
                            onClick={() => handleMoveDown(memberName)}
                            title="↓"
                          >↓</button>
                          <button
                            type="button"
                            className="ga-icon-btn ga-icon-btn--danger"
                            onClick={() => memberProfile && handleRemoveFromMixin(memberProfile.id)}
                            title={t('model.removeFromMixin')}
                          >×</button>
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="ga-mixin-hint">{t('model.aggregationDesc')}</div>
            </div>
          )}
        </div>
      )}

      {/* ── Individual models ── */}
      <div className="ga-model-list">
        {natives.length === 0 && (
          <div className="ga-model-empty">{t('set.noModels')}</div>
        )}
        {natives.map((profile) => {
          const actualIdx = modelProfiles.indexOf(profile);
          const isSelected = actualIdx === selectedModelNo;
          return (
            <div
              key={profile.id}
              className={`ga-model-item${isSelected ? ' ga-model-item--selected' : ''}`}
              onClick={() => handleSelect(actualIdx)}
            >
              <div className="ga-model-row-content">
                <ModelIcon model={profile.model || ''} />
                <span className="ga-model-name">{profileLabel(profile)}</span>
                {isSelected && <Tag color="green" size="small">{t('set.current')}</Tag>}
                {profile.inMixin && <Tag size="small">{t('model.inMixin')}</Tag>}
              </div>
              <span className="ga-model-actions">
                {mixin && !profile.inMixin && (
                  <Button
                    size="small"
                    type="tertiary"
                    theme="borderless"
                    onClick={(e) => { e.stopPropagation(); handleAddToMixin(profile.id); }}
                  >
                    +
                  </Button>
                )}
                <Button
                  size="small"
                  type="tertiary"
                  theme="borderless"
                  onClick={(e) => { e.stopPropagation(); handleEdit(profile.id); }}
                >
                  {t('common.edit')}
                </Button>
                <Button
                  size="small"
                  type="danger"
                  theme="borderless"
                  onClick={(e) => { e.stopPropagation(); handleDelete(profile.id, profileLabel(profile)); }}
                >
                  {t('common.delete')}
                </Button>
              </span>
            </div>
          );
        })}
      </div>

      <Button type="tertiary" onClick={handleAdd} className="ga-add-model-btn">
        + {t('set.addModel')}
      </Button>
    </div>
  );
}

function CaretIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="currentColor"
      style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s' }}
    >
      <path d="M4.5 2.5L8 6L4.5 9.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}
