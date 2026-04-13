<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  hourlySteps: number[]
}>()

const { t } = useI18n()

const normalized = computed(() => {
  const arr = props.hourlySteps
  if (!arr || arr.length === 0) return new Array(24).fill(0)
  const result = arr.slice(0, 24)
  while (result.length < 24) result.push(0)
  return result
})

const hasData = computed(() => normalized.value.some((v) => v > 0))
const maxVal = computed(() => Math.max(...normalized.value, 1))

function intensity(val: number): number {
  if (val === 0) return 0
  return Math.max(0.15, val / maxVal.value)
}

const hours = Array.from({ length: 24 }, (_, i) => i)
const labelHours = [0, 6, 12, 18, 23]

const hovered = ref<number | null>(null)
const tooltipStyle = ref<Record<string, string>>({})

function onEnter(h: number, ev: MouseEvent) {
  hovered.value = h
  positionTooltip(ev)
}
function onMove(ev: MouseEvent) {
  positionTooltip(ev)
}
function onLeave() {
  hovered.value = null
}

function positionTooltip(ev: MouseEvent) {
  const container = (ev.currentTarget as HTMLElement).closest('.heatmap-chart')
  if (!container) return
  const rect = container.getBoundingClientRect()
  const x = ev.clientX - rect.left
  const y = ev.clientY - rect.top
  tooltipStyle.value = { left: `${x}px`, top: `${y - 8}px` }
}
</script>

<template>
  <div class="heatmap-chart">
    <div v-if="!hasData" class="hm-empty">{{ t('statsNoData') }}</div>
    <template v-else>
      <div class="hm-grid">
        <div
          v-for="h in hours"
          :key="h"
          class="hm-cell"
          :style="{ opacity: intensity(normalized[h]) || undefined }"
          :class="{ empty: normalized[h] === 0, active: hovered === h }"
          @mouseenter="onEnter(h, $event)"
          @mousemove="onMove"
          @mouseleave="onLeave"
        ></div>
      </div>
      <div class="hm-labels">
        <span
          v-for="h in labelHours"
          :key="h"
          class="hm-label"
          :style="{ left: `${(h / 23) * 100}%` }"
        >
          {{ h }}:00
        </span>
      </div>
      <Transition name="tt">
        <div v-if="hovered !== null" class="hm-tooltip" :style="tooltipStyle">
          <span class="tt-time">{{ hovered }}:00–{{ hovered + 1 }}:00</span>
          <span class="tt-val">
            {{ normalized[hovered].toLocaleString() }} {{ t('statsSteps') }}
          </span>
        </div>
      </Transition>
    </template>
  </div>
</template>

<style scoped>
.heatmap-chart {
  width: 100%;
  position: relative;
}
.hm-empty {
  text-align: center;
  padding: 12px 0;
  font-size: 11px;
  color: var(--text-tertiary);
}
.hm-grid {
  display: flex;
  gap: 2px;
  height: 24px;
}
.hm-cell {
  flex: 1;
  border-radius: 3px;
  background: var(--accent);
  transition:
    opacity 0.2s,
    box-shadow 0.15s;
  min-width: 0;
  cursor: default;
}
.hm-cell.empty {
  background: var(--border);
  opacity: 1 !important;
}
.hm-cell.active:not(.empty) {
  box-shadow: 0 0 0 1.5px var(--accent);
}
.hm-labels {
  position: relative;
  height: 14px;
  margin-top: 4px;
}
.hm-label {
  position: absolute;
  transform: translateX(-50%);
  font-size: 8px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.hm-tooltip {
  position: absolute;
  transform: translate(-50%, -100%);
  background: var(--bg-tooltip, rgba(0, 0, 0, 0.82));
  color: #fff;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 11px;
  white-space: nowrap;
  pointer-events: none;
  z-index: 10;
  display: flex;
  gap: 6px;
  align-items: baseline;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
}
.tt-time {
  font-weight: 600;
}
.tt-val {
  font-variant-numeric: tabular-nums;
  opacity: 0.85;
}
.tt-enter-active,
.tt-leave-active {
  transition: opacity 0.12s;
}
.tt-enter-from,
.tt-leave-to {
  opacity: 0;
}
</style>
