<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  providerMinutes: Record<string, number>
}>()

const { t } = useI18n()

const COLORS = [
  '#6366f1',
  '#f59e0b',
  '#4ade80',
  '#ef4444',
  '#8b5cf6',
  '#06b6d4',
  '#ec4899',
  '#84cc16',
]

interface Segment {
  id: string
  minutes: number
  percent: number
  color: string
  offset: number
}

const segments = computed<Segment[]>(() => {
  const raw = Object.entries(props.providerMinutes).filter(([, v]) => v > 0)
  if (raw.length === 0) return []

  const merged = new Map<string, number>()
  for (const [id, mins] of raw) {
    const baseId = id.replace(/-process$/, '')
    merged.set(baseId, (merged.get(baseId) || 0) + mins)
  }
  const entries = [...merged.entries()]

  entries.sort((a, b) => b[1] - a[1])
  const total = entries.reduce((s, [, v]) => s + v, 0)

  let offset = 0
  return entries.map(([id, minutes], i) => {
    const percent = (minutes / total) * 100
    const seg: Segment = {
      id,
      minutes,
      percent,
      color: COLORS[i % COLORS.length],
      offset,
    }
    offset += percent
    return seg
  })
})

const totalMinutes = computed(() => segments.value.reduce((s, seg) => s + seg.minutes, 0))

function strokeDasharray(percent: number): string {
  const circumference = 2 * Math.PI * 40
  const len = (percent / 100) * circumference
  return `${len} ${circumference - len}`
}

function strokeDashoffset(offset: number): string {
  const circumference = 2 * Math.PI * 40
  return `${-(offset / 100) * circumference}`
}

function formatName(id: string): string {
  return id.replace(/-/g, ' ')
}

const hoveredIdx = ref<number | null>(null)
</script>

<template>
  <div class="pie-chart">
    <div v-if="segments.length === 0" class="pie-empty">{{ t('statsNoData') }}</div>
    <template v-else>
      <div class="pie-visual">
        <svg viewBox="0 0 100 100" class="pie-svg">
          <circle
            v-for="(seg, idx) in segments"
            :key="seg.id"
            cx="50"
            cy="50"
            r="40"
            fill="none"
            :stroke="seg.color"
            :stroke-width="hoveredIdx === idx ? 22 : 18"
            :stroke-dasharray="strokeDasharray(seg.percent)"
            :stroke-dashoffset="strokeDashoffset(seg.offset)"
            transform="rotate(-90 50 50)"
            class="pie-arc"
            :class="{ dimmed: hoveredIdx !== null && hoveredIdx !== idx }"
            @mouseenter="hoveredIdx = idx"
            @mouseleave="hoveredIdx = null"
          />
        </svg>
        <div class="pie-center-label">
          <template v-if="hoveredIdx !== null">
            <span class="pie-total">{{ segments[hoveredIdx].minutes }}</span>
            <span class="pie-unit">min</span>
          </template>
          <template v-else>
            <span class="pie-total">{{ totalMinutes }}</span>
            <span class="pie-unit">min</span>
          </template>
        </div>
      </div>
      <div class="pie-legend">
        <div
          v-for="(seg, idx) in segments"
          :key="seg.id"
          class="legend-item"
          :class="{
            highlighted: hoveredIdx === idx,
            dimmed: hoveredIdx !== null && hoveredIdx !== idx,
          }"
          @mouseenter="hoveredIdx = idx"
          @mouseleave="hoveredIdx = null"
        >
          <span class="legend-dot" :style="{ background: seg.color }"></span>
          <span class="legend-name">{{ formatName(seg.id) }}</span>
          <span class="legend-val">{{ seg.minutes }}m ({{ seg.percent.toFixed(0) }}%)</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.pie-chart {
  width: 100%;
}
.pie-empty {
  text-align: center;
  padding: 12px 0;
  font-size: 11px;
  color: var(--text-tertiary);
}
.pie-visual {
  position: relative;
  width: 80px;
  height: 80px;
  margin: 0 auto 8px;
}
.pie-svg {
  width: 100%;
  height: 100%;
}
.pie-arc {
  cursor: default;
  transition:
    stroke-width 0.18s ease,
    opacity 0.18s;
}
.pie-arc.dimmed {
  opacity: 0.35;
}
.pie-center-label {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.pie-total {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-bright);
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.pie-unit {
  font-size: 9px;
  color: var(--text-tertiary);
}
.pie-legend {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  padding: 2px 4px;
  border-radius: 4px;
  cursor: default;
  transition:
    background 0.15s,
    opacity 0.15s;
}
.legend-item:hover,
.legend-item.highlighted {
  background: var(--bg-surface-hover);
}
.legend-item.dimmed {
  opacity: 0.4;
}
.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
}
.legend-name {
  color: var(--text-secondary);
  text-transform: capitalize;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.legend-val {
  font-size: 10px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
</style>
