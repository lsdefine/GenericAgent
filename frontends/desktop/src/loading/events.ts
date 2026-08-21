import type { BootstrapAction } from './store';
import type { BootstrapSnapshot } from './types';

type Dispatch = (action: BootstrapAction) => void;

let unlisten: (() => void) | null = null;
let subscriptionGeneration = 0;

function mockSnapshot(seq: number, phase: BootstrapSnapshot['phase']): BootstrapSnapshot {
  const preparing = phase === 'preparing';
  return {
    seq,
    mode: preparing ? 'prepare' : 'cold_start',
    phase,
    stage: preparing ? 'dependencies' : phase === 'starting_service' ? 'service' : null,
    progress: phase === 'ready' ? 100 : preparing ? 55 : 15,
    failure: null,
    diagnostics: {
      buildId: 'development',
      platform: navigator.platform || 'web',
      projectDir: '',
      pythonPath: '',
      portState: 'unknown',
      bridgeIdentity: null,
      recentLogs: preparing ? ['Installing runtime components…'] : [],
    },
  };
}

function runDevMock(dispatch: Dispatch) {
  const timers = [
    setTimeout(() => dispatch({ type: 'snapshot', snapshot: mockSnapshot(1, 'resolving') }), 300),
    setTimeout(() => dispatch({ type: 'snapshot', snapshot: mockSnapshot(2, 'preparing') }), 900),
    setTimeout(() => dispatch({ type: 'snapshot', snapshot: mockSnapshot(3, 'starting_service') }), 1800),
    setTimeout(() => dispatch({ type: 'snapshot', snapshot: mockSnapshot(4, 'ready') }), 2600),
  ];
  unlisten = () => timers.forEach(clearTimeout);
}

export async function subscribe(dispatch: Dispatch): Promise<void> {
  const generation = ++subscriptionGeneration;
  const tauri = (window as Window & {
    __TAURI__?: {
      event?: { listen?: (name: string, handler: (event: { payload: BootstrapSnapshot }) => void) => Promise<() => void> };
      core?: { invoke?: <T>(command: string) => Promise<T> };
    };
  }).__TAURI__;

  if (!tauri?.event?.listen || !tauri.core?.invoke) {
    runDevMock(dispatch);
    return;
  }

  const stopListening = await tauri.event.listen('bootstrap', (event) => {
    if (generation === subscriptionGeneration) {
      dispatch({ type: 'snapshot', snapshot: event.payload as BootstrapSnapshot });
    }
  });
  if (generation !== subscriptionGeneration) {
    stopListening();
    return;
  }
  unlisten?.();
  unlisten = stopListening;

  const snapshot = await tauri.core.invoke<BootstrapSnapshot>('get_bootstrap_snapshot') as BootstrapSnapshot;
  if (generation === subscriptionGeneration) {
    dispatch({ type: 'snapshot', snapshot });
  }
}

export function unsubscribe(): void {
  subscriptionGeneration += 1;
  if (unlisten) {
    unlisten();
    unlisten = null;
  }
}
