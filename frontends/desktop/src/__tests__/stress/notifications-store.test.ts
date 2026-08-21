// @vitest-environment node
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

type NotificationKind = 'error' | 'warning' | 'info' | 'success';

interface AppNotification {
  id: string;
  kind: NotificationKind;
  message: string;
  title?: string;
  createdAt: number;
}

const MAX_VISIBLE = 4;

function createStore() {
  let seq = 0;
  let items: AppNotification[] = [];
  const timers: ReturnType<typeof setTimeout>[] = [];

  return {
    get items() { return items; },

    notify(n: { kind: NotificationKind; message: string; title?: string }) {
      const id = `notif-${++seq}-${Date.now()}`;
      const entry: AppNotification = { ...n, id, createdAt: Date.now() };

      const existing = items.find((i) => i.message === entry.message && i.kind === entry.kind);
      if (existing) {
        items = items.map((i) => (i.id === existing.id ? { ...entry, id: existing.id } : i));
      } else {
        const next = [...items, entry];
        items = next.length > MAX_VISIBLE ? next.slice(-MAX_VISIBLE) : next;
      }

      const timeout = n.kind === 'error' || n.kind === 'warning' ? 8000 : 5000;
      const timer = setTimeout(() => this.dismiss(id), timeout);
      timers.push(timer);
      return id;
    },

    dismiss(id: string) {
      items = items.filter((i) => i.id !== id);
    },

    clear() {
      items = [];
    },

    cleanup() {
      timers.forEach(clearTimeout);
    },
  };
}

describe('notification store stress tests', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('enforces MAX_VISIBLE limit under burst', () => {
    const store = createStore();
    for (let i = 0; i < 10; i++) {
      store.notify({ kind: 'info', message: `msg-${i}` });
    }
    expect(store.items.length).toBe(MAX_VISIBLE);
    expect(store.items[0].message).toBe('msg-6');
    expect(store.items[3].message).toBe('msg-9');
    store.cleanup();
  });

  it('deduplicates same message+kind by updating existing', () => {
    const store = createStore();
    store.notify({ kind: 'error', message: 'Connection lost' });
    store.notify({ kind: 'error', message: 'Connection lost' });
    store.notify({ kind: 'error', message: 'Connection lost' });
    expect(store.items.length).toBe(1);
    store.cleanup();
  });

  it('does not deduplicate different kinds with same message', () => {
    const store = createStore();
    store.notify({ kind: 'error', message: 'Something happened' });
    store.notify({ kind: 'warning', message: 'Something happened' });
    store.notify({ kind: 'info', message: 'Something happened' });
    expect(store.items.length).toBe(3);
    store.cleanup();
  });

  it('info/success auto-dismiss after 5s', () => {
    const store = createStore();
    store.notify({ kind: 'info', message: 'Info msg' });
    store.notify({ kind: 'success', message: 'Success msg' });
    expect(store.items.length).toBe(2);

    vi.advanceTimersByTime(5001);
    expect(store.items.length).toBe(0);
    store.cleanup();
  });

  it('error/warning auto-dismiss after 8s', () => {
    const store = createStore();
    store.notify({ kind: 'error', message: 'Error msg' });
    store.notify({ kind: 'warning', message: 'Warn msg' });
    expect(store.items.length).toBe(2);

    vi.advanceTimersByTime(5001);
    expect(store.items.length).toBe(2);

    vi.advanceTimersByTime(3000);
    expect(store.items.length).toBe(0);
    store.cleanup();
  });

  it('manual dismiss works before auto-timeout', () => {
    const store = createStore();
    const id = store.notify({ kind: 'error', message: 'Dismissable' });
    expect(store.items.length).toBe(1);
    store.dismiss(id);
    expect(store.items.length).toBe(0);
    store.cleanup();
  });

  it('clear removes all regardless of timers', () => {
    const store = createStore();
    for (let i = 0; i < 4; i++) {
      store.notify({ kind: 'error', message: `err-${i}` });
    }
    expect(store.items.length).toBe(4);
    store.clear();
    expect(store.items.length).toBe(0);
    store.cleanup();
  });

  it('overflow evicts oldest first', () => {
    const store = createStore();
    store.notify({ kind: 'info', message: 'A' });
    store.notify({ kind: 'info', message: 'B' });
    store.notify({ kind: 'info', message: 'C' });
    store.notify({ kind: 'info', message: 'D' });
    expect(store.items.length).toBe(4);
    store.notify({ kind: 'info', message: 'E' });
    expect(store.items.length).toBe(4);
    expect(store.items.map((i) => i.message)).toEqual(['B', 'C', 'D', 'E']);
    store.cleanup();
  });
});
