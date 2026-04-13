<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { enable, disable, isEnabled } from '@tauri-apps/plugin-autostart'
import { useSettingsStore } from '@/stores/settings'
import type { ThemeMode } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'
import type { MessageKey } from '@/composables/useI18n'

const settings = useSettingsStore()
const { t } = useI18n()
const autoStart = ref(false)
const autoStartLoading = ref(false)

const themeKeys: { value: ThemeMode; key: MessageKey }[] = [
  { value: 'light', key: 'settingsThemeLight' },
  { value: 'dark', key: 'settingsThemeDark' },
  { value: 'system', key: 'settingsThemeSystem' },
]

onMounted(async () => {
  try {
    autoStart.value = await isEnabled()
  } catch {
    /* not available in dev */
  }
})

async function toggleAutoStart() {
  autoStartLoading.value = true
  try {
    if (autoStart.value) {
      await disable()
      autoStart.value = false
    } else {
      await enable()
      autoStart.value = true
    }
  } catch (e) {
    console.error('autostart toggle failed', e)
  } finally {
    autoStartLoading.value = false
  }
}

watch(
  () => settings.nickname,
  () => {
    settings.persistUserFields()
  },
)

async function toggleShowOverFullscreen() {
  const newVal = !settings.showOverFullscreen
  settings.showOverFullscreen = newVal
  settings.persistUserFields()
  try {
    await invoke('set_show_over_fullscreen', { visible: newVal })
  } catch (e) {
    console.error('set_show_over_fullscreen failed', e)
  }
}
</script>

<template>
  <div class="settings-view">
    <header class="view-header">
      <h2 class="view-title">{{ t('settingsTitle') }}</h2>
    </header>

    <div class="form-section">
      <h3 class="section-heading">{{ t('settingsProfile') }}</h3>
      <div class="form-group">
        <label class="form-label">{{ t('settingsNickname') }}</label>
        <input
          v-model="settings.nickname"
          class="form-input"
          :placeholder="t('settingsNicknamePlaceholder')"
        />
      </div>
    </div>

    <div class="form-section">
      <h3 class="section-heading">{{ t('settingsGeneral') }}</h3>
      <div class="form-group row">
        <div>
          <label class="form-label">{{ t('settingsTheme') }}</label>
          <p class="form-hint">{{ t('settingsThemeHint') }}</p>
        </div>
        <div class="theme-switcher">
          <button
            v-for="opt in themeKeys"
            :key="opt.value"
            class="theme-option"
            :class="{ active: settings.theme === opt.value }"
            @click="settings.theme = opt.value"
          >
            {{ t(opt.key) }}
          </button>
        </div>
      </div>
      <div class="form-group row">
        <div>
          <label class="form-label">{{ t('settingsShowOverFullscreen') }}</label>
          <p class="form-hint">{{ t('settingsShowOverFullscreenHint') }}</p>
        </div>
        <button
          class="toggle"
          :class="{ on: settings.showOverFullscreen }"
          role="switch"
          :aria-checked="settings.showOverFullscreen"
          @click="toggleShowOverFullscreen"
        >
          <span class="toggle-thumb"></span>
        </button>
      </div>
      <div class="form-group row">
        <div>
          <label class="form-label">{{ t('settingsAutoStart') }}</label>
          <p class="form-hint">{{ t('settingsAutoStartHint') }}</p>
        </div>
        <button
          class="toggle"
          :class="{ on: autoStart }"
          :disabled="autoStartLoading"
          role="switch"
          :aria-checked="autoStart"
          @click="toggleAutoStart"
        >
          <span class="toggle-thumb"></span>
        </button>
      </div>
    </div>

    <div class="form-section">
      <h3 class="section-heading">{{ t('settingsLan') }}</h3>
      <div class="form-group row">
        <div>
          <label class="form-label">{{ t('settingsLan') }}</label>
          <p class="form-hint">{{ t('settingsLanHint') }}</p>
        </div>
        <button
          class="toggle"
          :class="{ on: settings.socialEnabled }"
          role="switch"
          :aria-checked="settings.socialEnabled"
          @click="settings.socialEnabled = !settings.socialEnabled"
        >
          <span class="toggle-thumb"></span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
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
.settings-view {
  padding-bottom: 24px;
}
.form-section {
  padding: 0 24px;
  margin-bottom: 24px;
}
.section-heading {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-dim);
  margin: 0 0 12px;
}
.form-group {
  margin-bottom: 16px;
}
.form-group.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.form-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-label);
  margin-bottom: 6px;
}
.form-group.row .form-label {
  margin-bottom: 0;
}
.form-hint {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 2px 0 0;
}
.form-input {
  width: 100%;
  padding: 8px 12px;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  border-radius: 8px;
  color: var(--text);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}
.form-input:focus {
  border-color: var(--accent);
}
.toggle {
  position: relative;
  width: 40px;
  height: 22px;
  border-radius: 11px;
  border: none;
  background: var(--toggle-bg);
  cursor: pointer;
  transition: background 0.2s;
  padding: 0;
  flex-shrink: 0;
}
.toggle.on {
  background: var(--accent);
}
.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: white;
  transition: transform 0.2s;
  box-shadow: 0 1px 3px var(--shadow-soft);
}
.toggle.on .toggle-thumb {
  transform: translateX(18px);
}

/* === Theme Switcher === */
.theme-switcher {
  display: flex;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  border-radius: 8px;
  padding: 2px;
  gap: 2px;
  flex-shrink: 0;
}

.theme-option {
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
  background: transparent;
  cursor: pointer;
  transition: all 0.15s;
}

.theme-option:hover {
  color: var(--text);
}

.theme-option.active {
  background: var(--accent);
  color: #fff;
  box-shadow: 0 1px 3px var(--shadow-soft);
}
</style>
