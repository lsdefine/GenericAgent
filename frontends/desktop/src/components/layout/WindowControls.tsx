export function WindowControls() {
  const win = (window as any).__TAURI__?.window?.getCurrentWindow?.();
  if (!win) return null;

  return (
    <div className="ga-win-controls" data-no-drag>
      <button
        type="button"
        className="ga-win-btn"
        onClick={() => win.minimize()}
        aria-label="Minimize"
      >
        <svg width="10" height="1" viewBox="0 0 10 1">
          <rect fill="currentColor" width="10" height="1" />
        </svg>
      </button>
      <button
        type="button"
        className="ga-win-btn"
        onClick={() => win.toggleMaximize()}
        aria-label="Maximize"
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
          <rect x="0.5" y="0.5" width="9" height="9" stroke="currentColor" strokeWidth="1" />
        </svg>
      </button>
      <button
        type="button"
        className="ga-win-btn ga-win-btn--close"
        onClick={() => win.close()}
        aria-label="Close"
      >
        <svg width="10" height="10" viewBox="0 0 10 10">
          <path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      </button>
    </div>
  );
}
