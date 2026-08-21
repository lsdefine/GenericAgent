import { useState, useRef, useEffect, useCallback } from 'react';
import { useSettingsStore } from '../../../stores/settings';

interface Props {
  onUploadFile: () => void;
  onUploadImage: () => void;
  onPasteImage: () => void;
}

const LABELS = {
  title: { zh: '附加', en: 'Attach' },
  file: { zh: '文件…', en: 'File…' },
  image: { zh: '图片…', en: 'Image…' },
  paste: { zh: '粘贴图片', en: 'Paste image' },
  hint: { zh: '提示：输入 @ 以内联引用文件', en: 'Tip: type @ to reference files inline' },
};

export function ContextMenu({ onUploadFile, onUploadImage, onPasteImage }: Props) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const lang = useSettingsStore((s) => s.lang);

  const t = (key: keyof typeof LABELS) => LABELS[key][lang] || LABELS[key].en;

  const toggle = useCallback(() => setOpen((v) => !v), []);

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

  const act = useCallback((fn: () => void) => () => {
    fn();
    setOpen(false);
  }, []);

  return (
    <div data-slot="context-menu-wrap">
      <button
        ref={btnRef}
        data-slot="composer-attach-btn"
        onClick={toggle}
        aria-label={t('title')}
        title={t('title')}
      >
        <PlusIcon />
      </button>

      {open && (
        <div ref={menuRef} data-slot="context-menu">
          <div data-slot="context-menu-title">{t('title')}</div>
          <button data-slot="context-menu-item" onClick={act(onUploadFile)}>
            <span data-slot="context-menu-icon"><FileIcon /></span>
            <span data-slot="context-menu-label">{t('file')}</span>
          </button>
          <button data-slot="context-menu-item" onClick={act(onUploadImage)}>
            <span data-slot="context-menu-icon"><ImageIcon /></span>
            <span data-slot="context-menu-label">{t('image')}</span>
          </button>
          <button data-slot="context-menu-item" onClick={act(onPasteImage)}>
            <span data-slot="context-menu-icon"><ClipboardIcon /></span>
            <span data-slot="context-menu-label">{t('paste')}</span>
          </button>
          <div data-slot="context-menu-hint">{t('hint')}</div>
        </div>
      )}
    </div>
  );
}

function PlusIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <path d="M4 2h5l4 4v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" stroke="currentColor" strokeWidth="1.2"/>
      <path d="M9 2v4h4" stroke="currentColor" strokeWidth="1.2"/>
    </svg>
  );
}

function ImageIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <rect x="2" y="2" width="12" height="12" rx="1" stroke="currentColor" strokeWidth="1.2"/>
      <circle cx="5.5" cy="5.5" r="1" fill="currentColor"/>
      <path d="M2 11l3-3 2 2 3-3 4 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
    </svg>
  );
}

function ClipboardIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <rect x="3" y="2" width="10" height="12" rx="1" stroke="currentColor" strokeWidth="1.2"/>
      <path d="M6 2V1.5A.5.5 0 0 1 6.5 1h3a.5.5 0 0 1 .5.5V2" stroke="currentColor" strokeWidth="1.2"/>
    </svg>
  );
}
