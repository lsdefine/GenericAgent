import { subscribe } from '../services/ws';

const LOG_VISIBLE = 40;

type Listener = () => void;

let logs: string[] = [];
const listeners = new Set<Listener>();
let started = false;

function emitChange() {
  for (const cb of listeners) cb();
}

function pushLog(line: string) {
  logs = [...logs.slice(-(LOG_VISIBLE - 1)), line];
  emitChange();
}

function ensureStarted() {
  if (started) return;
  started = true;

  subscribe('session-state', (data: unknown) => {
    const evt = data as { sessionId?: string; status?: string };
    if (!evt.sessionId || !evt.status) return;
    const label = evt.status === 'running'
      ? 'Turn started'
      : evt.status === 'idle'
        ? 'Turn complete'
        : evt.status === 'error'
          ? 'Turn error'
          : `Session ${evt.status}`;
    pushLog(label);
  });

  subscribe('service.changed', (data: unknown) => {
    const evt = data as { service?: { id?: string; name?: string; status?: string } };
    if (!evt.service) return;
    const label = evt.service.name ?? evt.service.id ?? 'service';
    const status = evt.service.status ?? 'unknown';
    pushLog(`${label}: ${status}`);
  });

  subscribe('token.changed', (data: unknown) => {
    const evt = data as { session_id?: string; total_output?: number };
    if (!evt.session_id || !evt.total_output) return;
    pushLog(`Token update: +${evt.total_output} output`);
  });
}

ensureStarted();

export function getBridgeActivity(): string[] {
  return logs;
}

export function onBridgeActivityChange(cb: Listener): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}
