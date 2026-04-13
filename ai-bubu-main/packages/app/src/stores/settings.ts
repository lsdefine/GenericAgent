import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { currentLang } from '@/composables/useI18n'

const RANDOM_NICKNAMES_ZH = [
  '奔跑的猫',
  '代码喵',
  '摸鱼侠',
  '键盘侠',
  '搬砖兔',
  '咖啡因',
  '通宵达旦',
  '逻辑怪',
  'Bug猎人',
  '像素猫',
  '闪电鼠',
  '暴走蛙',
  '安静鱼',
  '冲刺鸟',
  '思考熊',
]

const RANDOM_NICKNAMES_EN = [
  'RunningCat',
  'CodeKitty',
  'SlackHero',
  'KeyboardNinja',
  'BrickBunny',
  'CaffeineBot',
  'NightOwl',
  'LogicLord',
  'BugHunter',
  'PixelCat',
  'FlashMouse',
  'RageFrog',
  'QuietFish',
  'SprintBird',
  'ThinkBear',
]

function pickRandom<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function pickRandomNickname(): string {
  const pool = currentLang.value === 'zh' ? RANDOM_NICKNAMES_ZH : RANDOM_NICKNAMES_EN
  return pickRandom(pool)
}

const STORAGE_KEY = 'aibubu-settings'
const SKIN_KEY = 'aibubu-skin'
const THEME_KEY = 'aibubu-theme'

export type ThemeMode = 'dark' | 'light' | 'system'

interface SavedSettings {
  nickname?: string
  showOverFullscreen?: boolean
  socialEnabled?: boolean
}

function loadSaved(): SavedSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return {}
    return {
      nickname: typeof parsed.nickname === 'string' ? parsed.nickname : undefined,
      showOverFullscreen:
        typeof parsed.showOverFullscreen === 'boolean' ? parsed.showOverFullscreen : undefined,
      socialEnabled: typeof parsed.socialEnabled === 'boolean' ? parsed.socialEnabled : undefined,
    }
  } catch {
    return {}
  }
}

function saveSettings(nick: string, overFullscreen: boolean, social: boolean) {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ nickname: nick, showOverFullscreen: overFullscreen, socialEnabled: social }),
    )
  } catch {
    /* noop */
  }
}

function loadTheme(): ThemeMode {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    if (raw === 'dark' || raw === 'light' || raw === 'system') return raw
  } catch {
    /* noop */
  }
  return 'dark'
}

const DEFAULT_SKIN = 'vita'

function loadSkinId(): string {
  try {
    return localStorage.getItem(SKIN_KEY) || DEFAULT_SKIN
  } catch {
    return DEFAULT_SKIN
  }
}

export const useSettingsStore = defineStore('settings', () => {
  const saved = loadSaved()

  const currentSkinId = ref(loadSkinId())

  const nickname = ref(saved.nickname || pickRandomNickname())
  const showOverFullscreen = ref(saved.showOverFullscreen ?? true)
  const socialEnabled = ref(saved.socialEnabled ?? false)
  const theme = ref<ThemeMode>(loadTheme())

  if (!saved.nickname) {
    saveSettings(nickname.value, showOverFullscreen.value, socialEnabled.value)
  }

  watch(currentSkinId, (id) => {
    try {
      localStorage.setItem(SKIN_KEY, id)
    } catch {
      /* noop */
    }
  })

  watch(theme, (t) => {
    try {
      localStorage.setItem(THEME_KEY, t)
    } catch {
      /* noop */
    }
  })

  function syncSkinId(newId: string) {
    if (newId && newId !== currentSkinId.value) {
      currentSkinId.value = newId
    }
  }

  watch([nickname, showOverFullscreen, socialEnabled], () => {
    persistUserFields()
  })

  function persistUserFields() {
    saveSettings(nickname.value, showOverFullscreen.value, socialEnabled.value)
  }

  return {
    currentSkinId,
    nickname,
    showOverFullscreen,
    socialEnabled,
    theme,
    syncSkinId,
    persistUserFields,
  }
})
