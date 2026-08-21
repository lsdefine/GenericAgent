import { BRIDGE_BASE } from './constants';

export interface AppConfig {
  lang: 'zh' | 'en';
  theme: string;
  appearance: 'light' | 'dark';
  plain: boolean;
  fontSize: number;
  llmNo: number;
}

export interface ModelProfile {
  id: number;
  name: string;
  model: string;
  apibase: string;
  apikey?: string;
  protocol: 'oai' | 'claude';
  stream: boolean;
  max_retries?: number;
  connect_timeout?: number;
  read_timeout?: number;
  kind?: 'mixin';
  members?: string[];
  inMixin?: boolean;
}

interface GaApi {
  getConfig: () => Promise<{ config: AppConfig }>;
  saveConfig: (cfg: { config: Partial<AppConfig> }) => Promise<void>;
  getModelProfiles: () => Promise<{ profiles: ModelProfile[] }>;
  rpc: (method: string, params: Record<string, unknown>) => Promise<unknown>;
  getMykeyContent: () => Promise<{ content: string }>;
  saveMykeyContent: (content: string) => Promise<void>;
  tauriInvoke: (cmd: string, args: Record<string, unknown>) => Promise<unknown>;
}

// ── Tauri IPC — direct access to Rust commands ──
function getTauriInvoke(): ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>) | null {
  return (window as any).__TAURI__?.core?.invoke || null;
}

// ── Dev-mode HTTP fallback ──
// When window.ga is not available (browser dev server without Tauri shell),
// call the backend REST API directly.
const DEV_BACKEND = BRIDGE_BASE;

async function devFetch(path: string, opts?: RequestInit): Promise<unknown> {
  const res = await fetch(`${DEV_BACKEND}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    let msg = `${res.status} ${res.statusText}`;
    try { const j = JSON.parse(body); msg = j.error || j.message || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function ga(): GaApi | null {
  const w = window as unknown as { ga?: GaApi };
  return w.ga || null;
}

function isBridgeAvailable(): boolean {
  return !!ga();
}

export async function getConfig(): Promise<AppConfig> {
  if (isBridgeAvailable()) {
    try {
      const res = await ga()!.getConfig();
      return res.config;
    } catch { /* fall through */ }
  }
  try {
    const res = await devFetch('/config') as { config: AppConfig };
    return res.config;
  } catch {
    return {
      lang: (localStorage.getItem('ga_lang') as 'zh' | 'en') || 'zh',
      theme: 'light',
      appearance: (localStorage.getItem('ga_appearance') as 'light' | 'dark') || 'light',
      plain: false,
      fontSize: parseInt(localStorage.getItem('ga_font_size') || '14', 10),
      llmNo: 0,
    };
  }
}

export async function saveConfig(config: Partial<AppConfig>): Promise<void> {
  if (isBridgeAvailable()) {
    try { await ga()!.saveConfig({ config }); return; } catch { /* fall through */ }
  }
  try {
    await devFetch('/config', { method: 'POST', body: JSON.stringify({ config }) });
  } catch {}
}

export async function getModelProfiles(): Promise<ModelProfile[]> {
  if (isBridgeAvailable()) {
    try {
      const res = await ga()!.getModelProfiles();
      return res.profiles || [];
    } catch { /* fall through */ }
  }
  try {
    const res = await devFetch('/model-profiles') as { profiles: ModelProfile[] };
    return res.profiles || [];
  } catch {
    return [];
  }
}

export async function getModelProfileDetail(id: number): Promise<ModelProfile | null> {
  if (isBridgeAvailable()) {
    try {
      const res = await ga()!.rpc('model-profiles/get', { id }) as { profile: ModelProfile };
      return res.profile || null;
    } catch { /* fall through */ }
  }
  try {
    const res = await devFetch(`/model-profiles/${id}`) as { profile: ModelProfile };
    return res.profile || null;
  } catch {
    return null;
  }
}

export async function addModelProfile(data: Partial<ModelProfile>): Promise<ModelProfile[]> {
  if (isBridgeAvailable()) {
    const res = await ga()!.rpc('model-profiles/add', data) as { profiles: ModelProfile[] };
    return res.profiles;
  }
  const res = await devFetch('/model-profiles', {
    method: 'POST',
    body: JSON.stringify(data),
  }) as { profiles: ModelProfile[] };
  return res.profiles;
}

export async function editModelProfile(id: number, data: Partial<ModelProfile>): Promise<ModelProfile[]> {
  if (isBridgeAvailable()) {
    const res = await ga()!.rpc('model-profiles/edit', { id, ...data }) as { profiles: ModelProfile[] };
    return res.profiles;
  }
  const res = await devFetch(`/model-profiles/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }) as { profiles: ModelProfile[] };
  return res.profiles;
}

export async function deleteModelProfile(id: number): Promise<ModelProfile[]> {
  if (isBridgeAvailable()) {
    const res = await ga()!.rpc('model-profiles/delete', { id }) as { profiles: ModelProfile[] };
    return res.profiles;
  }
  const res = await devFetch(`/model-profiles/${id}`, {
    method: 'DELETE',
  }) as { profiles: ModelProfile[] };
  return res.profiles;
}

export async function addToMixin(id: number): Promise<ModelProfile[]> {
  if (isBridgeAvailable()) {
    const res = await ga()!.rpc('model-profiles/mixin-add', { id }) as { profiles: ModelProfile[] };
    return res.profiles;
  }
  const res = await devFetch(`/model-profiles/${id}/mixin`, {
    method: 'POST',
    body: '{}',
  }) as { profiles: ModelProfile[] };
  return res.profiles;
}

export async function removeFromMixin(id: number): Promise<ModelProfile[]> {
  if (isBridgeAvailable()) {
    const res = await ga()!.rpc('model-profiles/mixin-remove', { id }) as { profiles: ModelProfile[] };
    return res.profiles;
  }
  const res = await devFetch(`/model-profiles/${id}/mixin`, {
    method: 'DELETE',
  }) as { profiles: ModelProfile[] };
  return res.profiles;
}

export async function reorderMixin(members: string[]): Promise<ModelProfile[]> {
  if (isBridgeAvailable()) {
    const res = await ga()!.rpc('model-profiles/mixin-reorder', { members }) as { profiles: ModelProfile[] };
    return res.profiles;
  }
  const res = await devFetch('/model-profiles/mixin/order', {
    method: 'PUT',
    body: JSON.stringify({ members }),
  }) as { profiles: ModelProfile[] };
  return res.profiles;
}

export async function getMykeyContent(): Promise<string> {
  if (isBridgeAvailable()) {
    try {
      const res = await ga()!.getMykeyContent();
      return res.content;
    } catch { /* fall through */ }
  }
  try {
    const res = await devFetch('/services/mykey') as { content: string };
    return res.content || '';
  } catch {
    return '';
  }
}

export async function saveMykeyContent(content: string): Promise<void> {
  if (isBridgeAvailable()) {
    await ga()!.saveMykeyContent(content);
    return;
  }
  await devFetch('/services/mykey', {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

export async function tauriInvoke(cmd: string, args: Record<string, unknown>): Promise<unknown> {
  // Prefer window.ga.tauriInvoke if the vanilla bridge script is loaded
  if (isBridgeAvailable()) {
    return ga()!.tauriInvoke(cmd, args);
  }
  // Direct Tauri IPC — works in packaged app without app.js
  const invoke = getTauriInvoke();
  if (invoke) {
    return invoke(cmd, args);
  }
  throw new Error('Tauri IPC not available');
}
