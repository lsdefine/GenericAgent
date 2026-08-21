import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

const windowApi = {
  minimize: vi.fn().mockResolvedValue(undefined),
  toggleMaximize: vi.fn().mockResolvedValue(undefined),
  close: vi.fn().mockResolvedValue(undefined),
  startDragging: vi.fn().mockResolvedValue(undefined),
};

function installWindowsTauri() {
  Object.defineProperty(navigator, 'platform', { value: 'Win32', configurable: true });
  Object.defineProperty(navigator, 'userAgentData', { value: undefined, configurable: true });
  delete document.documentElement.dataset.platform;
  (window as any).__TAURI__ = {
    window: { getCurrentWindow: () => windowApi },
    event: { listen: vi.fn().mockResolvedValue(() => {}) },
    core: { invoke: vi.fn().mockResolvedValue(null) },
  };
}

function expectWindowButtons() {
  expect(screen.getByRole('button', { name: 'Minimize' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Maximize' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy();
}

async function importAppLayout() {
  vi.doMock('../stores/app', () => ({
    useAppStore: (selector: (state: any) => unknown) =>
      selector({ sidebarCollapsed: false, toggleSidebar: vi.fn() }),
  }));
  vi.doMock('../components/layout/LeftSidebar', () => ({ LeftSidebar: () => null }));
  vi.doMock('../components/layout/MainArea', () => ({ MainArea: () => null }));
  vi.doMock('../components/layout/Statusbar', () => ({ Statusbar: () => null }));
  vi.doMock('../components/layout/TitlebarControls', () => ({ TitlebarControls: () => null }));
  vi.doMock('../components/layout/ShortcutPrompt', () => ({ ShortcutPrompt: () => null }));
  vi.doMock('@douyinfe/semi-ui', () => ({
    ResizeGroup: ({ children }: any) => <div>{children}</div>,
    ResizeItem: ({ children }: any) => <div>{children}</div>,
    ResizeHandler: () => null,
  }));

  return import('../components/layout/AppLayout');
}

describe('Windows window chrome', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    installWindowsTauri();
  });

  afterEach(() => {
    cleanup();
    delete (window as any).__TAURI__;
    delete document.documentElement.dataset.platform;
  });

  it('renders window controls in the main application before data-platform is pre-seeded', async () => {
    const { AppLayout } = await importAppLayout();
    render(<AppLayout />);

    expectWindowButtons();
    expect(document.documentElement.dataset.platform).toBe('windows');
  });

  it('routes titlebar drag and button actions to the current Tauri window', async () => {
    const { AppLayout } = await importAppLayout();
    render(<AppLayout />);

    fireEvent.mouseDown(screen.getByTestId('windows-titlebar'), { button: 0 });
    fireEvent.click(screen.getByRole('button', { name: 'Minimize' }));
    fireEvent.click(screen.getByRole('button', { name: 'Maximize' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    expect(windowApi.startDragging).toHaveBeenCalledOnce();
    expect(windowApi.minimize).toHaveBeenCalledOnce();
    expect(windowApi.toggleMaximize).toHaveBeenCalledOnce();
    expect(windowApi.close).toHaveBeenCalledOnce();
  });

  it('renders window controls while the loading application is visible', async () => {
    const { LoadingApp } = await import('../loading/App');
    render(<LoadingApp />);

    expectWindowButtons();
  });

  it('grants the commands used by the three window buttons', async () => {
    const { default: capability } = await import('../../src-tauri/capabilities/default.json');

    expect(capability.permissions).toEqual(expect.arrayContaining([
      'core:window:allow-minimize',
      'core:window:allow-toggle-maximize',
      'core:window:allow-close',
      'core:window:allow-start-dragging',
    ]));
  });

  it('keeps the Windows sidebar nav directly below the custom titlebar', () => {
    const layoutCss = fs.readFileSync(
      path.join(desktopRoot, 'src/components/layout/layout.css'),
      'utf8',
    );

    expect(layoutCss).toMatch(
      /:root\[data-platform="windows"\]\s*{[^}]*--ga-sidebar-top-padding:\s*8px;/s,
    );
    expect(layoutCss).toMatch(
      /\.ga-left-sidebar\s*{[^}]*padding:\s*var\(--ga-sidebar-top-padding,\s*36px\) 0 0;/s,
    );
  });

  it.each(['MacIntel', 'Linux x86_64'])(
    'does not render Windows controls for %s inside Tauri',
    async (platform) => {
      cleanup();
      vi.resetModules();
      Object.defineProperty(navigator, 'platform', { value: platform, configurable: true });
      (window as any).__TAURI__ = {
        window: { getCurrentWindow: () => windowApi },
        event: { listen: vi.fn().mockResolvedValue(() => {}) },
        core: { invoke: vi.fn().mockResolvedValue(null) },
      };

      const { LoadingApp } = await import('../loading/App');
      render(<LoadingApp />);

      expect(screen.queryByTestId('windows-titlebar')).toBeNull();
    },
  );

  it('does not render Windows controls in an ordinary browser', async () => {
    cleanup();
    vi.resetModules();
    delete (window as any).__TAURI__;
    Object.defineProperty(navigator, 'platform', { value: 'Win32', configurable: true });

    const { LoadingApp } = await import('../loading/App');
    render(<LoadingApp />);

    expect(screen.queryByTestId('windows-titlebar')).toBeNull();
  });
});
