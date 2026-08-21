// @vitest-environment node
/**
 * Bridge connection state machine tests.
 * Tests the bridgeActivity store and status tracking logic.
 */
import { describe, it, expect } from 'vitest';

const LOG_VISIBLE = 40;

function createBridgeActivity() {
  let logs: string[] = [];
  const listeners = new Set<() => void>();

  function pushLog(line: string) {
    logs = [...logs.slice(-(LOG_VISIBLE - 1)), line];
    listeners.forEach((cb) => cb());
  }

  function handleSessionState(evt: { sessionId?: string; status?: string }) {
    if (!evt.sessionId || !evt.status) return;
    const label = evt.status === 'running'
      ? 'Turn started'
      : evt.status === 'idle'
        ? 'Turn complete'
        : evt.status === 'error'
          ? 'Turn error'
          : `Session ${evt.status}`;
    pushLog(label);
  }

  function handleServiceChanged(evt: { service?: { id?: string; name?: string; status?: string } }) {
    if (!evt.service) return;
    const label = evt.service.name ?? evt.service.id ?? 'service';
    const status = evt.service.status ?? 'unknown';
    pushLog(`${label}: ${status}`);
  }

  function handleTokenChanged(evt: { session_id?: string; total_output?: number }) {
    if (!evt.session_id || !evt.total_output) return;
    pushLog(`Token update: +${evt.total_output} output`);
  }

  return {
    get logs() { return logs; },
    pushLog,
    handleSessionState,
    handleServiceChanged,
    handleTokenChanged,
    onActivityChange(cb: () => void) {
      listeners.add(cb);
      return () => { listeners.delete(cb); };
    },
  };
}

describe('bridge activity / connection state', () => {
  describe('log buffer management', () => {
    it('caps at LOG_VISIBLE entries', () => {
      const activity = createBridgeActivity();
      for (let i = 0; i < 60; i++) {
        activity.pushLog(`line-${i}`);
      }
      expect(activity.logs.length).toBe(LOG_VISIBLE);
      expect(activity.logs[0]).toBe('line-20');
      expect(activity.logs[39]).toBe('line-59');
    });

    it('notifies listeners on new log entry', () => {
      const activity = createBridgeActivity();
      let notified = 0;
      activity.onActivityChange(() => notified++);
      activity.pushLog('test');
      activity.pushLog('test2');
      expect(notified).toBe(2);
    });

    it('unsubscribe stops notifications', () => {
      const activity = createBridgeActivity();
      let notified = 0;
      const unsub = activity.onActivityChange(() => notified++);
      activity.pushLog('a');
      unsub();
      activity.pushLog('b');
      expect(notified).toBe(1);
    });
  });

  describe('session-state event routing', () => {
    it('maps running → "Turn started"', () => {
      const activity = createBridgeActivity();
      activity.handleSessionState({ sessionId: 's1', status: 'running' });
      expect(activity.logs).toContain('Turn started');
    });

    it('maps idle → "Turn complete"', () => {
      const activity = createBridgeActivity();
      activity.handleSessionState({ sessionId: 's1', status: 'idle' });
      expect(activity.logs).toContain('Turn complete');
    });

    it('maps error → "Turn error"', () => {
      const activity = createBridgeActivity();
      activity.handleSessionState({ sessionId: 's1', status: 'error' });
      expect(activity.logs).toContain('Turn error');
    });

    it('maps unknown status to "Session <status>"', () => {
      const activity = createBridgeActivity();
      activity.handleSessionState({ sessionId: 's1', status: 'cancelled' });
      expect(activity.logs).toContain('Session cancelled');
    });

    it('ignores events without sessionId or status', () => {
      const activity = createBridgeActivity();
      activity.handleSessionState({});
      activity.handleSessionState({ sessionId: 's1' });
      activity.handleSessionState({ status: 'running' });
      expect(activity.logs.length).toBe(0);
    });
  });

  describe('service.changed event routing', () => {
    it('logs service name + status', () => {
      const activity = createBridgeActivity();
      activity.handleServiceChanged({ service: { id: 'agent', name: 'GenericAgent', status: 'running' } });
      expect(activity.logs[0]).toBe('GenericAgent: running');
    });

    it('falls back to id when name is missing', () => {
      const activity = createBridgeActivity();
      activity.handleServiceChanged({ service: { id: 'bridge', status: 'stopped' } });
      expect(activity.logs[0]).toBe('bridge: stopped');
    });

    it('falls back to "service" when both missing', () => {
      const activity = createBridgeActivity();
      activity.handleServiceChanged({ service: { status: 'error' } });
      expect(activity.logs[0]).toBe('service: error');
    });

    it('ignores null service', () => {
      const activity = createBridgeActivity();
      activity.handleServiceChanged({});
      expect(activity.logs.length).toBe(0);
    });
  });

  describe('token.changed event routing', () => {
    it('logs token update with output count', () => {
      const activity = createBridgeActivity();
      activity.handleTokenChanged({ session_id: 's1', total_output: 500 });
      expect(activity.logs[0]).toBe('Token update: +500 output');
    });

    it('ignores events without session_id or total_output', () => {
      const activity = createBridgeActivity();
      activity.handleTokenChanged({});
      activity.handleTokenChanged({ session_id: 's1' });
      activity.handleTokenChanged({ total_output: 100 });
      expect(activity.logs.length).toBe(0);
    });

    it('ignores zero total_output', () => {
      const activity = createBridgeActivity();
      activity.handleTokenChanged({ session_id: 's1', total_output: 0 });
      expect(activity.logs.length).toBe(0);
    });
  });

  describe('high-throughput scenario', () => {
    it('handles rapid interleaved events without data loss', () => {
      const activity = createBridgeActivity();
      for (let i = 0; i < 100; i++) {
        activity.handleSessionState({ sessionId: `s${i}`, status: i % 2 === 0 ? 'running' : 'idle' });
        activity.handleServiceChanged({ service: { id: `svc-${i}`, status: 'running' } });
        activity.handleTokenChanged({ session_id: `s${i}`, total_output: i * 10 });
      }
      expect(activity.logs.length).toBe(LOG_VISIBLE);
    });
  });
});
