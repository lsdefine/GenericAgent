<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted } from 'vue'
import type { PeerInfo } from '@/types'
import { useI18n } from '@/composables/useI18n'
import { useSkinStore } from '@/stores/skin'
import MoodIcon from './MoodIcon.vue'

const { t, isZh } = useI18n()
const skinStore = useSkinStore()

const props = defineProps<{
  count: number
  peers: PeerInfo[]
  side: 'left' | 'right'
}>()

const hovered = ref(false)
const badgeEl = ref<HTMLElement | null>(null)
const tooltipPos = ref({ top: '0px', left: '0px' })
const tooltipMaxH = ref('152px')
const arrowLeft = ref('50%')

let hideTimer: ReturnType<typeof setTimeout> | null = null

const label = computed(() => `+${props.count}`)

const peerRows = computed(() =>
  props.peers.map((p) => {
    const name = p.nickname || t('lbSelf')
    const steps = p.dailySteps.toLocaleString()
    const stepsLabel = isZh.value ? `${steps}步` : `${steps} steps`
    const avatarUrl = skinStore.isBuiltin(p.petSkin) ? `/skins/${p.petSkin}/pet.png` : null
    const initial = (p.nickname || '?').charAt(0)
    const moodState = p.moodState ?? 'normal'
    return { name, stepsLabel, avatarUrl, initial, moodState }
  }),
)

function cancelHide() {
  if (hideTimer) {
    clearTimeout(hideTimer)
    hideTimer = null
  }
}

function scheduleHide() {
  cancelHide()
  hideTimer = setTimeout(() => {
    hovered.value = false
  }, 120)
}

function calcPosition() {
  if (!badgeEl.value) return
  const rect = badgeEl.value.getBoundingClientRect()
  const winW = window.innerWidth
  const tipW = 150

  const spaceAbove = rect.top - 4
  const maxH = Math.max(50, Math.min(152, spaceAbove - 8))

  const rowH = 24
  const padding = 12
  const tipH = Math.min(maxH, props.peers.length * rowH + padding)

  let top = rect.top - tipH - 6
  if (top < 2) top = 2

  const badgeCenterX = rect.left + rect.width / 2
  let left: number
  if (props.side === 'left') {
    left = badgeCenterX - tipW + 20
  } else {
    left = badgeCenterX - 20
  }
  if (left < 2) left = 2
  if (left + tipW > winW - 2) left = winW - tipW - 2

  const arrowX = badgeCenterX - left
  arrowLeft.value = `${Math.max(10, Math.min(tipW - 10, arrowX))}px`

  tooltipPos.value = { top: `${top}px`, left: `${left}px` }
  tooltipMaxH.value = `${maxH}px`
}

function onBadgeEnter() {
  cancelHide()
  hovered.value = true
  nextTick(calcPosition)
}

function onBadgeLeave() {
  scheduleHide()
}

function onTooltipEnter() {
  cancelHide()
}

function onTooltipLeave() {
  scheduleHide()
}

onUnmounted(() => cancelHide())

const imgErrors = ref(new Set<number>())
function onImgError(idx: number) {
  imgErrors.value.add(idx)
}
</script>

<template>
  <div ref="badgeEl" class="overflow-badge" @mouseenter="onBadgeEnter" @mouseleave="onBadgeLeave">
    <span class="badge-label">{{ label }}</span>
    <Teleport to="body">
      <Transition name="ob-fade">
        <div
          v-if="hovered"
          class="overflow-tooltip"
          :style="{ ...tooltipPos, maxHeight: tooltipMaxH }"
          @mouseenter="onTooltipEnter"
          @mouseleave="onTooltipLeave"
        >
          <div v-for="(row, idx) in peerRows" :key="idx" class="ob-row">
            <img
              v-if="row.avatarUrl && !imgErrors.has(idx)"
              :src="row.avatarUrl"
              class="ob-avatar"
              @error="onImgError(idx)"
            />
            <span v-else class="ob-avatar-fallback">{{ row.initial }}</span>
            <span class="ob-name">{{ row.name }}</span>
            <MoodIcon v-if="row.moodState !== 'normal'" :mood="row.moodState" class="ob-mood" />
            <span class="ob-steps">{{ row.stepsLabel }}</span>
          </div>
          <span class="ob-arrow" :style="{ left: arrowLeft }"></span>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.overflow-badge {
  position: relative;
  display: flex;
  align-items: center;
  cursor: default;
  flex-shrink: 0;
}

.badge-label {
  font-size: 9px;
  font-weight: 600;
  color: #c4b5fd;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.18), rgba(139, 92, 246, 0.12));
  border: 1px solid rgba(139, 92, 246, 0.18);
  border-radius: 10px;
  padding: 2px 7px;
  white-space: nowrap;
  user-select: none;
  letter-spacing: 0.3px;
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  transition:
    background 0.2s ease,
    border-color 0.2s ease;
}

.overflow-badge:hover .badge-label {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.3), rgba(139, 92, 246, 0.2));
  border-color: rgba(139, 92, 246, 0.3);
}
</style>

<style>
.overflow-tooltip {
  position: fixed;
  background: rgba(15, 23, 42, 0.92);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 8px;
  padding: 6px 4px;
  min-width: 150px;
  overflow-y: auto;
  z-index: 200;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
}

.overflow-tooltip::-webkit-scrollbar {
  width: 3px;
}
.overflow-tooltip::-webkit-scrollbar-track {
  background: transparent;
}
.overflow-tooltip::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.25);
  border-radius: 2px;
}

.ob-arrow {
  position: absolute;
  bottom: -4px;
  transform: translateX(-50%) rotate(45deg);
  width: 7px;
  height: 7px;
  background: rgba(15, 23, 42, 0.92);
  border-right: 1px solid rgba(148, 163, 184, 0.15);
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
}

.ob-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.15s ease;
}
.ob-row:hover {
  background: rgba(255, 255, 255, 0.04);
}

.ob-avatar {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  object-fit: contain;
  image-rendering: pixelated;
  flex-shrink: 0;
}

.ob-avatar-fallback {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: rgba(99, 102, 241, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 8px;
  font-weight: 700;
  color: #e0e7ff;
  flex-shrink: 0;
}

.ob-name {
  font-size: 10px;
  color: #e2e8f0;
  font-weight: 500;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ob-mood {
  font-size: 11px;
  flex-shrink: 0;
}

.ob-steps {
  font-size: 9px;
  color: #a78bfa;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}

.ob-fade-enter-active,
.ob-fade-leave-active {
  transition: opacity 0.15s ease;
}
.ob-fade-enter-from,
.ob-fade-leave-to {
  opacity: 0;
}
</style>
