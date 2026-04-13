<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { openUrl } from '@tauri-apps/plugin-opener'
import { useSkinStore } from '@/stores/skin'
import { useSettingsStore } from '@/stores/settings'
import { getScoreColor } from '@/utils/activity'
import { resolveAnimation } from '@/utils/skin'
import { useI18n } from '@/composables/useI18n'
import SpriteRenderer from '@/pet/renderers/SpriteRenderer.vue'
import SkinImportSection from './SkinImportSection.vue'
import type { CatalogEntry } from '@/stores/skin'
import type { MovementState, SkinAnimationConfig } from '@/types'

const skinStore = useSkinStore()
const settings = useSettingsStore()
const { t } = useI18n()

const hoveredId = ref<string | null>(null)
const confirmRemoveId = ref<string | null>(null)
const removing = ref(false)
let hoverTimer: ReturnType<typeof setTimeout> | null = null

const PREVIEW_STATES: { state: MovementState; score: number }[] = [
  { state: 'idle', score: 5 },
  { state: 'walk', score: 30 },
  { state: 'run', score: 60 },
  { state: 'sprint', score: 90 },
]

onMounted(() => {
  if (!skinStore.catalogLoaded) {
    skinStore.loadCatalog()
  }
})

const currentEntry = computed(
  () => skinStore.catalog.find((e) => e.id === settings.currentSkinId) ?? null,
)

const allEntries = computed(() => skinStore.catalog)

const hoveredEntry = computed(() => skinStore.catalog.find((e) => e.id === hoveredId.value) ?? null)

interface PreviewCell {
  state: MovementState
  score: number
  anim: SkinAnimationConfig | null
  src: string
}

function buildPreviewCells(entry: CatalogEntry): PreviewCell[] {
  return PREVIEW_STATES.map((s) => {
    const result = resolveAnimation(s.state, entry.manifest)
    return {
      state: s.state,
      score: s.score,
      anim: result ? result.config : null,
      src: result ? `/skins/${entry.id}/${result.config.file}` : '',
    }
  })
}

const currentPreviewCells = computed(() =>
  currentEntry.value ? buildPreviewCells(currentEntry.value) : [],
)

const hoveredPreviewCells = computed(() =>
  hoveredEntry.value ? buildPreviewCells(hoveredEntry.value) : [],
)

function petAvatarSrc(skinId: string): string {
  return `/skins/${skinId}/pet.png`
}

function onEnter(id: string) {
  if (hoverTimer) clearTimeout(hoverTimer)
  hoverTimer = setTimeout(() => {
    hoveredId.value = id
  }, 200)
}

function onLeave() {
  if (hoverTimer) clearTimeout(hoverTimer)
  hoverTimer = null
  hoveredId.value = null
}

function selectSkin(entry: CatalogEntry) {
  settings.currentSkinId = entry.id
}

async function openSource(url: string) {
  try {
    await openUrl(url)
  } catch {
    /* noop */
  }
}

function requestRemove(skinId: string) {
  confirmRemoveId.value = skinId
}

function cancelRemove() {
  confirmRemoveId.value = null
}

async function confirmRemove() {
  const id = confirmRemoveId.value
  if (!id) return

  removing.value = true
  try {
    await skinStore.removeSkin(id)
  } finally {
    removing.value = false
    confirmRemoveId.value = null
  }
}
</script>

<template>
  <div class="skin-market">
    <div v-if="!skinStore.catalogLoaded" class="market-loading">
      <div v-for="i in 3" :key="i" class="loading-shimmer"></div>
    </div>

    <template v-else>
      <!-- 当前角色 -->
      <div v-if="currentEntry" class="current-skin">
        <div class="current-label">{{ t('skinsCurrent') }}</div>
        <div class="current-card">
          <div class="current-states">
            <div v-for="cell in currentPreviewCells" :key="cell.state" class="current-cell">
              <div class="current-anim">
                <SpriteRenderer
                  v-if="cell.anim?.sprite"
                  :src="cell.src"
                  :frame-width="cell.anim.sprite!.frameWidth"
                  :frame-height="cell.anim.sprite!.frameHeight"
                  :frame-count="cell.anim.sprite!.frameCount"
                  :columns="cell.anim.sprite!.columns"
                  :fps="cell.anim.sprite!.fps"
                  :start-frame="cell.anim.sprite!.startFrame ?? 0"
                  :loop="true"
                />
              </div>
              <span class="current-tag">
                <span class="state-dot" :style="{ background: getScoreColor(cell.score) }"></span>
                {{ t('state' + cell.state.charAt(0).toUpperCase() + cell.state.slice(1)) }}
              </span>
            </div>
          </div>
          <div class="current-info">
            <span class="current-name">{{ currentEntry.manifest.name }}</span>
            <span
              v-if="currentEntry.manifest.source"
              class="current-author source-link"
              @click.stop="openSource(currentEntry.manifest.source!)"
            >
              {{ currentEntry.manifest.author }}
            </span>
            <span v-else class="current-author">{{ currentEntry.manifest.author }}</span>
          </div>
        </div>
      </div>

      <!-- 全部角色 -->
      <div v-if="allEntries.length" class="other-skins">
        <div class="other-label">{{ t('skinsChange') }}</div>
        <div class="skin-strip" role="listbox" aria-label="角色选择">
          <button
            v-for="entry in allEntries"
            :key="entry.id"
            class="skin-item"
            :class="{ 'is-active': entry.id === settings.currentSkinId }"
            role="option"
            :aria-selected="entry.id === settings.currentSkinId"
            @click="entry.id !== settings.currentSkinId && selectSkin(entry)"
            @mouseenter="entry.id !== settings.currentSkinId && onEnter(entry.id)"
            @mouseleave="onLeave"
          >
            <div class="item-preview">
              <img
                class="item-pet-img"
                :src="petAvatarSrc(entry.id)"
                :alt="entry.manifest.name"
                @error="(e: Event) => ((e.target as HTMLImageElement).style.display = 'none')"
              />
            </div>
            <span class="item-name">{{ entry.manifest.name }}</span>
            <span v-if="entry.id === settings.currentSkinId" class="active-badge">
              {{ t('skinsActive') }}
            </span>
            <button
              v-if="!skinStore.isBuiltin(entry.id)"
              class="remove-btn"
              :title="t('skinsRemoveBtn')"
              @click.stop="requestRemove(entry.id)"
            >
              <svg viewBox="0 0 12 12" fill="none" width="10" height="10" aria-hidden="true">
                <path
                  d="M3 3l6 6M9 3l-6 6"
                  stroke="currentColor"
                  stroke-width="1.4"
                  stroke-linecap="round"
                />
              </svg>
            </button>
          </button>
        </div>

        <Transition name="popover">
          <div
            v-if="hoveredEntry"
            class="state-popover"
            @mouseenter="hoveredId = hoveredEntry!.id"
            @mouseleave="onLeave"
          >
            <div class="popover-header">
              <span class="popover-name">{{ hoveredEntry.manifest.name }}</span>
              <span
                v-if="hoveredEntry.manifest.source"
                class="popover-author source-link"
                @click.stop="openSource(hoveredEntry.manifest.source!)"
              >
                {{ hoveredEntry.manifest.author }}
              </span>
              <span v-else class="popover-author">{{ hoveredEntry.manifest.author }}</span>
            </div>
            <div class="popover-grid">
              <div v-for="cell in hoveredPreviewCells" :key="cell.state" class="popover-cell">
                <div class="cell-anim">
                  <SpriteRenderer
                    v-if="cell.anim?.sprite"
                    :src="cell.src"
                    :frame-width="cell.anim.sprite!.frameWidth"
                    :frame-height="cell.anim.sprite!.frameHeight"
                    :frame-count="cell.anim.sprite!.frameCount"
                    :columns="cell.anim.sprite!.columns"
                    :fps="cell.anim.sprite!.fps"
                    :start-frame="cell.anim.sprite!.startFrame ?? 0"
                    :loop="true"
                  />
                </div>
                <span class="cell-tag">
                  <span class="state-dot" :style="{ background: getScoreColor(cell.score) }"></span>
                  {{ t('state' + cell.state.charAt(0).toUpperCase() + cell.state.slice(1)) }}
                </span>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- 删除确认 -->
      <Transition name="status">
        <div v-if="confirmRemoveId" class="remove-confirm">
          <span class="confirm-text">{{ t('skinsRemoveConfirm') }}</span>
          <div class="confirm-actions">
            <button class="confirm-btn cancel" @click="cancelRemove">{{ t('skinsCancel') }}</button>
            <button class="confirm-btn danger" :disabled="removing" @click="confirmRemove">
              {{ removing ? t('skinsRemoving') : t('skinsRemoveOk') }}
            </button>
          </div>
        </div>
      </Transition>

      <SkinImportSection />
    </template>
  </div>
</template>

<style scoped>
.skin-market {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.market-loading {
  display: flex;
  gap: 8px;
  overflow: hidden;
}
.loading-shimmer {
  width: 64px;
  height: 80px;
  border-radius: 10px;
  background: linear-gradient(
    110deg,
    var(--bg-surface) 30%,
    var(--bg-surface-hover) 50%,
    var(--bg-surface) 70%
  );
  background-size: 200% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
  flex-shrink: 0;
}
@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

.current-label,
.other-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}
.current-card {
  background: var(--accent-bg);
  border: 1px solid var(--accent-border);
  border-radius: 12px;
  padding: 12px;
}
.current-states {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  margin-bottom: 8px;
}
.current-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.current-anim {
  width: 52px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--anim-bg);
  border-radius: 8px;
  overflow: hidden;
}
.current-tag {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 9px;
  font-weight: 600;
  color: var(--text-label);
  letter-spacing: 0.3px;
}
.state-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}
.current-info {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}
.current-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent-brightest);
}
.current-author {
  font-size: 10px;
  color: var(--text-tertiary);
}
.source-link {
  text-decoration: none;
  cursor: pointer;
  transition: color 0.15s;
}
.source-link:hover {
  color: var(--accent-text);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.other-skins {
  position: relative;
}
.skin-strip {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 4px;
  scrollbar-width: thin;
  scrollbar-color: var(--scrollbar) transparent;
}
.skin-strip::-webkit-scrollbar {
  height: 4px;
}
.skin-strip::-webkit-scrollbar-track {
  background: transparent;
}
.skin-strip::-webkit-scrollbar-thumb {
  background: var(--scrollbar);
  border-radius: 2px;
}

.skin-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 10px 12px 8px;
  background: var(--bg-surface);
  border: 1.5px solid var(--border);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s ease-out;
  color: inherit;
  flex-shrink: 0;
  min-width: 72px;
}
.skin-item:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-hover);
  transform: translateY(-1px);
}
.item-preview {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  overflow: hidden;
}
.item-pet-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  image-rendering: pixelated;
}
.item-name {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
}
.skin-item.is-active {
  border-color: var(--accent-border-strong);
  background: var(--accent-bg);
  cursor: default;
}
.skin-item.is-active .item-name {
  color: var(--accent-brightest);
}
.active-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  font-size: 8px;
  font-weight: 700;
  color: var(--accent-text);
  background: var(--accent-bg);
  padding: 1px 5px;
  border-radius: 4px;
  letter-spacing: 0.3px;
}

.remove-btn {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--danger-bg);
  border: none;
  border-radius: 4px;
  color: var(--danger);
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s;
  padding: 0;
}
.skin-item:hover .remove-btn {
  opacity: 1;
}
.remove-btn:hover {
  background: var(--danger-bg-strong);
  color: var(--danger-text);
}

.remove-confirm {
  background: var(--danger-bg);
  border: 1px solid var(--danger-border);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.confirm-text {
  font-size: 11px;
  color: var(--danger-text);
  font-weight: 500;
}
.confirm-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.confirm-btn {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
}
.confirm-btn.cancel {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
}
.confirm-btn.cancel:hover {
  background: var(--border-hover);
}
.confirm-btn.danger {
  background: var(--danger-bg-strong);
  color: var(--danger);
}
.confirm-btn.danger:hover {
  background: var(--danger-border);
  color: var(--danger-text);
}
.confirm-btn.danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.state-popover {
  margin-top: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: 14px;
  padding: 12px;
  box-shadow: 0 8px 32px var(--shadow);
}
.popover-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
}
.popover-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-bright);
}
.popover-author {
  font-size: 10px;
  color: var(--text-tertiary);
}
.popover-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.popover-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.cell-anim {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-surface);
  border-radius: 10px;
  overflow: hidden;
}
.cell-tag {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 9px;
  font-weight: 600;
  color: var(--text-label);
  letter-spacing: 0.3px;
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

.popover-enter-active {
  transition: all 0.15s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.popover-leave-active {
  transition: all 0.1s ease-in;
}
.popover-enter-from {
  opacity: 0;
  transform: translateY(-4px);
}
.popover-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
