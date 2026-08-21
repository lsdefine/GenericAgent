import { useState, useRef, useEffect, useCallback } from 'react';
import { useSettingsStore } from '../../../stores/settings';
import { BUILTIN_SKILLS, type SkillDef } from './skills';

const CUSTOM_PRESETS_KEY = 'ga_custom_presets';

function getCustomPresets(): SkillDef[] {
  try {
    const raw = localStorage.getItem(CUSTOM_PRESETS_KEY);
    if (!raw) return [];
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

const LABELS = {
  hint: { zh: '提示：输入 / 以内联调用技能', en: 'Tip: type / to invoke a skill inline' },
};


interface Props {
  onSelect: (id: string, prompt: string) => void;
}

export function SkillPanel({ onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [focusIdx, setFocusIdx] = useState(-1);
  const panelRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const lang = useSettingsStore((s) => s.lang);

  const customs = getCustomPresets();
  const allItems = [...BUILTIN_SKILLS, ...customs];

  const toggle = useCallback(() => {
    setOpen((v) => !v);
    setFocusIdx(-1);
  }, []);

  const handleSelect = useCallback((id: string, prompt: string) => {
    onSelect(id, prompt);
    setOpen(false);
  }, [onSelect]);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node) &&
          btnRef.current && !btnRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKeydown(e: KeyboardEvent) {
      if (e.key === 'Escape') { setOpen(false); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); setFocusIdx((v) => Math.min(v + 1, allItems.length - 1)); }
      if (e.key === 'ArrowUp') { e.preventDefault(); setFocusIdx((v) => Math.max(v - 1, 0)); }
      if (e.key === 'Enter' && focusIdx >= 0 && focusIdx < allItems.length) {
        e.preventDefault();
        handleSelect(allItems[focusIdx].id, allItems[focusIdx].prompt);
      }
    }
    document.addEventListener('mousedown', onClickOutside);
    document.addEventListener('keydown', onKeydown);
    return () => {
      document.removeEventListener('mousedown', onClickOutside);
      document.removeEventListener('keydown', onKeydown);
    };
  }, [open, focusIdx, allItems, handleSelect]);

  return (
    <div data-slot="skill-wrap">
      <button
        ref={btnRef}
        data-slot="skill-trigger"
        onClick={toggle}
        aria-label="Presets"
        title="Prompt presets"
      >
        <SkillIcon />
      </button>

      {open && (
        <div ref={panelRef} data-slot="skill-panel">
          <div data-slot="skill-section">
            <div data-slot="skill-section-title">Presets</div>
            {BUILTIN_SKILLS.map((s, i) => (
              <button
                key={s.id}
                data-slot="skill-item"
                data-focused={focusIdx === i ? '' : undefined}
                onClick={() => handleSelect(s.id, s.prompt)}
                onMouseEnter={() => setFocusIdx(i)}
              >
                <span data-slot="skill-info">
                  <span data-slot="skill-name">{s.title}</span>
                  <span data-slot="skill-desc">{s.desc[lang] || s.desc.en}</span>
                </span>
              </button>
            ))}
          </div>
          {customs.length > 0 && (
            <div data-slot="skill-section">
              <div data-slot="skill-section-title">Custom</div>
              {customs.map((s, i) => (
                <button
                  key={s.id}
                  data-slot="skill-item"
                  data-focused={focusIdx === BUILTIN_SKILLS.length + i ? '' : undefined}
                  onClick={() => handleSelect(s.id, s.prompt)}
                  onMouseEnter={() => setFocusIdx(BUILTIN_SKILLS.length + i)}
                >
                  <span data-slot="skill-info">
                    <span data-slot="skill-name">{s.title}</span>
                    <span data-slot="skill-desc">{s.desc[lang] || s.desc.en}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
          <div data-slot="skill-panel-hint">{LABELS.hint[lang] || LABELS.hint.en}</div>
        </div>
      )}
    </div>
  );
}

function SkillIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true">
      <path d="M215.79 118.17a8 8 0 0 0-5-5.66L153.18 90.9l14.66-73.33a8 8 0 0 0-13.69-7l-112 120a8 8 0 0 0 3 13.05l57.63 21.61-14.62 73.12a8 8 0 0 0 13.69 7l112-120a8 8 0 0 0 1.94-7.18Z" />
    </svg>
  );
}
