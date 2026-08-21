import { useCallback } from 'react';
import { ResizeGroup, ResizeItem, ResizeHandler } from '@douyinfe/semi-ui';
import { LeftSidebar } from './LeftSidebar';
import { MainArea } from './MainArea';
import { Statusbar } from './Statusbar';
import { TitlebarControls } from './TitlebarControls';
import { WindowsTitlebar } from './WindowsTitlebar';
import { ShortcutPrompt } from './ShortcutPrompt';
import { useAppStore } from '../../stores/app';
import { isMacOS, isWindows } from '../../platform';
import './layout.css';

function useDragWindow() {
  return useCallback((e: React.MouseEvent) => {
    if (!isMacOS) return;
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest('button, a, input, [data-no-drag]')) return;
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const y = e.clientY - rect.top;
    if (y > 38) return;
    e.preventDefault();
    const tauri = (window as any).__TAURI__;
    tauri?.window?.getCurrentWindow?.()?.startDragging?.();
  }, []);
}

export function AppLayout() {
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed);
  const onDrag = useDragWindow();

  return (
    <div className="ga-app-layout" onMouseDown={onDrag}>
      {isWindows && (
        <WindowsTitlebar />
      )}
      <TitlebarControls />
      <div className="ga-app-body">
        {sidebarCollapsed ? (
          <div className="ga-body-collapsed">
            <MainArea />
          </div>
        ) : (
          <ResizeGroup direction="horizontal">
            <ResizeItem
              defaultSize="260px"
              min="200px"
              max="340px"
              className="ga-sidebar-item"
            >
              <LeftSidebar />
            </ResizeItem>
            <ResizeHandler />
            <ResizeItem className="ga-main-item">
              <MainArea />
            </ResizeItem>
          </ResizeGroup>
        )}
      </div>
      <Statusbar />
      <ShortcutPrompt />
    </div>
  );
}
