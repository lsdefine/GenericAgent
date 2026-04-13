<script setup lang="ts">
import { ref, computed } from 'vue'
import type { StepRecord } from '@/types'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  history: StepRecord[]
  days: 7 | 30
}>()

const { t } = useI18n()

const data = computed(() => {
  const sorted = [...props.history].sort((a, b) => a.date.localeCompare(b.date))
  return sorted.slice(-props.days)
})

const maxSteps = computed(() => Math.max(...data.value.map((r) => r.steps), 1))

function barHeight(steps: number): string {
  return `${Math.max((steps / maxSteps.value) * 100, 2)}%`
}

function label(dateStr: string): string {
  const [, m, d] = dateStr.split('-')
  return `${parseInt(m)}/${parseInt(d)}`
}

const hovered = ref<number | null>(null)
const tooltipStyle = ref<Record<string, string>>({})

function onBarEnter(idx: number, ev: MouseEvent) {
  hovered.value = idx
  positionAboveBar(ev.currentTarget as HTMLElement)
}
function onBarLeave() {
  hovered.value = null
}

function positionAboveBar(barEl: HTMLElement) {
  const container = barEl.closest('.step-chart') as HTMLElement | null
  if (!container) return
  const containerRect = container.getBoundingClientRect()
  const barRect = barEl.getBoundingClientRect()
  const x = barRect.left + barRect.width / 2 - containerRect.left
  const y = barRect.top - containerRect.top
  tooltipStyle.value = { left: `${x}px`, top: `${y - 6}px` }
}
</script>

<template>
  <div class="step-chart">
    <div v-if="data.length === 0" class="chart-empty">{{ t('statsNoData') }}</div>
    <div v-else class="chart-bars">
      <div v-for="(record, idx) in data" :key="record.date" class="bar-col">
        <div class="bar-track">
          <div
            class="bar-fill"
            :class="{ active: hovered === idx }"
            :style="{ height: barHeight(record.steps) }"
            @mouseenter="onBarEnter(idx, $event)"
            @mouseleave="onBarLeave"
          ></div>
        </div>
        <span class="bar-label">{{ label(record.date) }}</span>
      </div>
    </div>
    <Transition name="tt">
      <div v-if="hovered !== null" class="chart-tooltip" :style="tooltipStyle">
        <span class="tt-date">{{ label(data[hovered].date) }}</span>
        <span class="tt-val">{{ data[hovered].steps.toLocaleString() }} {{ t('statsSteps') }}</span>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.step-chart {
  width: 100%;
  position: relative;
}
.chart-empty {
  text-align: center;
  padding: 20px 0;
  font-size: 11px;
  color: var(--text-tertiary);
}
.chart-bars {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 80px;
}
.bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
}
.bar-track {
  width: 100%;
  height: 64px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.bar-fill {
  width: 100%;
  max-width: 16px;
  min-height: 2px;
  background: var(--accent);
  border-radius: 3px 3px 0 0;
  transition:
    height 0.3s ease-out,
    opacity 0.15s;
  opacity: 0.65;
  cursor: default;
}
.bar-fill:hover,
.bar-fill.active {
  opacity: 1;
}
.bar-label {
  font-size: 8px;
  color: var(--text-tertiary);
  margin-top: 3px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.chart-tooltip {
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
.tt-date {
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
