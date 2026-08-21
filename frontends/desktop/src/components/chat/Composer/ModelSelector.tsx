import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useSettingsStore } from '../../../stores/settings';
import { useChatStore } from '../../../stores/chat';
import { useI18n } from '../../../i18n';
import type { ModelProfile } from '../../../services/bridge';
import { getProviderIcon, providerFromModel } from '../../../data/provider-icons';

const PROVIDER_COLORS: Record<string, string> = {
  deepseek: '#4D6BFE',
  dashscope: '#615CED',
  qwen: '#615CED',
  openai: '#10A37F',
  anthropic: '#D97706',
  openrouter: '#6366F1',
  google: '#4285F4',
  moonshot: '#7C3AED',
  kimi: '#7C3AED',
  doubao: '#006EFF',
  minimax: '#F23F5D',
  zhipu: '#3859FF',
  stepfun: '#005AFF',
};

function providerColor(apibase: string, model?: string): string {
  const lower = (apibase || '').toLowerCase();
  for (const [key, color] of Object.entries(PROVIDER_COLORS)) {
    if (lower.includes(key)) return color;
  }
  const fromModel = providerFromModel(model || '');
  if (fromModel && PROVIDER_COLORS[fromModel]) return PROVIDER_COLORS[fromModel];
  return 'var(--semi-color-text-3, #8f959e)';
}

function providerName(apibase: string, model?: string): string {
  const lower = (apibase || '').toLowerCase();
  if (lower.includes('deepseek')) return 'DEEPSEEK';
  if (lower.includes('dashscope') || lower.includes('qwen')) return 'QWEN';
  if (lower.includes('anthropic')) return 'ANTHROPIC';
  if (lower.includes('openai')) return 'OPENAI';
  if (lower.includes('openrouter')) return 'OPENROUTER';
  if (lower.includes('google')) return 'GOOGLE';
  if (lower.includes('moonshot')) return 'KIMI';
  if (lower.includes('volces') || lower.includes('volcengine')) return 'DOUBAO';
  if (lower.includes('minimax')) return 'MINIMAX';
  if (lower.includes('bigmodel') || lower.includes('zhipu')) return 'ZHIPU';
  if (lower.includes('stepfun')) return 'STEPFUN';
  const fromModel = providerFromModel(model || '');
  if (fromModel) return fromModel.toUpperCase();
  return 'OTHER';
}

function profileLabel(name: string): string {
  const s = String(name || '');
  const i = s.indexOf('/');
  return (i >= 0 ? s.slice(i + 1) : s).trim();
}

function modelShortName(profile: ModelProfile): string {
  const m = profile.model || '';
  const slash = m.lastIndexOf('/');
  return slash >= 0 ? m.slice(slash + 1) : m || profileLabel(profile.name);
}

export function formatModelSelectionLabel(
  profiles: ModelProfile[],
  selectedNo: number,
  runningNo: number | null | undefined,
  isRunning: boolean,
): string {
  const selected = profiles[selectedNo];
  const selectedLabel = selected ? modelShortName(selected) : '';
  if (!isRunning || runningNo == null || runningNo === selectedNo) return selectedLabel;
  const running = profiles[runningNo];
  return running ? `${modelShortName(running)} → ${selectedLabel}` : selectedLabel;
}

function ProviderIcon({ apibase, model, size = 14 }: { apibase: string; model?: string; size?: number }) {
  const providerKey = providerFromModel(model || '') || providerKeyFromApibase(apibase);
  const iconDef = providerKey ? getProviderIcon(providerKey) : undefined;

  if (iconDef?.Component) {
    const Comp = iconDef.Component;
    return <Comp size={size} />;
  }
  return <span data-slot="provider-dot" style={{ background: providerColor(apibase, model) }} />;
}

function providerKeyFromApibase(apibase: string): string | null {
  const lower = (apibase || '').toLowerCase();
  if (lower.includes('deepseek')) return 'deepseek';
  if (lower.includes('dashscope') || lower.includes('qwen')) return 'qwen';
  if (lower.includes('anthropic')) return 'anthropic';
  if (lower.includes('openai')) return 'openai';
  if (lower.includes('openrouter')) return 'openrouter';
  if (lower.includes('google')) return 'google';
  if (lower.includes('moonshot')) return 'moonshot';
  if (lower.includes('volces') || lower.includes('volcengine')) return 'doubao';
  if (lower.includes('minimax')) return 'minimax';
  if (lower.includes('bigmodel') || lower.includes('zhipu')) return 'zhipu';
  if (lower.includes('stepfun')) return 'stepfun';
  return null;
}

interface GroupedProfiles {
  provider: string;
  color: string;
  items: { profile: ModelProfile; idx: number }[];
}

function groupByProvider(profiles: ModelProfile[]): { groups: GroupedProfiles[]; mixins: { profile: ModelProfile; idx: number }[] } {
  const mixins: { profile: ModelProfile; idx: number }[] = [];
  const map = new Map<string, GroupedProfiles>();

  profiles.forEach((p, idx) => {
    if (p.kind === 'mixin') {
      mixins.push({ profile: p, idx });
      return;
    }
    const provider = providerName(p.apibase, p.model);
    if (!map.has(provider)) {
      map.set(provider, { provider, color: providerColor(p.apibase, p.model), items: [] });
    }
    map.get(provider)!.items.push({ profile: p, idx });
  });

  return { groups: Array.from(map.values()), mixins };
}

interface ModelSelectorProps {
  selectedNo?: number;
  runningNo?: number | null;
  isRunning?: boolean;
  onSelect?: (no: number) => void | Promise<void>;
}

export function ModelSelector({
  selectedNo: controlledSelectedNo,
  runningNo: controlledRunningNo,
  isRunning: controlledIsRunning,
  onSelect,
}: ModelSelectorProps = {}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [expandedMixin, setExpandedMixin] = useState<number | null>(null);
  const [isCompact, setIsCompact] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const { lang, t } = useI18n();

  const profiles = useSettingsStore((s) => s.modelProfiles);
  const defaultModelNo = useSettingsStore((s) => s.defaultModelNo);
  const liveModel = useSettingsStore((s) => s.liveModel);
  const sessionModelNo = useChatStore((s) => s.sessionModelNo);
  const sessionStatus = useChatStore((s) => s.status);
  const selectSessionModel = useChatStore((s) => s.selectSessionModel);

  const selectedNo = controlledSelectedNo ?? sessionModelNo ?? defaultModelNo;
  const runningNo = controlledRunningNo !== undefined
    ? controlledRunningNo
    : liveModel?.runningLlmNo;
  const isRunning = controlledIsRunning ?? sessionStatus === 'running';
  const isLoading = profiles.length === 0;
  const currentProfile = profiles[selectedNo];

  const chipLabel = useMemo(() => {
    if (!currentProfile) return t('model.menuLabel');
    if (isRunning && runningNo != null && runningNo !== selectedNo) {
      return formatModelSelectionLabel(profiles, selectedNo, runningNo, true);
    }
    if (currentProfile.kind === 'mixin') {
      return t('model.aggregationShort');
    }
    return modelShortName(currentProfile);
  }, [currentProfile, isRunning, profiles, runningNo, selectedNo, t]);

  const { groups, mixins } = useMemo(() => groupByProvider(profiles), [profiles]);

  const filteredGroups = useMemo(() => {
    if (!search.trim()) return groups;
    const q = search.toLowerCase();
    return groups
      .map((g) => ({
        ...g,
        items: g.items.filter(
          ({ profile: p }) =>
            modelShortName(p).toLowerCase().includes(q) ||
            (p.model || '').toLowerCase().includes(q) ||
            g.provider.toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.items.length > 0);
  }, [groups, search]);

  const toggle = useCallback(() => {
    setOpen((v) => {
      if (!v) setSearch('');
      return !v;
    });
  }, []);

  const handleSelect = useCallback((idx: number) => {
    if (onSelect) onSelect(idx);
    else selectSessionModel(idx);
    setOpen(false);
  }, [onSelect, selectSessionModel]);

  useEffect(() => {
    if (open && searchRef.current) {
      searchRef.current.focus();
    }
  }, [open]);

  // Compact mode: observe toolbar width
  useEffect(() => {
    const toolbar = wrapRef.current?.closest('[data-slot="composer-toolbar"]') as HTMLElement | null;
    if (!toolbar) return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect?.width ?? toolbar.offsetWidth;
      setIsCompact(width < 320);
    });
    observer.observe(toolbar);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node) &&
          btnRef.current && !btnRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onClickOutside);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onClickOutside);
      document.removeEventListener('keydown', onEsc);
    };
  }, [open]);

  useEffect(() => {
    function onHotkey(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key >= '1' && e.key <= '9') {
        const idx = parseInt(e.key) - 1;
        if (idx < profiles.length) {
          e.preventDefault();
          selectSessionModel(idx);
        }
      }
    }
    document.addEventListener('keydown', onHotkey);
    return () => document.removeEventListener('keydown', onHotkey);
  }, [profiles, selectSessionModel]);

  const handleOpenSettings = useCallback(() => {
    setOpen(false);
    useSettingsStore.getState().open();
  }, []);

  return (
    <div ref={wrapRef} data-slot="model-selector">
      <button
        ref={btnRef}
        data-slot="model-chip"
        data-loading={isLoading ? '' : undefined}
        data-open={open ? '' : undefined}
        onClick={toggle}
        title={currentProfile
          ? currentProfile.kind === 'mixin'
            ? t('model.aggregation')
            : `${currentProfile.model}${currentProfile.apibase ? ' @ ' + currentProfile.apibase : ''}`
          : t('model.menuLabel')}
      >
        {isLoading ? (
          <span data-slot="model-chip-spinner"><span /></span>
        ) : (
          <>
            {!isCompact && <span data-slot="model-chip-label">{chipLabel}</span>}
            <span data-slot="model-chip-caret" data-open={open ? '' : undefined}>
              <CaretIcon />
            </span>
          </>
        )}
      </button>

      {open && !isLoading && (
        <div ref={menuRef} data-slot="model-menu">
          {/* Search */}
          <div data-slot="model-menu-search">
            <SearchIcon />
            <input
              ref={searchRef}
              type="text"
              placeholder={t('model.menuLabel')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-slot="model-menu-search-input"
            />
          </div>

          <div data-slot="model-menu-body">
            {/* Provider groups */}
            {filteredGroups.map((group) => (
              <div key={group.provider} data-slot="model-menu-section">
                <div data-slot="model-menu-section-header">
                  <ProviderIcon apibase={group.items[0]?.profile.apibase || ''} model={group.items[0]?.profile.model} />
                  {group.provider}
                </div>
                {group.items.map(({ profile: p, idx }) => (
                  <button
                    key={p.id}
                    data-slot="model-menu-item"
                    data-active={idx === selectedNo ? '' : undefined}
                    onClick={() => handleSelect(idx)}
                    title={`${p.model}${p.apibase ? ' @ ' + p.apibase : ''}`}
                  >
                    {idx === selectedNo && <span data-slot="model-check">✓</span>}
                    <span data-slot="model-menu-name">{modelShortName(p)}</span>
                  </button>
                ))}
              </div>
            ))}

            {/* Mixin section */}
            {mixins.length > 0 && (
              <div data-slot="model-menu-section">
                <div data-slot="model-menu-section-header">
                  {t('model.aggregationShort').toUpperCase()}
                </div>
                {mixins.map(({ profile: p, idx }) => {
                  const isExpanded = expandedMixin === idx;
                  const label = p.name?.trim() || t('model.aggregationShort');
                  return (
                    <div key={p.id} data-slot="model-menu-group">
                      <button
                        data-slot="model-menu-item"
                        data-active={idx === selectedNo ? '' : undefined}
                        onClick={() => handleSelect(idx)}
                        title={t('model.aggregationDesc')}
                      >
                        {idx === selectedNo && <span data-slot="model-check">✓</span>}
                        <span data-slot="model-menu-name">{label}</span>
                        {p.members && p.members.length > 0 && (
                          <span
                            data-slot="mixin-caret"
                            data-expanded={isExpanded ? '' : undefined}
                            onClick={(e) => { e.stopPropagation(); setExpandedMixin(isExpanded ? null : idx); }}
                          >
                            <CaretIcon />
                          </span>
                        )}
                      </button>
                      {isExpanded && p.members && (
                        <div data-slot="mixin-members">
                          {p.members.map((memberName) => {
                            const member = profiles.find((pp) => pp.name === memberName);
                            return (
                              <div key={memberName} data-slot="mixin-member">
                                <ProviderIcon apibase={member?.apibase || ''} model={member?.model} size={12} />
                                <span data-slot="model-menu-name">{member ? modelShortName(member) : String(memberName)}</span>
                              </div>
                            );
                          })}
                          {p.members.length === 0 && (
                            <div data-slot="mixin-member" style={{ opacity: 0.5 }}>
                              {t('model.emptyMixin')}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {/* Empty state */}
            {filteredGroups.length === 0 && mixins.length === 0 && (
              <div data-slot="model-menu-empty">{t('set.noModels')}</div>
            )}
          </div>

          {/* Footer actions */}
          <div data-slot="model-menu-footer">
            <button data-slot="model-menu-action" onClick={handleOpenSettings}>
              {lang === 'zh' ? '编辑模型…' : 'Edit models…'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function CaretIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
      <path d="M2.5 3.5L5 6.5L7.5 3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true" data-slot="model-menu-search-icon">
      <path d="M7 12A5 5 0 107 2a5 5 0 000 10zM14 14l-3.5-3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
