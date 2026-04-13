<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import PetRenderer from './pet/PetRenderer.vue'
import PeerOverlay from './pet/PeerOverlay.vue'
import StepDisplay from './pet/StepDisplay.vue'
import PetEffects from './pet/PetEffects.vue'
import MoodEffect from './pet/MoodEffect.vue'
import SocialPanel from './panels/SocialPanel.vue'
import { useMonitor } from './composables/useMonitor'
import { useActivityScore } from './composables/useActivityScore'
import { useStepCounter } from './composables/useStepCounter'
import { useSocial } from './composables/useSocial'
import { usePetMood } from './composables/usePetMood'
import { useTrayIcon } from './composables/useTrayIcon'
import { useWindowSize } from './composables/useWindowSize'
import { useI18n } from './composables/useI18n'
import { usePetInteraction } from './composables/usePetInteraction'
import { useSkinStore } from './stores/skin'
import { usePetStore } from './stores/pet'
import { useSettingsStore } from './stores/settings'

let cleanupMockPeers: (() => void) | null = null
if (import.meta.env.VITE_MOCK_PEERS === 'true') {
  import('./dev/useMockPeers').then(({ startMockPeers }) => {
    cleanupMockPeers = startMockPeers()
  })
}

const settingsStore = useSettingsStore()
const { t } = useI18n()

useMonitor()
useActivityScore()
useStepCounter()
useSocial()
usePetMood()
const skinStore = useSkinStore()
const petStore = usePetStore()
skinStore.loadCatalog()
useTrayIcon()

const currentWindow = getCurrentWindow()
const isSocialWindow = currentWindow.label === 'social'
const isPetWindow = currentWindow.label === 'pet'

if (isPetWindow) {
  import('./composables/useAutoUpdater').then(({ useAutoUpdater }) => {
    const { checkForUpdate, startPeriodicCheck } = useAutoUpdater()
    checkForUpdate(true)
    startPeriodicCheck()
  })
}

if (isSocialWindow) {
  onMounted(() => {
    currentWindow.onCloseRequested(async (event) => {
      event.preventDefault()
      await currentWindow.hide()
    })
  })
}

if (isPetWindow) {
  useWindowSize()

  onMounted(() => {
    invoke('set_show_over_fullscreen', { visible: settingsStore.showOverFullscreen }).catch((e) =>
      console.error('set_show_over_fullscreen failed', e),
    )
  })

  watch(
    () => settingsStore.showOverFullscreen,
    (val) => {
      invoke('set_show_over_fullscreen', { visible: val }).catch((e) =>
        console.error('set_show_over_fullscreen failed', e),
      )
    },
  )
}

const {
  showTooltip,
  isHovering,
  pressing,
  onWindowEnter,
  onWindowLeave,
  onPetEnter,
  onPetLeave,
  onWindowMouseDown,
  onWindowMouseUp,
  onContextMenu,
} = usePetInteraction()

function onStorageChange(e: StorageEvent) {
  if (e.key === 'aibubu-skin' && e.newValue) {
    settingsStore.syncSkinId(e.newValue)
  }
}

onMounted(() => {
  window.addEventListener('storage', onStorageChange)
})

onUnmounted(() => {
  window.removeEventListener('storage', onStorageChange)
  if (cleanupMockPeers) cleanupMockPeers()
})
</script>

<template>
  <!-- Social window -->
  <SocialPanel v-if="isSocialWindow" />

  <!-- Pet window -->
  <div
    v-else
    class="pet-app"
    :class="{ hovering: isHovering, pressing }"
    @mouseenter="onWindowEnter"
    @mouseleave="onWindowLeave"
    @mousedown="onWindowMouseDown"
    @mouseup="onWindowMouseUp"
    @contextmenu="onContextMenu"
  >
    <Transition name="drag-hint">
      <div v-if="isHovering" class="drag-hint">
        <span class="grip-icon" aria-hidden="true"></span>
        <span class="drag-text">{{ t('dragHint') }}</span>
      </div>
    </Transition>
    <div class="pet-zone">
      <PeerOverlay>
        <div class="pet-center" @mouseenter="onPetEnter" @mouseleave="onPetLeave">
          <Transition name="tooltip">
            <StepDisplay v-if="showTooltip" class="step-tooltip" />
          </Transition>
          <MoodEffect
            v-if="petStore.moodState !== 'normal'"
            :mood="petStore.moodState"
            class="mood-layer"
          />
          <PetEffects class="effects-layer" />
          <PetRenderer />
        </div>
      </PeerOverlay>
    </div>
  </div>
</template>

<style scoped>
.pet-app {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  padding-bottom: 4px;
  background: transparent;
  cursor: grab;
  border-radius: 10px;
  transition:
    box-shadow 0.3s ease,
    background 0.3s ease;
}

.pet-app.hovering {
  box-shadow:
    inset 0 0 0 1px rgba(128, 128, 128, 0.15),
    0 0 8px rgba(128, 128, 128, 0.06);
}

.pet-app.pressing {
  cursor: grabbing;
  box-shadow:
    inset 0 0 0 1px rgba(128, 128, 128, 0.2),
    0 0 6px rgba(128, 128, 128, 0.08);
}

.drag-hint {
  position: absolute;
  top: 3px;
  left: 5px;
  display: flex;
  align-items: center;
  gap: 3px;
  pointer-events: none;
  user-select: none;
}

.grip-icon {
  display: inline-grid;
  grid-template-columns: 2px 2px;
  gap: 1.5px;
  width: 7px;
  height: 9px;
}
.grip-icon::before,
.grip-icon::after {
  content: '';
  width: 2px;
  height: 2px;
  border-radius: 50%;
  background: rgba(128, 128, 128, 0.45);
  box-shadow:
    0 3.5px 0 rgba(128, 128, 128, 0.45),
    0 7px 0 rgba(128, 128, 128, 0.45);
}

.drag-text {
  font-size: 8px;
  color: rgba(128, 128, 128, 0.5);
  white-space: nowrap;
  letter-spacing: 0.2px;
}

.drag-hint-enter-active {
  transition: opacity 0.25s ease;
}
.drag-hint-leave-active {
  transition: opacity 0.15s ease;
}
.drag-hint-enter-from,
.drag-hint-leave-to {
  opacity: 0;
}

.pet-zone {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.pet-center {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.step-tooltip {
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  margin-bottom: 0;
  z-index: 5;
  pointer-events: none;
}

.mood-layer {
  z-index: 10;
}

.effects-layer {
  z-index: 20;
}

.tooltip-enter-active {
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.tooltip-leave-active {
  transition: all 0.12s ease-in;
}
.tooltip-enter-from {
  opacity: 0;
  transform: translateX(-50%) translateY(4px) scale(0.92);
}
.tooltip-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(3px) scale(0.95);
}
</style>
