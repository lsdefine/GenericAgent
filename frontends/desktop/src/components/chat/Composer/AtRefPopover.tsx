import { useRef, useEffect, useState, useCallback } from 'react';

interface Props {
  visible: boolean;
  query: string;
  onConfirm: (kind: string, value: string) => void;
  onClose: () => void;
}

const KINDS = [
  { id: 'file', label: 'file' },
  { id: 'url', label: 'url' },
  { id: 'image', label: 'image' },
];

export function AtRefPopover({ visible, query, onConfirm, onClose }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState('file');
  const [value, setValue] = useState('');

  useEffect(() => {
    if (visible) {
      setValue(query);
      setKind('file');
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [visible, query]);

  useEffect(() => {
    if (!visible) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [visible, onClose]);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    onConfirm(kind, trimmed);
  }, [kind, value, onConfirm]);

  if (!visible) return null;

  return (
    <div data-slot="at-ref-popover">
      <form onSubmit={handleSubmit} data-slot="at-ref-form">
        <div data-slot="at-ref-kinds">
          {KINDS.map((k) => (
            <button
              key={k.id}
              type="button"
              data-slot="at-ref-kind-btn"
              data-active={k.id === kind ? '' : undefined}
              onClick={() => setKind(k.id)}
              title={k.label}
            >
              <KindIcon kind={k.id} />
            </button>
          ))}
        </div>
        <input
          ref={inputRef}
          data-slot="at-ref-input"
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={kind === 'url' ? 'https://...' : 'path/to/file'}
        />
        <button type="submit" data-slot="at-ref-confirm" disabled={!value.trim()}>
          ↵
        </button>
      </form>
    </div>
  );
}

function KindIcon({ kind }: { kind: string }) {
  switch (kind) {
    case 'file':
      return (
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
          <path d="M4 2h5l4 4v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" stroke="currentColor" strokeWidth="1.2"/>
          <path d="M9 2v4h4" stroke="currentColor" strokeWidth="1.2"/>
        </svg>
      );
    case 'url':
      return (
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
          <path d="M6.5 9.5l3-3M7 11l-1.5 1.5a2.12 2.12 0 1 1-3-3L4 8m5-3l1.5-1.5a2.12 2.12 0 1 1 3 3L12 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
        </svg>
      );
    case 'image':
      return (
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
          <rect x="2" y="2" width="12" height="12" rx="1" stroke="currentColor" strokeWidth="1.2"/>
          <circle cx="5.5" cy="5.5" r="1" fill="currentColor"/>
          <path d="M2 11l3-3 2 2 3-3 4 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
        </svg>
      );
    default:
      return null;
  }
}
