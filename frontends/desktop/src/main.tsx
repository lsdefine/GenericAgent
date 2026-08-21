import './platform';
import '@semi-css';
import './global.css';
import './stores/bridgeActivity';

if (document.documentElement.dataset.appearance === 'dark') {
  document.body.setAttribute('theme-mode', 'dark');
}

if ((window as any).__TAURI__) {
  document.addEventListener('click', (e) => {
    const anchor = (e.target as HTMLElement).closest('a[href]') as HTMLAnchorElement | null;
    if (!anchor) return;
    const href = anchor.href;
    if (!href || href.startsWith('javascript:')) return;
    const url = new URL(href, location.href);
    if (url.origin === location.origin) return;
    e.preventDefault();
    (window as any).__TAURI__.opener.openUrl(href);
  });
}

setTimeout(() => {
  document.body.classList.remove('no-transition');
}, 0);

import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';

class RootErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[RootErrorBoundary] React crashed:', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <pre style={{ padding: 24, color: 'red', whiteSpace: 'pre-wrap' }}>
          {this.state.error.message}
          {'\n\n'}
          {this.state.error.stack}
        </pre>
      );
    }
    return this.props.children;
  }
}

async function renderApp() {
  if (import.meta.env.VITE_GA_E2E === '1') {
    await import('@wdio/tauri-plugin');
  }
  const appRoot = document.getElementById('app')!;
  createRoot(appRoot).render(
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>,
  );
}

void renderApp();
