<script setup lang="ts">
import { ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
import { useSkinStore } from '@/stores/skin'
import { useI18n } from '@/composables/useI18n'
import SkinGuide from './SkinGuide.vue'

const skinStore = useSkinStore()
const { t } = useI18n()

const showGuide = ref(false)
const importStatus = ref<{ type: 'success' | 'error' | 'info'; text: string } | null>(null)
const importing = ref(false)
let statusTimer: ReturnType<typeof setTimeout> | null = null

function showStatus(type: 'success' | 'error' | 'info', text: string) {
  importStatus.value = { type, text }
  if (statusTimer) clearTimeout(statusTimer)
  statusTimer = setTimeout(() => {
    importStatus.value = null
  }, 4000)
}

async function importFromFolder() {
  const selected = await open({ directory: true, title: t('skinsSelectFolder') })
  if (!selected) return

  importing.value = true
  try {
    const result = await invoke<{ success: boolean; skin_id: string; message: string }>(
      'import_skin_from_dir',
      { sourceDir: selected },
    )
    if (result.success) {
      showStatus('success', result.message)
      await new Promise((r) => setTimeout(r, 300))
      await skinStore.loadCatalog()
    } else {
      showStatus('error', result.message)
    }
  } catch (err) {
    showStatus('error', `${t('skinImportFail')}: ${err}`)
  } finally {
    importing.value = false
  }
}

async function importFromZip() {
  const selected = await open({
    title: t('skinsSelectZip'),
    filters: [{ name: t('skinsZipFilter'), extensions: ['zip'] }],
  })
  if (!selected) return

  importing.value = true
  try {
    const result = await invoke<{ success: boolean; skin_id: string; message: string }>(
      'import_skin_from_zip',
      { zipPath: selected },
    )
    if (result.success) {
      showStatus('success', result.message)
      await new Promise((r) => setTimeout(r, 300))
      await skinStore.loadCatalog()
    } else {
      showStatus('error', result.message)
    }
  } catch (err) {
    showStatus('error', `${t('skinImportFail')}: ${err}`)
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <div class="import-section">
    <div class="import-header">
      <span class="import-title">{{ t('skinsImport') }}</span>
      <button class="guide-toggle" @click="showGuide = !showGuide">
        <svg viewBox="0 0 16 16" fill="none" width="14" height="14" aria-hidden="true">
          <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.2" />
          <path
            d="M6.5 6.5a1.5 1.5 0 112.12 1.37c-.36.21-.62.58-.62 1.13"
            stroke="currentColor"
            stroke-width="1.2"
            stroke-linecap="round"
          />
          <circle cx="8" cy="11.5" r="0.6" fill="currentColor" />
        </svg>
        {{ t('skinsGuideFormat') }}
      </button>
    </div>

    <Transition name="guide">
      <SkinGuide v-if="showGuide" @status="showStatus" />
    </Transition>

    <div class="import-actions">
      <button class="import-btn" :disabled="importing" @click="importFromFolder">
        <svg class="import-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path
            d="M3 5.5A1.5 1.5 0 014.5 4H8l1.5 2h5A1.5 1.5 0 0116 7.5v6a1.5 1.5 0 01-1.5 1.5h-10A1.5 1.5 0 013 13.5v-8z"
            stroke="currentColor"
            stroke-width="1.4"
          />
          <path
            d="M9.5 9v4M7.5 11h4"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
          />
        </svg>
        {{ t('skinsImportFolder') }}
      </button>
      <button class="import-btn" :disabled="importing" @click="importFromZip">
        <svg class="import-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <rect
            x="4"
            y="3"
            width="12"
            height="14"
            rx="1.5"
            stroke="currentColor"
            stroke-width="1.4"
          />
          <path
            d="M8 3v14M10 5h-2M10 7h-2M10 9h-2M10 11h-2"
            stroke="currentColor"
            stroke-width="1.2"
          />
          <rect x="8" y="12" width="2" height="2" rx="0.5" stroke="currentColor" stroke-width="1" />
        </svg>
        {{ t('skinsImportZip') }}
      </button>
    </div>
    <Transition name="status">
      <div v-if="importStatus" class="import-status" :class="importStatus.type">
        {{ importStatus.text }}
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.import-section {
  margin-top: 8px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.import-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.import-title {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.guide-toggle {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  color: var(--text-dim);
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all 0.15s;
}

.guide-toggle:hover {
  color: var(--accent-bright);
  background: var(--accent-bg);
}

.guide-enter-active {
  transition: all 0.2s ease-out;
}
.guide-leave-active {
  transition: all 0.15s ease-in;
}
.guide-enter-from,
.guide-leave-to {
  opacity: 0;
  max-height: 0;
  margin-bottom: 0;
  padding: 0 12px;
  overflow: hidden;
}
.guide-enter-to,
.guide-leave-from {
  max-height: 200px;
}

.import-actions {
  display: flex;
  gap: 8px;
}

.import-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 8px 12px;
  border: 1.5px dashed var(--border-strong);
  background: var(--bg-surface);
  color: var(--text-secondary);
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.import-btn:hover:not(:disabled) {
  border-color: var(--accent-border-strong);
  background: var(--accent-bg);
  color: var(--accent-brightest);
}

.import-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.import-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.import-status {
  margin-top: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 500;
}

.import-status.success {
  background: var(--success-bg);
  color: var(--success);
  border: 1px solid var(--success-border);
}

.import-status.error {
  background: var(--danger-bg);
  color: var(--danger);
  border: 1px solid var(--danger-border);
}

.import-status.info {
  background: var(--info-bg);
  color: var(--accent-bright);
  border: 1px solid var(--info-border);
}

.status-enter-active {
  transition: all 0.2s ease-out;
}
.status-leave-active {
  transition: all 0.15s ease-in;
}
.status-enter-from,
.status-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
