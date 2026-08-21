import { create } from 'zustand';
import type { ModelProfile } from '../services/bridge';
import * as bridge from '../services/bridge';
import * as legacy from '../services/legacy';

const STORE_KEYS = {
  lang: 'ga_lang',
  theme: 'ga_theme',
  appearance: 'ga_appearance',
  fontSize: 'ga_font_size',
  llmNo: 'ga_llm_no',
} as const;

function syncBootCache(state: SettingsState) {
  try {
    localStorage.setItem(STORE_KEYS.lang, state.lang);
    localStorage.setItem(STORE_KEYS.appearance, state.appearance);
    localStorage.setItem(STORE_KEYS.fontSize, String(state.chatFontSize));
    localStorage.setItem(STORE_KEYS.llmNo, String(state.defaultModelNo));
  } catch (_) { /* private browsing */ }
}

function applyToDOM(appearance: string, chatFontSize: number) {
  const root = document.documentElement;
  root.dataset.appearance = appearance;
  delete root.dataset.plain;
  root.dataset.chatFont = String(chatFontSize);
  root.style.setProperty('--chat-font', chatFontSize + 'px');
  if (appearance === 'dark') {
    document.body.setAttribute('theme-mode', 'dark');
  } else {
    document.body.removeAttribute('theme-mode');
  }
}

interface SettingsState {
  visible: boolean;
  appearance: 'light' | 'dark';
  chatFontSize: number;
  lang: 'zh' | 'en';
  modelProfiles: ModelProfile[];
  defaultModelNo: number;
  liveModel: { isMixin: boolean; current: string; llmNo?: number; runningLlmNo?: number | null; runningModel?: string | null } | null;

  open: () => void;
  close: () => void;
  setAppearance: (app: 'light' | 'dark') => void;
  setChatFontSize: (size: number) => void;
  setLang: (lang: 'zh' | 'en') => void;
  setModelProfiles: (profiles: ModelProfile[]) => void;
  setDefaultModel: (no: number) => void;
  setLiveModel: (model: { isMixin: boolean; current: string; llmNo?: number; runningLlmNo?: number | null; runningModel?: string | null } | null) => void;
  loadFromBridge: () => Promise<void>;
  persist: () => Promise<void>;
}

function readInitialState() {
  const root = document.documentElement;
  return {
    appearance: (root.dataset.appearance === 'dark' ? 'dark' : 'light') as 'light' | 'dark',
    chatFontSize: parseInt(root.dataset.chatFont || '14', 10) || 14,
    lang: (root.lang === 'en' ? 'en' : 'zh') as 'zh' | 'en',
    defaultModelNo: parseInt(localStorage.getItem(STORE_KEYS.llmNo) || '0', 10),
  };
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  visible: false,
  modelProfiles: [],
  liveModel: null,
  ...readInitialState(),

  open: () => set({ visible: true }),
  close: () => set({ visible: false }),

  setAppearance: (app) => {
    set({ appearance: app });
    applyToDOM(app, get().chatFontSize);
    legacy.applyAppearance(app, false);
    legacy.syncHljsTheme();
    get().persist();
  },

  setChatFontSize: (size) => {
    const clamped = Math.max(10, Math.min(20, size));
    set({ chatFontSize: clamped });
    applyToDOM(get().appearance, clamped);
    get().persist();
  },

  setLang: (lang) => {
    set({ lang });
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    legacy.refreshAfterLangChange();
    get().persist();
  },

  setModelProfiles: (profiles) => set({ modelProfiles: profiles }),

  setDefaultModel: (no) => {
    const profiles = get().modelProfiles;
    const profile = profiles[no];
    if (!profile) return;
    set({ defaultModelNo: no });
    legacy.selectModel(no, profile.name || profile.model);
    get().persist();
  },

  setLiveModel: (model) => set({ liveModel: model }),

  loadFromBridge: async () => {
    try {
      const [config, profiles] = await Promise.all([
        bridge.getConfig(),
        bridge.getModelProfiles(),
      ]);
      set({
        appearance: config.appearance === 'dark' ? 'dark' : 'light',
        chatFontSize: config.fontSize || 14,
        lang: config.lang === 'en' ? 'en' : 'zh',
        defaultModelNo: config.llmNo || 0,
        modelProfiles: profiles,
      });
      const s = get();
      applyToDOM(s.appearance, s.chatFontSize);
    } catch (_) { /* bridge not ready yet */ }
  },

  persist: async () => {
    const s = get();
    syncBootCache(s);
    try {
      await bridge.saveConfig({
        lang: s.lang,
        theme: '1',
        appearance: s.appearance,
        plain: false,
        fontSize: s.chatFontSize,
        llmNo: s.defaultModelNo,
      });
    } catch (_) { /* bridge offline */ }
  },
}));
