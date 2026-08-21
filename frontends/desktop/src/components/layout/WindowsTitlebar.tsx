import type { MouseEvent } from 'react';
import { WindowControls } from './WindowControls';
import './windowChrome.css';

export function WindowsTitlebar() {
  const handleMouseDown = (event: MouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('button, a, input, [data-no-drag]')) return;
    event.preventDefault();
    (window as any).__TAURI__?.window?.getCurrentWindow?.()?.startDragging?.();
  };

  return (
    <div
      className="ga-win-titlebar"
      data-testid="windows-titlebar"
      onMouseDown={handleMouseDown}
    >
      <WindowControls />
    </div>
  );
}
