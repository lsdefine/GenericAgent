export type AppPlatform = 'windows' | 'macos' | 'linux' | 'web';

function detectPlatform(): AppPlatform {
  if (!(window as any).__TAURI__) return 'web';

  const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
  const raw = `${nav.userAgentData?.platform || navigator.platform || navigator.userAgent || ''}`.toLowerCase();
  if (raw.includes('win')) return 'windows';
  if (raw.includes('mac')) return 'macos';
  if (raw.includes('linux')) return 'linux';
  return 'web';
}

export const appPlatform = detectPlatform();
export const isWindows = appPlatform === 'windows';
export const isMacOS = appPlatform === 'macos';

if (appPlatform !== 'web') {
  document.documentElement.dataset.platform = appPlatform;
}
