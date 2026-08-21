import { useSyncExternalStore } from 'react';
import { getBridgeFailCount, onBridgeStatusChange } from '../services/ws';

function subscribe(cb: () => void) {
  return onBridgeStatusChange(() => cb());
}

export function useBridgeFailCount(): number {
  return useSyncExternalStore(subscribe, getBridgeFailCount, getBridgeFailCount);
}
