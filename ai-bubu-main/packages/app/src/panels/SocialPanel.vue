<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { useSocialStore } from '@/stores/social'
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'
import { useAutoUpdater } from '@/composables/useAutoUpdater'
import Leaderboard from './Leaderboard.vue'
import TodayView from './TodayView.vue'
import SkinMarket from './SkinMarket.vue'
import SettingsView from './SettingsView.vue'
import AboutView from './AboutView.vue'

const socialStore = useSocialStore()
const { status: updateStatus } = useAutoUpdater()
const hasUpdate = computed(() => updateStatus.value === 'available')
const settings = useSettingsStore()
const { t, lang, setLang, isZh } = useI18n()

const systemDark = ref(window.matchMedia('(prefers-color-scheme: dark)').matches)

function onMediaChange(e: MediaQueryListEvent) {
  systemDark.value = e.matches
}

const isLight = computed(() => {
  if (settings.theme === 'system') return !systemDark.value
  return settings.theme === 'light'
})

const TAB_KEY = 'aibubu-active-tab'
type Tab = 'today' | 'leaderboard' | 'skins' | 'settings' | 'about'

function loadTab(): Tab {
  try {
    const saved = localStorage.getItem(TAB_KEY) as Tab | null
    if (saved && ['today', 'leaderboard', 'skins', 'settings', 'about'].includes(saved))
      return saved
  } catch {
    /* private mode */
  }
  return 'today'
}

const activeTab = ref<Tab>(loadTab())

watch(activeTab, (val) => {
  try {
    localStorage.setItem(TAB_KEY, val)
  } catch {
    /* private mode */
  }
})

const navKeys: Tab[] = ['today', 'leaderboard', 'skins', 'settings', 'about']

function onKeydown(event: KeyboardEvent) {
  if (event.metaKey || event.ctrlKey || event.altKey) return
  const tag = (event.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
  const key = event.key
  if (key === '1') activeTab.value = 'today'
  else if (key === '2') activeTab.value = 'leaderboard'
  else if (key === '3') activeTab.value = 'skins'
  else if (key === '4') activeTab.value = 'settings'
  else if (key === '5') activeTab.value = 'about'
}

const mql = window.matchMedia('(prefers-color-scheme: dark)')

const appWindow = getCurrentWindow()

watch(
  lang,
  () => {
    const title = t('brand')
    document.title = title
    appWindow.setTitle(title)
  },
  { immediate: true },
)

watch(
  isLight,
  (light) => {
    appWindow.setTheme(light ? 'light' : 'dark')
    const bg = light ? '#f8fafc' : '#0f0f14'
    document.documentElement.style.backgroundColor = bg
    document.body.style.backgroundColor = bg
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  mql.addEventListener('change', onMediaChange)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  mql.removeEventListener('change', onMediaChange)
})
</script>

<template>
  <div class="social-window" :class="{ 'theme-light': isLight }">
    <nav class="sidebar">
      <div class="sidebar-brand">
        <img class="brand-logo" src="/skins/vita/pet.png" :alt="t('brand')" />
        <span class="brand-text">{{ t('brand') }}</span>
        <button
          class="lang-toggle"
          :title="isZh ? 'English' : '中文'"
          @click="setLang(isZh ? 'en' : 'zh')"
        >
          {{ isZh ? 'EN' : '中' }}
        </button>
      </div>

      <div class="nav-items">
        <button
          v-for="tab in navKeys"
          :key="tab"
          class="nav-btn"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >
          <svg
            v-if="tab === 'today'"
            class="nav-icon"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M9 4V6M15 4V6"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
            />
            <rect
              x="4.5"
              y="5.5"
              width="15"
              height="14"
              rx="2"
              stroke="currentColor"
              stroke-width="1.6"
            />
            <path d="M4.5 9.5H19.5" stroke="currentColor" stroke-width="1.6" />
            <path d="M9 13H12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
          <svg
            v-else-if="tab === 'leaderboard'"
            class="nav-icon"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <path d="M7 18V12" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            <path d="M12 18V8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            <path d="M17 18V10.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
            <path d="M4 19H20" stroke="currentColor" stroke-width="1.7" />
          </svg>
          <svg
            v-else-if="tab === 'skins'"
            class="nav-icon"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M12 4C8 4 5 7 5 10.5C5 14 7 16.5 9 18L10 20H14L15 18C17 16.5 19 14 19 10.5C19 7 16 4 12 4Z"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linejoin="round"
            />
            <circle cx="9.5" cy="11" r="1" fill="currentColor" />
            <circle cx="14.5" cy="11" r="1" fill="currentColor" />
            <path
              d="M10 14.5C10.8 15.3 13.2 15.3 14 14.5"
              stroke="currentColor"
              stroke-width="1.4"
              stroke-linecap="round"
            />
          </svg>
          <svg
            v-else-if="tab === 'settings'"
            class="nav-icon"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="2.8" stroke="currentColor" stroke-width="1.6" />
            <path
              d="M12 4.5V6.2M12 17.8V19.5M19.5 12H17.8M6.2 12H4.5M17.3 6.7L16.1 7.9M7.9 16.1L6.7 17.3M17.3 17.3L16.1 16.1M7.9 7.9L6.7 6.7"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
            />
          </svg>
          <svg v-else class="nav-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.6" />
            <circle cx="12" cy="8.5" r="1" fill="currentColor" />
            <path
              d="M12 11.5V16.5"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
            />
          </svg>
          <span class="nav-label">{{ t(tab) }}</span>
          <span v-if="tab === 'about' && hasUpdate" class="update-dot"></span>
        </button>
      </div>

      <div class="sidebar-footer">
        <button
          class="footer-status"
          :class="{ connected: socialStore.isConnected }"
          :title="socialStore.isConnected ? '' : t('disconnectedHint')"
          @click="!socialStore.isConnected && (activeTab = 'settings')"
        >
          <span class="status-dot"></span>
          {{
            socialStore.isConnected
              ? `${socialStore.onlinePeers.length} ${t('connected')}`
              : t('disconnected')
          }}
        </button>
      </div>
    </nav>

    <main class="content">
      <TodayView v-if="activeTab === 'today'" />

      <div v-else-if="activeTab === 'leaderboard'" class="list-view">
        <header class="view-header">
          <h2 class="view-title">{{ t('lbTitle') }}</h2>
          <span class="view-badge">
            {{ socialStore.onlinePeers.length + 1 }} {{ t('lbPeople') }}
          </span>
        </header>
        <Leaderboard />
      </div>

      <div v-else-if="activeTab === 'skins'" class="list-view">
        <header class="view-header">
          <h2 class="view-title">{{ t('skinsTitle') }}</h2>
        </header>
        <div class="skins-content">
          <SkinMarket />
        </div>
      </div>

      <SettingsView v-else-if="activeTab === 'settings'" />

      <AboutView v-else />
    </main>
  </div>
</template>

<style scoped>
@import '../styles/theme.css';

/* === Layout === */
.social-window {
  height: 100%;
  display: flex;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  transition:
    background 0.2s,
    color 0.2s;
}
.sidebar {
  width: 72px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 16px 0;
  flex-shrink: 0;
}
.sidebar-brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
  margin: 0 8px;
  color: var(--text-secondary);
}
.brand-logo {
  width: 28px;
  height: 28px;
  image-rendering: pixelated;
}
.brand-text {
  font-size: 9px;
  color: var(--text-tertiary);
  font-weight: 600;
  letter-spacing: 0.5px;
}
.lang-toggle {
  font-size: 8px;
  font-weight: 600;
  color: var(--text-muted);
  background: none;
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  padding: 1px 5px;
  cursor: pointer;
  transition: all 0.15s;
  letter-spacing: 0.3px;
  margin-top: 2px;
}
.lang-toggle:hover {
  color: var(--text-secondary);
  border-color: var(--border-hover);
  background: var(--bg-surface-hover);
}
.nav-items {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 8px;
}
.nav-btn {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 8px 4px;
  border: none;
  background: none;
  border-radius: 10px;
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
  color: var(--text-tertiary);
}
.update-dot {
  position: absolute;
  top: 5px;
  right: 10px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--error, #ef4444);
  box-shadow: 0 0 0 2px var(--bg-sidebar);
}
.nav-btn:hover {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
}
.nav-btn.active {
  background: var(--accent-bg-strong);
  color: var(--text);
}
.nav-icon {
  width: 18px;
  height: 18px;
}
.nav-label {
  font-size: 9px;
  font-weight: 500;
}
.sidebar-footer {
  padding: 8px;
}
.footer-status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-size: 9px;
  color: var(--text-tertiary);
  background: none;
  border: none;
  width: 100%;
  padding: 4px;
  border-radius: 6px;
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
}
.footer-status:not(.connected):hover {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
}
.footer-status.connected {
  color: var(--success);
}
.status-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--text-tertiary);
}
.connected .status-dot {
  background: var(--success);
}
.content {
  flex: 1;
  overflow-y: auto;
  min-width: 0;
}
.view-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 16px;
}
.view-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-bright);
  margin: 0;
  letter-spacing: -0.3px;
}
.view-badge {
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-surface);
  padding: 3px 8px;
  border-radius: 6px;
}
.list-view {
  padding-bottom: 24px;
}
.skins-content {
  padding: 0 24px;
}
</style>
