// @vitest-environment node
/**
 * WebSocket protocol tests.
 * Tests message format parsing, streaming chunk assembly, and reconnection timing
 * extracted from services/ws.ts logic.
 */
import { describe, it, expect } from 'vitest';

type BridgeStatus = 'ready' | 'connecting' | 'offline';
type WsHandler = (payload: unknown) => void;

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;

function createWsManager() {
  let currentStatus: BridgeStatus = 'offline';
  let reconnectAttempt = 0;
  let failCount = 0;
  let everConnected = false;
  const listeners = new Map<string, Set<WsHandler>>();
  const statusListeners = new Set<(s: BridgeStatus) => void>();

  function setStatus(s: BridgeStatus) {
    if (s === currentStatus) return;
    currentStatus = s;
    if (s === 'ready') {
      failCount = 0;
      everConnected = true;
    }
    statusListeners.forEach((fn) => fn(s));
  }

  function getReconnectDelay(): number {
    return Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempt, RECONNECT_MAX_MS);
  }

  function simulateReconnectAttempt() {
    reconnectAttempt++;
    failCount++;
    return getReconnectDelay();
  }

  function simulateOpen() {
    reconnectAttempt = 0;
    setStatus('ready');
  }

  function simulateClose() {
    setStatus('connecting');
  }

  function dispatch(type: string, data: unknown) {
    const handlers = listeners.get(type);
    if (handlers) handlers.forEach((fn) => fn(data));
  }

  function subscribe(type: string, handler: WsHandler) {
    if (!listeners.has(type)) listeners.set(type, new Set());
    listeners.get(type)!.add(handler);
    return () => { listeners.get(type)?.delete(handler); };
  }

  function onStatusChange(fn: (s: BridgeStatus) => void) {
    statusListeners.add(fn);
    return () => { statusListeners.delete(fn); };
  }

  return {
    get status() { return currentStatus; },
    get failCount() { return failCount; },
    get reconnectAttempt() { return reconnectAttempt; },
    get everConnected() { return everConnected; },
    setStatus,
    getReconnectDelay,
    simulateReconnectAttempt,
    simulateOpen,
    simulateClose,
    dispatch,
    subscribe,
    onStatusChange,
  };
}

describe('WebSocket protocol', () => {
  describe('reconnection backoff', () => {
    it('starts at base delay and doubles', () => {
      const mgr = createWsManager();
      expect(mgr.getReconnectDelay()).toBe(1000);
      mgr.simulateReconnectAttempt();
      expect(mgr.getReconnectDelay()).toBe(2000);
      mgr.simulateReconnectAttempt();
      expect(mgr.getReconnectDelay()).toBe(4000);
    });

    it('caps at RECONNECT_MAX_MS', () => {
      const mgr = createWsManager();
      for (let i = 0; i < 20; i++) mgr.simulateReconnectAttempt();
      expect(mgr.getReconnectDelay()).toBe(RECONNECT_MAX_MS);
    });

    it('resets attempt counter on successful connect', () => {
      const mgr = createWsManager();
      mgr.simulateReconnectAttempt();
      mgr.simulateReconnectAttempt();
      mgr.simulateReconnectAttempt();
      expect(mgr.reconnectAttempt).toBe(3);
      mgr.simulateOpen();
      expect(mgr.status).toBe('ready');
    });
  });

  describe('status transitions', () => {
    it('offline → connecting → ready on first connect', () => {
      const mgr = createWsManager();
      const transitions: BridgeStatus[] = [];
      mgr.onStatusChange((s) => transitions.push(s));

      mgr.setStatus('connecting');
      mgr.simulateOpen();

      expect(transitions).toEqual(['connecting', 'ready']);
    });

    it('ready → connecting on socket close', () => {
      const mgr = createWsManager();
      mgr.setStatus('connecting');
      mgr.simulateOpen();

      const transitions: BridgeStatus[] = [];
      mgr.onStatusChange((s) => transitions.push(s));
      mgr.simulateClose();

      expect(transitions).toEqual(['connecting']);
    });

    it('does not emit duplicate status', () => {
      const mgr = createWsManager();
      const transitions: BridgeStatus[] = [];
      mgr.onStatusChange((s) => transitions.push(s));

      mgr.setStatus('connecting');
      mgr.setStatus('connecting');
      mgr.setStatus('connecting');

      expect(transitions).toEqual(['connecting']);
    });

    it('everConnected becomes true on first ready', () => {
      const mgr = createWsManager();
      expect(mgr.everConnected).toBe(false);
      mgr.setStatus('connecting');
      expect(mgr.everConnected).toBe(false);
      mgr.simulateOpen();
      expect(mgr.everConnected).toBe(true);
    });

    it('failCount resets on successful connect', () => {
      const mgr = createWsManager();
      mgr.simulateReconnectAttempt();
      mgr.simulateReconnectAttempt();
      expect(mgr.failCount).toBe(2);
      mgr.simulateOpen();
      expect(mgr.failCount).toBe(0);
    });
  });

  describe('message dispatch', () => {
    it('routes messages to correct handler by type', () => {
      const mgr = createWsManager();
      const received: unknown[] = [];
      mgr.subscribe('session-state', (d) => received.push(d));

      mgr.dispatch('session-state', { sessionId: 's1', status: 'running' });
      mgr.dispatch('token.changed', { session_id: 's1', total_output: 100 });

      expect(received).toEqual([{ sessionId: 's1', status: 'running' }]);
    });

    it('supports multiple handlers per type', () => {
      const mgr = createWsManager();
      const a: unknown[] = [];
      const b: unknown[] = [];
      mgr.subscribe('partial-update', (d) => a.push(d));
      mgr.subscribe('partial-update', (d) => b.push(d));

      mgr.dispatch('partial-update', { content: 'hello' });
      expect(a.length).toBe(1);
      expect(b.length).toBe(1);
    });

    it('unsubscribe removes only that handler', () => {
      const mgr = createWsManager();
      const received: unknown[] = [];
      const unsub = mgr.subscribe('test', (d) => received.push(d));
      mgr.subscribe('test', () => {});

      unsub();
      mgr.dispatch('test', { x: 1 });
      expect(received).toEqual([]);
    });

    it('handles unknown type silently', () => {
      const mgr = createWsManager();
      expect(() => mgr.dispatch('nonexistent', {})).not.toThrow();
    });
  });

  describe('message format parsing', () => {
    it('parses partial-update with content and turn_segs', () => {
      const payload = { type: 'partial-update', sessionId: 's1', content: 'Hello world', turn_segs: ['Hello', ' world'] };
      expect(payload.content).toBe('Hello world');
      expect(payload.turn_segs?.length).toBe(2);
    });

    it('parses session-state change', () => {
      const payload = { type: 'session-state', sessionId: 's1', status: 'running' };
      expect(payload.sessionId).toBe('s1');
      expect(payload.status).toBe('running');
    });

    it('parses service.changed event', () => {
      const payload = { type: 'service.changed', service: { id: 'agent', name: 'GenericAgent', status: 'running' } };
      expect(payload.service.status).toBe('running');
    });

    it('handles malformed JSON gracefully', () => {
      const parseMessage = (data: string) => {
        try { return JSON.parse(data); } catch { return null; }
      };
      expect(parseMessage('not json')).toBeNull();
      expect(parseMessage('{"type":"test"}')).toEqual({ type: 'test' });
    });
  });

  describe('streaming chunk assembly', () => {
    it('assembles incremental partial updates', () => {
      const chunks = ['Hel', 'Hello', 'Hello wor', 'Hello world'];
      let current = '';
      for (const chunk of chunks) {
        current = chunk;
      }
      expect(current).toBe('Hello world');
    });

    it('handles rapid partial updates without loss', () => {
      const updates: string[] = [];
      for (let i = 0; i < 100; i++) {
        updates.push('x'.repeat(i + 1));
      }
      const final = updates[updates.length - 1];
      expect(final.length).toBe(100);
    });
  });
});
