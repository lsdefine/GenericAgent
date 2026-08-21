export function isTauri(): boolean {
  return typeof (window as any).__TAURI__ !== 'undefined';
}

export async function invokeStartBridge(): Promise<void> {
  const invoke = (window as any).__TAURI__?.core?.invoke;
  if (!invoke) throw new Error('Not in Tauri environment');
  await invoke('start_bridge');
}
