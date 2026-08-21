import { useEffect } from 'react';
import { Codicon } from '../../lib/icons';
import { useAppStore } from '../../stores/app';

export function TitlebarControls() {
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault();
        toggleSidebar();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggleSidebar]);

  return (
    <div className="ga-titlebar-controls">
      <button
        type="button"
        className="ga-titlebar-btn"
        onClick={toggleSidebar}
        title={sidebarCollapsed ? '显示侧边栏' : '隐藏侧边栏'}
        aria-label={sidebarCollapsed ? '显示侧边栏' : '隐藏侧边栏'}
      >
        <Codicon
          name={sidebarCollapsed ? 'layout-sidebar-left-off' : 'layout-sidebar-left'}
          size="16px"
        />
      </button>
    </div>
  );
}
