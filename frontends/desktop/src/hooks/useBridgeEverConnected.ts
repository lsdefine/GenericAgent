import { useSyncExternalStore } from 'react';
import { getBridgeEverConnected, onBridgeEverConnectedChange, onBridgeStatusChange } from '../services/ws';

function subscribe(cb: () => void) {
  const unsub1 = onBridgeEverConnectedChange(cb);
  const unsub2 = onBridgeStatusChange(() => cb());
  return () => { unsub1(); unsub2(); };
}

export function useBridgeEverConnected(): boolean {
  return useSyncExternalStore(subscribe, getBridgeEverConnected, getBridgeEverConnected);
}
