import { create } from 'zustand';
import { subscribe } from '../services/ws';
import {
  fetchServicesPanel,
  startServiceById,
  stopServiceById,
  exitBridge,
  fetchServiceLogs,
  fetchMykeyContent,
  saveMykeyContent,
  type ServiceInfo,
} from '../services/services-api';

export type { ServiceInfo };

interface ServicesState {
  services: ServiceInfo[];
  loading: boolean;
  error: string | null;
  mykeyContent: string;
  mykeyLoading: boolean;

  fetchServices: () => Promise<void>;
  startService: (id: string) => Promise<boolean>;
  stopService: (id: string) => Promise<boolean>;
  exitBridge: () => Promise<boolean>;
  restartService: (id: string) => Promise<boolean>;
  fetchLogs: (id: string, tail?: number) => Promise<string[]>;
  fetchMykey: () => Promise<void>;
  saveMykey: (content: string) => Promise<boolean>;
}

export const useServicesStore = create<ServicesState>((set, get) => {
  subscribe('services.snapshot', (data: unknown) => {
    const evt = data as { services?: ServiceInfo[] };
    if (evt.services) {
      set({ services: evt.services, loading: false, error: null });
    }
  });

  subscribe('service.changed', (data: unknown) => {
    const evt = data as { service?: ServiceInfo };
    if (evt.service) {
      set((s) => ({
        services: s.services.map((svc) =>
          svc.id === evt.service!.id ? evt.service! : svc,
        ),
      }));
    }
  });

  return {
    services: [],
    loading: true,
    error: null,
    mykeyContent: '',
    mykeyLoading: false,

    async fetchServices() {
      if (get().services.length === 0) set({ loading: true });
      set({ error: null });
      try {
        const services = await fetchServicesPanel();
        set({ services, loading: false });
      } catch (e) {
        set({ loading: false, error: (e as Error).message });
      }
    },

    async startService(id: string) {
      try {
        const { ok, service } = await startServiceById(id);
        if (service) {
          set((s) => ({
            services: s.services.map((svc) =>
              svc.id === service.id ? service : svc,
            ),
          }));
        }
        return ok;
      } catch {
        return false;
      }
    },

    async stopService(id: string) {
      try {
        const { ok, service } = await stopServiceById(id);
        if (service) {
          set((s) => ({
            services: s.services.map((svc) =>
              svc.id === service.id ? service : svc,
            ),
          }));
        }
        return ok;
      } catch {
        return false;
      }
    },

    async exitBridge() {
      try {
        return await exitBridge();
      } catch {
        return false;
      }
    },

    async restartService(id: string) {
      const stopped = await get().stopService(id);
      if (!stopped) return false;
      await new Promise((r) => setTimeout(r, 500));
      return get().startService(id);
    },

    async fetchLogs(id: string, tail = 200) {
      try {
        return await fetchServiceLogs(id, tail);
      } catch {
        return [];
      }
    },

    async fetchMykey() {
      set({ mykeyLoading: true });
      try {
        const content = await fetchMykeyContent();
        set({ mykeyContent: content, mykeyLoading: false });
      } catch {
        set({ mykeyLoading: false });
      }
    },

    async saveMykey(content: string) {
      try {
        const ok = await saveMykeyContent(content);
        if (ok) set({ mykeyContent: content });
        return ok;
      } catch {
        return false;
      }
    },
  };
});
