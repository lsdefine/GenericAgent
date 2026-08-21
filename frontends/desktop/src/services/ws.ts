type WsHandler = (payload: unknown) => void;
export type BridgeStatus = 'ready' | 'connecting' | 'offline';

import { WS_URL } from './constants';
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;

let ws: WebSocket | null = null;
let reconnectAttempt = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
const listeners = new Map<string, Set<WsHandler>>();

let currentStatus: BridgeStatus = 'offline';
const statusListeners = new Set<(s: BridgeStatus) => void>();

let everConnected = false;
let failCount = 0;
const everConnectedListeners = new Set<() => void>();

function setStatus(s: BridgeStatus) {
  if (s === currentStatus) return;
  currentStatus = s;
  if (s === 'ready') {
    failCount = 0;
    if (!everConnected) {
      everConnected = true;
      everConnectedListeners.forEach((fn) => fn());
    }
  }
  statusListeners.forEach((fn) => fn(s));
}

export function getBridgeStatus(): BridgeStatus {
  return currentStatus;
}

export function onBridgeStatusChange(fn: (s: BridgeStatus) => void): () => void {
  statusListeners.add(fn);
  return () => { statusListeners.delete(fn); };
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  setStatus('connecting');

  try {
    ws = new WebSocket(WS_URL);
  } catch {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    reconnectAttempt = 0;
    setStatus('ready');
  };

  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      const type = data.type as string;
      if (!type) return;
      const handlers = listeners.get(type);
      if (handlers) {
        handlers.forEach((fn) => fn(data));
      }
    } catch {}
  };

  ws.onclose = () => {
    ws = null;
    setStatus('connecting');
    scheduleReconnect();
  };

  ws.onerror = () => {
    ws?.close();
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempt, RECONNECT_MAX_MS);
  reconnectAttempt++;
  failCount++;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

export function subscribe(type: string, handler: WsHandler): () => void {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type)!.add(handler);
  connect();
  return () => {
    listeners.get(type)?.delete(handler);
  };
}

export function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  ws?.close();
  ws = null;
}

export function getBridgeEverConnected(): boolean {
  return everConnected;
}

export function getBridgeFailCount(): number {
  return failCount;
}

export function onBridgeEverConnectedChange(fn: () => void): () => void {
  everConnectedListeners.add(fn);
  return () => { everConnectedListeners.delete(fn); };
}
