import zh from './zh'
import en from './en'

export type Locale = 'zh' | 'en'
export type Messages = typeof zh

const messages: Record<Locale, Messages> = { zh, en }

export function getLocale(url: URL): Locale {
  const seg = url.pathname.split('/')[1]
  return seg === 'en' ? 'en' : 'zh'
}

export function t(locale: Locale): Messages {
  return messages[locale]
}

export function localePath(locale: Locale, path: string): string {
  const clean = path.startsWith('/') ? path : `/${path}`
  return `/${locale}${clean}`
}

export function switchLocalePath(url: URL, targetLocale: Locale): string {
  const parts = url.pathname.split('/')
  if (parts[1] === 'zh' || parts[1] === 'en') {
    parts[1] = targetLocale
  }
  return parts.join('/')
}

export const locales: Locale[] = ['zh', 'en']
