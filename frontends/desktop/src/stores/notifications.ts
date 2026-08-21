import { create } from 'zustand';

export type NotificationKind = 'error' | 'warning' | 'info' | 'success';

export interface AppNotification {
  id: string;
  kind: NotificationKind;
  title?: string;
  message: string;
  detail?: string;
  action?: { label: string; onClick: () => void };
  createdAt: number;
}

interface NotificationState {
  items: AppNotification[];
  notify: (n: Omit<AppNotification, 'id' | 'createdAt'>) => void;
  dismiss: (id: string) => void;
  clear: () => void;
}

const MAX_VISIBLE = 4;
let seq = 0;

export const useNotificationStore = create<NotificationState>((set, get) => ({
  items: [],

  notify(n) {
    const id = `notif-${++seq}-${Date.now()}`;
    const entry: AppNotification = { ...n, id, createdAt: Date.now() };
    set((s) => {
      const existing = s.items.find((i) => i.message === entry.message && i.kind === entry.kind);
      if (existing) {
        return { items: s.items.map((i) => (i.id === existing.id ? { ...entry, id: existing.id } : i)) };
      }
      const next = [...s.items, entry];
      return { items: next.length > MAX_VISIBLE ? next.slice(-MAX_VISIBLE) : next };
    });

    if (n.kind === 'info' || n.kind === 'success') {
      setTimeout(() => get().dismiss(id), 5000);
    } else if (n.kind === 'error' || n.kind === 'warning') {
      setTimeout(() => get().dismiss(id), 8000);
    }
  },

  dismiss(id) {
    set((s) => ({ items: s.items.filter((i) => i.id !== id) }));
  },

  clear() {
    set({ items: [] });
  },
}));
