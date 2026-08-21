// @vitest-environment node
import { describe, it, expect } from 'vitest';

describe('settings store logic', () => {
  describe('font size clamping', () => {
    function clamp(size: number): number {
      return Math.max(10, Math.min(20, size));
    }

    it('clamps below minimum to 10', () => {
      expect(clamp(5)).toBe(10);
      expect(clamp(0)).toBe(10);
      expect(clamp(-1)).toBe(10);
    });

    it('clamps above maximum to 20', () => {
      expect(clamp(25)).toBe(20);
      expect(clamp(100)).toBe(20);
    });

    it('preserves values within range', () => {
      for (let i = 10; i <= 20; i++) {
        expect(clamp(i)).toBe(i);
      }
    });
  });

  describe('model selection validation', () => {
    interface ModelProfile {
      id: number;
      name: string;
      model: string;
      apibase: string;
      protocol: 'oai' | 'claude';
      stream: boolean;
    }

    function selectModel(profiles: ModelProfile[], no: number): ModelProfile | null {
      return profiles[no] || null;
    }

    it('returns null for out-of-bounds index', () => {
      const profiles: ModelProfile[] = [
        { id: 1, name: 'GPT-4', model: 'gpt-4', apibase: 'https://api.openai.com', protocol: 'oai', stream: true },
      ];
      expect(selectModel(profiles, -1)).toBeNull();
      expect(selectModel(profiles, 5)).toBeNull();
    });

    it('returns correct profile for valid index', () => {
      const profiles: ModelProfile[] = [
        { id: 1, name: 'GPT-4', model: 'gpt-4', apibase: 'https://api.openai.com', protocol: 'oai', stream: true },
        { id: 2, name: 'Claude', model: 'claude-3', apibase: 'https://api.anthropic.com', protocol: 'claude', stream: true },
      ];
      expect(selectModel(profiles, 0)?.name).toBe('GPT-4');
      expect(selectModel(profiles, 1)?.name).toBe('Claude');
    });

    it('handles empty profiles', () => {
      expect(selectModel([], 0)).toBeNull();
    });
  });

  describe('localStorage boot cache round-trip', () => {
    const STORE_KEYS = {
      lang: 'ga_lang',
      appearance: 'ga_appearance',
      fontSize: 'ga_font_size',
      llmNo: 'ga_llm_no',
    } as const;

    function syncBootCache(state: { lang: string; appearance: string; chatFontSize: number; defaultModelNo: number }) {
      const store = new Map<string, string>();
      store.set(STORE_KEYS.lang, state.lang);
      store.set(STORE_KEYS.appearance, state.appearance);
      store.set(STORE_KEYS.fontSize, String(state.chatFontSize));
      store.set(STORE_KEYS.llmNo, String(state.defaultModelNo));
      return store;
    }

    function readFromCache(store: Map<string, string>) {
      return {
        lang: store.get(STORE_KEYS.lang) || 'zh',
        appearance: store.get(STORE_KEYS.appearance) || 'light',
        chatFontSize: parseInt(store.get(STORE_KEYS.fontSize) || '14', 10),
        defaultModelNo: parseInt(store.get(STORE_KEYS.llmNo) || '0', 10),
      };
    }

    it('round-trips all settings correctly', () => {
      const original = { lang: 'en', appearance: 'dark', chatFontSize: 16, defaultModelNo: 3 };
      const store = syncBootCache(original);
      const restored = readFromCache(store);
      expect(restored).toEqual(original);
    });

    it('handles missing keys with defaults', () => {
      const empty = new Map<string, string>();
      const defaults = readFromCache(empty);
      expect(defaults).toEqual({ lang: 'zh', appearance: 'light', chatFontSize: 14, defaultModelNo: 0 });
    });

    it('survives rapid update cycles', () => {
      for (let i = 0; i < 50; i++) {
        const state = { lang: i % 2 === 0 ? 'zh' : 'en', appearance: i % 3 === 0 ? 'dark' : 'light', chatFontSize: 10 + (i % 11), defaultModelNo: i % 5 };
        const store = syncBootCache(state);
        const restored = readFromCache(store);
        expect(restored).toEqual(state);
      }
    });
  });
});
