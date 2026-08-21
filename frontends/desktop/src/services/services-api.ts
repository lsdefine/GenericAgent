import { BRIDGE_BASE } from './constants';

export interface ServiceInfo {
  id: string;
  name: string;
  status: 'running' | 'offline' | 'error' | 'warning';
  running: boolean;
  pid: number | null;
  memMb: number | null;
  cpuPct: number | null;
  managed: boolean;
  lastError: string | null;
  errorKey?: string;
  lastWarning?: string;
  warningKey?: string;
}

export type ModelFallbackReason =
  | 'ui_default'
  | 'invalid_configured'
  | 'configured_unavailable'
  | 'first_available'
  | 'no_models'
  | null;

export interface ConductorModelState {
  configured: number | null;
  effective: number | null;
  fallbackReason: ModelFallbackReason;
}

export async function fetchConductorModel(): Promise<ConductorModelState> {
  const res = await fetch(`${BRIDGE_BASE}/services/conductor/model`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.model;
}

export async function saveConductorModel(llmNo: number): Promise<ConductorModelState> {
  const res = await fetch(`${BRIDGE_BASE}/services/conductor/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ llmNo }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.model;
}

export async function fetchServicesPanel(): Promise<ServiceInfo[]> {
  const res = await fetch(`${BRIDGE_BASE}/services/panel`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.services ?? [];
}

export async function startServiceById(id: string): Promise<{ ok: boolean; service?: ServiceInfo }> {
  const res = await fetch(`${BRIDGE_BASE}/services/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return { ok: data.ok ?? true, service: data.service };
}

export async function stopServiceById(id: string): Promise<{ ok: boolean; service?: ServiceInfo }> {
  const res = await fetch(`${BRIDGE_BASE}/services/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return { ok: data.ok ?? true, service: data.service };
}

export async function fetchServiceLogs(id: string, tail = 200): Promise<string[]> {
  const res = await fetch(
    `${BRIDGE_BASE}/services/logs?id=${encodeURIComponent(id)}&tail=${tail}`,
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.lines ?? [];
}

export async function fetchMykeyContent(): Promise<string> {
  const res = await fetch(`${BRIDGE_BASE}/services/mykey`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.content ?? '';
}

export async function saveMykeyContent(content: string): Promise<boolean> {
  const res = await fetch(`${BRIDGE_BASE}/services/mykey`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.ok ?? false;
}

export async function exitBridge(): Promise<boolean> {
  const res = await fetch(`${BRIDGE_BASE}/services/bridge/exit`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.ok ?? false;
}
