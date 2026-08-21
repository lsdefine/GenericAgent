import { useMemo } from 'react';
import { useSettingsStore } from '../stores/settings';
import { zh } from './zh';
import { en } from './en';

const dictionaries: Record<string, Record<string, string>> = { zh, en };

export function t(lang: string, key: string, params?: Record<string, string | number>): string {
  const dict = dictionaries[lang] || dictionaries.zh;
  let text = dict[key] ?? key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replaceAll(`{${k}}`, String(v));
    }
  }
  return text;
}

export function useI18n() {
  const lang = useSettingsStore((s) => s.lang);
  return useMemo(
    () => ({
      lang,
      t: (key: string, params?: Record<string, string | number>) => t(lang, key, params),
    }),
    [lang],
  );
}
