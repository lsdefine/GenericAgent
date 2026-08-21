import { useState } from 'react';
import { Codicon } from '../../lib/icons';

export function SessionSectionHeader({
  label,
  count,
  open: controlledOpen,
  onToggle,
  onAction,
  defaultOpen = true,
}: {
  label: string;
  count: number;
  open?: boolean;
  onToggle?: (open: boolean) => void;
  onAction?: () => void;
  defaultOpen?: boolean;
}) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isOpen = controlledOpen ?? internalOpen;

  function toggle() {
    const next = !isOpen;
    setInternalOpen(next);
    onToggle?.(next);
  }

  function handleAction(e: React.MouseEvent) {
    e.stopPropagation();
    onAction?.();
  }

  return (
    <div className="ga-section-header" onClick={toggle}>
      <span className="ga-section-dot" />
      <span className="ga-section-label">{label}</span>
      <span className="ga-section-count">{count}</span>
      <span className={`ga-section-chevron${isOpen ? ' open' : ''}`}>
        <Codicon name="chevron-right" size="0.625rem" />
      </span>
      {onAction && (
        <button type="button" className="ga-section-action" onClick={handleAction}>
          <Codicon name="add" size="0.75rem" />
        </button>
      )}
    </div>
  );
}
