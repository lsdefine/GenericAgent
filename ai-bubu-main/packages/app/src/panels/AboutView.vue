<script setup lang="ts">
import { openUrl } from '@tauri-apps/plugin-opener'
import { useI18n } from '@/composables/useI18n'
import { useAutoUpdater } from '@/composables/useAutoUpdater'

const { t } = useI18n()
const appVersion = __APP_VERSION__
const {
  status: updateStatus,
  newVersion,
  errorMessage: updateError,
  checkForUpdate,
  downloadAndInstall,
  installAndRelaunch,
} = useAutoUpdater()

async function open(url: string) {
  try {
    await openUrl(url)
  } catch (e) {
    console.error('openUrl failed', e)
  }
}
</script>

<template>
  <div class="about-view">
    <header class="view-header">
      <h2 class="view-title">{{ t('about') }}</h2>
    </header>

    <div class="about-brand">
      <img class="about-logo" src="/skins/vita/pet.png" alt="AIbubu" />
      <div class="brand-info">
        <p class="brand-name">{{ t('brand') }}</p>
        <p class="brand-desc">{{ t('aboutDesc') }}</p>
        <div class="brand-version-row">
          <span class="brand-version">v{{ appVersion }}</span>
          <span class="version-sep">·</span>
          <template v-if="updateStatus === 'idle' || updateStatus === 'error'">
            <button class="inline-update-btn" @click="checkForUpdate(false)">
              {{ t('updateCheckBtn') }}
            </button>
          </template>
          <template v-else-if="updateStatus === 'checking'">
            <span class="update-inline-status">{{ t('updateChecking') }}</span>
          </template>
          <template v-else-if="updateStatus === 'up-to-date'">
            <span class="update-inline-status up-to-date">{{ t('updateUpToDate') }}</span>
          </template>
          <template v-else-if="updateStatus === 'available'">
            <button class="inline-update-btn accent" @click="downloadAndInstall()">
              {{ t('updateNewVersion') }} {{ newVersion }} — {{ t('updateDownloadBtn') }}
            </button>
          </template>
          <template v-else-if="updateStatus === 'downloading'">
            <span class="update-inline-status">{{ t('updateDownloading') }}</span>
          </template>
          <template v-else-if="updateStatus === 'ready'">
            <button class="inline-update-btn accent" @click="installAndRelaunch()">
              {{ t('updateRestartBtn') }}
            </button>
          </template>
        </div>
        <p v-if="updateStatus === 'error'" class="update-error">{{ updateError }}</p>
      </div>
    </div>

    <div class="about-section">
      <div
        class="about-row"
        role="button"
        tabindex="0"
        @click="open('https://aibubu.app')"
        @keydown.enter="open('https://aibubu.app')"
        @keydown.space.prevent="open('https://aibubu.app')"
      >
        <div class="row-icon-wrap">
          <svg class="row-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.4" />
            <path d="M2.5 10H17.5" stroke="currentColor" stroke-width="1.4" />
            <path
              d="M10 2.5C11.8 4.5 13 7 13 10C13 13 11.8 15.5 10 17.5"
              stroke="currentColor"
              stroke-width="1.4"
            />
            <path
              d="M10 2.5C8.2 4.5 7 7 7 10C7 13 8.2 15.5 10 17.5"
              stroke="currentColor"
              stroke-width="1.4"
            />
          </svg>
        </div>
        <div class="row-content">
          <span class="row-label">{{ t('aboutWebsite') }}</span>
          <span class="row-value">aibubu.app</span>
        </div>
        <svg class="row-arrow" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path
            d="M6 4L10 8L6 12"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>

      <div
        class="about-row"
        role="button"
        tabindex="0"
        @click="open('https://github.com/funAgent/ai-bubu')"
        @keydown.enter="open('https://github.com/funAgent/ai-bubu')"
        @keydown.space.prevent="open('https://github.com/funAgent/ai-bubu')"
      >
        <div class="row-icon-wrap">
          <svg class="row-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path
              d="M10 2C5.58 2 2 5.58 2 10C2 13.54 4.29 16.53 7.47 17.59C7.87 17.66 8.02 17.42 8.02 17.21C8.02 17.02 8.01 16.39 8.01 15.72C6 16.07 5.48 15.22 5.32 14.78C5.23 14.55 4.84 13.84 4.5 13.65C4.22 13.5 3.82 13.15 4.49 13.14C5.12 13.13 5.57 13.73 5.72 13.97C6.44 15.19 7.57 14.85 8.05 14.64C8.12 14.11 8.33 13.76 8.56 13.55C6.76 13.34 4.88 12.63 4.88 9.61C4.88 8.71 5.23 7.97 5.74 7.39C5.66 7.18 5.38 6.34 5.82 5.22C5.82 5.22 6.49 5 8.02 6.04C8.66 5.86 9.34 5.77 10.02 5.77C10.7 5.77 11.38 5.86 12.02 6.04C13.55 4.99 14.22 5.22 14.22 5.22C14.66 6.34 14.38 7.18 14.3 7.39C14.81 7.97 15.16 8.7 15.16 9.61C15.16 12.64 13.27 13.34 11.47 13.55C11.76 13.8 12.01 14.29 12.01 15.03C12.01 16.08 12 16.93 12 17.21C12 17.42 12.15 17.67 12.55 17.59C15.73 16.53 18.02 13.53 18.02 10C18.02 5.58 14.44 2 10.02 2H10Z"
              fill="currentColor"
            />
          </svg>
        </div>
        <div class="row-content">
          <span class="row-label">{{ t('aboutGitHub') }}</span>
          <span class="row-hint">{{ t('aboutGitHubHint') }}</span>
        </div>
        <svg class="row-arrow" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path
            d="M6 4L10 8L6 12"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>

      <div
        class="about-row"
        role="button"
        tabindex="0"
        @click="open('https://github.com/funAgent/ai-bubu/issues')"
        @keydown.enter="open('https://github.com/funAgent/ai-bubu/issues')"
        @keydown.space.prevent="open('https://github.com/funAgent/ai-bubu/issues')"
      >
        <div class="row-icon-wrap">
          <svg class="row-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path
              d="M17 10C17 13.866 13.866 17 10 17C8.62 17 7.34 16.6 6.25 15.9L3 17L4.1 13.75C3.4 12.66 3 11.38 3 10C3 6.134 6.134 3 10 3C13.866 3 17 6.134 17 10Z"
              stroke="currentColor"
              stroke-width="1.4"
              stroke-linejoin="round"
            />
            <circle cx="7.5" cy="10" r="0.8" fill="currentColor" />
            <circle cx="10" cy="10" r="0.8" fill="currentColor" />
            <circle cx="12.5" cy="10" r="0.8" fill="currentColor" />
          </svg>
        </div>
        <div class="row-content">
          <span class="row-label">{{ t('aboutFeedback') }}</span>
          <span class="row-hint">{{ t('aboutFeedbackHint') }}</span>
        </div>
        <svg class="row-arrow" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path
            d="M6 4L10 8L6 12"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>
    </div>

    <div class="about-section">
      <div class="about-row static">
        <div class="row-icon-wrap">
          <svg class="row-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <rect
              x="3"
              y="5"
              width="14"
              height="10"
              rx="2"
              stroke="currentColor"
              stroke-width="1.4"
            />
            <path d="M7 9H13" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
            <path d="M7 12H10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
        </div>
        <div class="row-content">
          <span class="row-label">{{ t('aboutLicense') }}</span>
        </div>
        <span class="row-value-static">MIT</span>
      </div>

      <div class="about-row static">
        <div class="row-icon-wrap">
          <svg class="row-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <circle cx="10" cy="7" r="3.5" stroke="currentColor" stroke-width="1.4" />
            <path
              d="M4 17C4 14 6.5 12 10 12C13.5 12 16 14 16 17"
              stroke="currentColor"
              stroke-width="1.4"
              stroke-linecap="round"
            />
          </svg>
        </div>
        <div class="row-content">
          <span class="row-label">{{ t('aboutDeveloper') }}</span>
        </div>
        <span class="row-value-static">funAgent</span>
      </div>
    </div>

    <div class="privacy-card">
      <div class="privacy-header">
        <svg class="privacy-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path
            d="M8 1.5L3 3.5V7.5C3 10.8 5.2 13.6 8 14.5C10.8 13.6 13 10.8 13 7.5V3.5L8 1.5Z"
            stroke="currentColor"
            stroke-width="1.2"
            stroke-linejoin="round"
          />
          <path
            d="M6 8L7.5 9.5L10.5 6.5"
            stroke="currentColor"
            stroke-width="1.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <span class="privacy-title">{{ t('aboutPrivacy') }}</span>
      </div>
      <p class="privacy-desc">{{ t('aboutPrivacyHint') }}</p>
      <button class="privacy-link" @click="open('https://aibubu.app/privacy')">
        {{ t('aboutPrivacyPolicy') }}
        <svg class="link-arrow-sm" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path
            d="M3 2H10V9"
            stroke="currentColor"
            stroke-width="1.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path d="M10 2L2 10" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.about-view {
  padding: 0 20px 12px;
}
.view-header {
  display: flex;
  align-items: center;
  padding: 14px 0 10px;
}
.view-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-bright);
  margin: 0;
  letter-spacing: -0.3px;
}

/* === Brand Card === */
.about-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: var(--bg-surface);
  border-radius: 10px;
  border: 1px solid var(--border);
  margin-bottom: 8px;
}
.about-logo {
  width: 36px;
  height: 36px;
  image-rendering: pixelated;
  flex-shrink: 0;
}
.brand-info {
  min-width: 0;
  flex: 1;
}
.brand-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-bright);
  margin: 0;
  letter-spacing: -0.2px;
}
.brand-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 1px 0 0;
}
.brand-version-row {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 3px;
}
.brand-version {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.version-sep {
  font-size: 11px;
  color: var(--text-muted);
}
.inline-update-btn {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  transition: color 0.15s;
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 2px;
}
.inline-update-btn:hover {
  color: var(--text);
}
.inline-update-btn.accent {
  color: var(--accent);
}
.inline-update-btn.accent:hover {
  opacity: 0.85;
}
.update-inline-status {
  font-size: 11px;
  color: var(--text-tertiary);
}
.update-inline-status.up-to-date {
  color: var(--success, #22c55e);
}
.update-error {
  font-size: 10px;
  color: var(--error, #ef4444);
  margin: 2px 0 0;
}

/* === Section === */
.about-section {
  background: var(--bg-surface);
  border-radius: 10px;
  border: 1px solid var(--border);
  margin-bottom: 8px;
  overflow: hidden;
}

/* === Row === */
.about-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  cursor: pointer;
  transition: background 0.15s;
}
.about-row:not(:last-child) {
  border-bottom: 1px solid var(--border);
}
.about-row:hover:not(.static) {
  background: var(--bg-surface-hover);
}
.about-row.static {
  cursor: default;
}
.row-icon-wrap {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 5px;
  background: var(--accent-bg-strong);
  flex-shrink: 0;
}
.row-icon {
  width: 14px;
  height: 14px;
  color: var(--accent);
}
.row-content {
  flex: 1;
  min-width: 0;
}
.row-label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-label);
}
.row-value {
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 500;
}
.row-hint {
  display: block;
  font-size: 10px;
  color: var(--text-tertiary);
  margin-top: 1px;
}
.row-value-static {
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 500;
  flex-shrink: 0;
}
.row-arrow {
  width: 14px;
  height: 14px;
  color: var(--text-muted);
  flex-shrink: 0;
}

/* === Privacy Card === */
.privacy-card {
  padding: 10px 12px;
  background: var(--bg-surface);
  border-radius: 10px;
  border: 1px solid var(--border);
}
.privacy-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.privacy-icon {
  width: 14px;
  height: 14px;
  color: var(--success);
  flex-shrink: 0;
}
.privacy-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-label);
}
.privacy-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  margin: 0 0 6px;
  line-height: 1.4;
}
.privacy-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 500;
  color: var(--accent);
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  transition: opacity 0.15s;
}
.privacy-link:hover {
  opacity: 0.8;
}
.link-arrow-sm {
  width: 10px;
  height: 10px;
}
</style>
