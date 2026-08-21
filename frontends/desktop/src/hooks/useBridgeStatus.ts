import { useSyncExternalStore } from 'react';
import { getBridgeStatus, onBridgeStatusChange, subscribe as subscribeWs, type BridgeStatus } from '../services/ws';

function subscribe(cb: () => void) {
  const unsubscribeStatus = onBridgeStatusChange(cb);
  const unsubscribeWs = subscribeWs('bridge-ready', () => cb());
  return () => {
    unsubscribeWs();
    unsubscribeStatus();
  };
}

export function useBridgeStatus(): BridgeStatus {
  return useSyncExternalStore(subscribe, getBridgeStatus, getBridgeStatus);
}
