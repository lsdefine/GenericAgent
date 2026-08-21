import { useRef, useEffect, useState } from 'react';
import { useSettingsStore } from '../../../stores/settings';
import { BUILTIN_SKILLS, type SkillDef } from './skills';

interface Props {
  visible: boolean;
  query: string;
  onSelect: (id: string, prompt: string) => void;
  onClose: () => void;
}

function getCustomCompletions(): SkillDef[] {
  try {
    const raw = localStorage.getItem('ga_custom_presets');
    if (!raw) return [];
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

export function CompletionDrawer({ visible, query, onSelect, onClose }: Props) {
  const lang = useSettingsStore((s) => s.lang);
  const [focusIdx, setFocusIdx] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);

  const customs = getCustomCompletions();
  const allItems = [...BUILTIN_SKILLS, ...customs];

  const filtered = query
    ? allItems.filter((item) =>
        item.id.startsWith(query.toLowerCase()) ||
        item.title.toLowerCase().includes(query.toLowerCase())
      )
    : allItems;

  useEffect(() => {
    setFocusIdx(0);
  }, [query]);

  useEffect(() => {
    if (!visible) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setFocusIdx((v) => Math.min(v + 1, filtered.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setFocusIdx((v) => Math.max(v - 1, 0));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filtered[focusIdx]) {
          onSelect(filtered[focusIdx].id, filtered[focusIdx].prompt);
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [visible, focusIdx, filtered, onSelect, onClose]);

  useEffect(() => {
    if (!panelRef.current) return;
    const focused = panelRef.current.querySelector('[data-focused]');
    focused?.scrollIntoView({ block: 'nearest' });
  }, [focusIdx]);

  if (!visible || filtered.length === 0) return null;

  return (
    <div ref={panelRef} data-slot="completion-drawer">
      {filtered.map((item, i) => (
        <button
          key={item.id}
          data-slot="completion-item"
          data-focused={i === focusIdx ? '' : undefined}
          onClick={() => onSelect(item.id, item.prompt)}
          onMouseEnter={() => setFocusIdx(i)}
        >
          <span data-slot="completion-info">
            <span data-slot="completion-title">/{item.id}</span>
            <span data-slot="completion-desc">{item.desc[lang] || item.desc.en}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
