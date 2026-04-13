<script setup lang="ts">
import { openUrl } from '@tauri-apps/plugin-opener'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

const emit = defineEmits<{
  status: [type: 'success' | 'error' | 'info', text: string]
}>()

async function downloadExample() {
  try {
    await openUrl('https://aibubu.app/demo/vita-example.zip')
  } catch {
    emit('status', 'info', '请从官网下载示例：aibubu.app')
  }
}
</script>

<template>
  <div class="guide-panel">
    <div class="guide-content">
      <div class="guide-row">
        <span class="guide-label">{{ t('skinsFormat') }}</span>
        <span class="guide-val">{{ t('skinsFormatVal') }}</span>
      </div>
      <div class="guide-row">
        <span class="guide-label">{{ t('skinsRequired') }}</span>
        <span class="guide-val">{{ t('skinsRequiredVal') }}</span>
      </div>
      <div class="guide-row">
        <span class="guide-label">{{ t('skinsPetPng') }}</span>
        <span class="guide-val">{{ t('skinsPetPngVal') }}</span>
      </div>
      <div class="guide-row">
        <span class="guide-label">{{ t('skinsStates') }}</span>
        <span class="guide-val">{{ t('skinsStatesVal') }}</span>
      </div>
      <div class="guide-row">
        <span class="guide-label">{{ t('skinsSkinJson') }}</span>
        <span class="guide-val">{{ t('skinsSkinJsonVal') }}</span>
      </div>
      <div class="guide-row">
        <span class="guide-label">{{ t('skinsOptional') }}</span>
        <span class="guide-val">{{ t('skinsOptionalVal') }}</span>
      </div>
    </div>
    <div class="guide-actions">
      <button class="example-btn" @click="downloadExample">
        <svg viewBox="0 0 16 16" fill="none" width="13" height="13" aria-hidden="true">
          <path
            d="M8 2v8M5 7l3 3 3-3M3 12h10"
            stroke="currentColor"
            stroke-width="1.3"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        {{ t('skinsDownloadExample') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.guide-panel {
  background: var(--accent-bg);
  border: 1px solid var(--accent-border);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 10px;
}

.guide-content {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 8px;
}

.guide-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 10px;
}

.guide-label {
  color: var(--text-dim);
  min-width: 56px;
  flex-shrink: 0;
}

.guide-val {
  color: var(--text-label);
  font-family: 'SF Mono', 'Menlo', monospace;
  font-size: 9.5px;
}

.guide-actions {
  display: flex;
  gap: 6px;
}

.example-btn {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--accent-text);
  background: var(--info-bg);
  border: 1px solid var(--accent-border);
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
  transition: all 0.15s;
  justify-content: center;
  text-decoration: none;
}

.example-btn:hover {
  background: var(--accent-bg-strong);
  color: var(--accent-bright);
}
</style>
