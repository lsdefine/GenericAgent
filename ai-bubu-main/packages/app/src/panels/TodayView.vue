<script setup lang="ts">
import { ref, computed } from 'vue'
import { usePetStore } from '@/stores/pet'
import { useActivityStore } from '@/stores/activity'
import { getScoreColor, getLocalDateString } from '@/utils/activity'
import { useI18n } from '@/composables/useI18n'
import { MOVEMENT_STATE_KEYS } from '@/utils/movement'
import type { MessageKey } from '@/composables/useI18n'
import StepChart from './StepChart.vue'
import HeatmapChart from './HeatmapChart.vue'
import ProviderPieChart from './ProviderPieChart.vue'

const petStore = usePetStore()
const activityStore = useActivityStore()
const { t } = useI18n()

const scoreColor = computed(() => getScoreColor(petStore.activityScore))
const stateText = computed(() => t(MOVEMENT_STATE_KEYS[petStore.movementState]))

const showHistory = ref(false)
const expandedDate = ref<string | null>(null)

function toggleDetail(date: string) {
  expandedDate.value = expandedDate.value === date ? null : date
}

function hasDetail(record: {
  hourlySteps?: number[]
  providerMinutes?: Record<string, number>
}): boolean {
  const hasHourly = !!record.hourlySteps && record.hourlySteps.some((v) => v > 0)
  const hasProviders =
    !!record.providerMinutes && Object.values(record.providerMinutes).some((v) => v > 0)
  return hasHourly || hasProviders
}

function miniBarHeight(steps: number, max: number): string {
  return `${Math.max((steps / Math.max(max, 1)) * 100, 4)}%`
}

const PROVIDER_COLORS = [
  '#6366f1',
  '#f59e0b',
  '#4ade80',
  '#ef4444',
  '#8b5cf6',
  '#06b6d4',
  '#ec4899',
  '#84cc16',
]

function formatProviderName(id: string): string {
  return id.replace(/-process$/, '').replace(/-/g, ' ')
}

function mergeProviders(pm: Record<string, number>): [string, number][] {
  const merged = new Map<string, number>()
  for (const [id, mins] of Object.entries(pm)) {
    if (mins <= 0) continue
    const baseId = id.replace(/-process$/, '')
    merged.set(baseId, (merged.get(baseId) || 0) + mins)
  }
  return [...merged.entries()].sort((a, b) => b[1] - a[1])
}

const expandedRecord = computed(() => {
  if (!expandedDate.value) return null
  return sortedHistory.value.find((r) => r.date === expandedDate.value) ?? null
})

const expandedHourlyMax = computed(() => {
  const r = expandedRecord.value
  if (!r?.hourlySteps) return 1
  return Math.max(...r.hourlySteps, 1)
})

const expandedMergedProviders = computed(() => {
  const r = expandedRecord.value
  if (!r?.providerMinutes) return []
  return mergeProviders(r.providerMinutes)
})

const sortedHistory = computed(() =>
  [...activityStore.history].sort((a, b) => b.date.localeCompare(a.date)),
)

const maxHistorySteps = computed(() => {
  if (sortedHistory.value.length === 0) return 1
  return Math.max(...sortedHistory.value.map((r) => r.steps), 1)
})

const streak = computed(() => {
  const dates = new Set(activityStore.history.map((r) => r.date))
  if (petStore.dailySteps > 0) {
    dates.add(getLocalDateString())
  }
  let count = 0
  const d = new Date()
  while (true) {
    const key = getLocalDateString(d)
    if (dates.has(key)) {
      count++
      d.setDate(d.getDate() - 1)
    } else {
      break
    }
  }
  return count
})

function formatDateLabel(dateStr: string): string {
  const [, m, d] = dateStr.split('-')
  return `${parseInt(m)}/${parseInt(d)}`
}

const weekKeys: MessageKey[] = [
  'weekSun',
  'weekMon',
  'weekTue',
  'weekWed',
  'weekThu',
  'weekFri',
  'weekSat',
]

function weekday(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return t(weekKeys[d.getDay()])
}
</script>

<template>
  <div class="today-view">
    <header class="view-header">
      <h2 class="view-title">{{ t('todayOverview') }}</h2>
    </header>
    <div class="hero-card">
      <div class="hero-steps">{{ petStore.formattedSteps }}</div>
      <div class="hero-label">{{ t('todaySteps') }}</div>
      <div class="hero-state">
        <span class="state-dot" :style="{ background: scoreColor }"></span>
        <span class="state-text">{{ stateText }}</span>
      </div>
    </div>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value" :style="{ color: scoreColor }">{{ petStore.activityScore }}%</div>
        <div class="stat-label">{{ t('currentActivity') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ activityStore.peakScore.toFixed(0) }}%</div>
        <div class="stat-label">{{ t('todayPeak') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ activityStore.activeMinutes }}m</div>
        <div class="stat-label">{{ t('activeDuration') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-value accent">{{ streak }}</div>
        <div class="stat-label">{{ t('statsStreak') }} ({{ t('statsStreakDays') }})</div>
      </div>
    </div>

    <!-- 数据洞察 -->
    <div class="insights-section">
      <h3 class="section-heading">{{ t('statsTitle') }}</h3>

      <div class="insight-card">
        <div class="insight-label">{{ t('statsWeekTrend') }}</div>
        <StepChart :history="activityStore.history" :days="7" />
      </div>

      <div class="insight-card">
        <div class="insight-label">{{ t('statsHeatmap') }}</div>
        <div class="insight-hint">{{ t('statsHeatmapHint') }}</div>
        <HeatmapChart :hourly-steps="activityStore.hourlySteps" />
      </div>

      <div class="insight-card">
        <div class="insight-label">{{ t('statsProviders') }}</div>
        <div class="insight-hint">{{ t('statsProvidersHint') }}</div>
        <ProviderPieChart :provider-minutes="activityStore.providerMinutes" />
      </div>
    </div>

    <!-- 历史记录 -->
    <div class="history-section">
      <button class="history-toggle" @click="showHistory = !showHistory">
        <svg class="history-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.3" />
          <path
            d="M8 4.5V8.5L10.5 10"
            stroke="currentColor"
            stroke-width="1.3"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <span>{{ t('history') }}</span>
        <span v-if="sortedHistory.length" class="history-count">
          {{ sortedHistory.length }}{{ t('historyDays') }}
        </span>
        <svg
          class="chevron"
          :class="{ open: showHistory }"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M3 4.5L6 7.5L9 4.5"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>

      <Transition name="history">
        <div v-if="showHistory" class="history-panel">
          <div v-if="sortedHistory.length === 0" class="history-empty">
            {{ t('historyEmpty') }}
          </div>
          <div v-else class="history-list">
            <div v-for="record in sortedHistory" :key="record.date" class="history-item">
              <div
                class="history-row"
                :class="{ expandable: hasDetail(record), expanded: expandedDate === record.date }"
                @click="hasDetail(record) && toggleDetail(record.date)"
              >
                <div class="history-date">
                  <span class="date-label">{{ formatDateLabel(record.date) }}</span>
                  <span class="date-weekday">{{ weekday(record.date) }}</span>
                </div>
                <div class="history-bar-wrap">
                  <div
                    class="history-bar"
                    :style="{ width: (record.steps / maxHistorySteps) * 100 + '%' }"
                  ></div>
                </div>
                <div class="history-stats">
                  <span class="history-steps">{{ record.steps.toLocaleString() }}</span>
                  <span class="history-meta">{{ record.activeMinutes }}m</span>
                </div>
                <svg
                  v-if="hasDetail(record)"
                  class="detail-chevron"
                  :class="{ open: expandedDate === record.date }"
                  viewBox="0 0 12 12"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M3 4.5L6 7.5L9 4.5"
                    stroke="currentColor"
                    stroke-width="1.4"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </div>
              <Transition name="detail">
                <div
                  v-if="expandedDate === record.date && hasDetail(record)"
                  class="history-detail"
                >
                  <div v-if="expandedRecord?.hourlySteps?.some((v) => v > 0)" class="detail-block">
                    <span class="detail-heading">{{ t('historyDetailHourly') }}</span>
                    <div class="mini-bars">
                      <div
                        v-for="(val, h) in expandedRecord!.hourlySteps"
                        :key="h"
                        class="mini-bar-col"
                        :title="`${h}:00 — ${val.toLocaleString()}`"
                      >
                        <div
                          class="mini-bar-fill"
                          :class="{ empty: val === 0 }"
                          :style="{ height: miniBarHeight(val, expandedHourlyMax) }"
                        ></div>
                      </div>
                    </div>
                  </div>
                  <div v-if="expandedMergedProviders.length > 0" class="detail-block">
                    <span class="detail-heading">{{ t('historyDetailProviders') }}</span>
                    <div class="detail-providers">
                      <div
                        v-for="([pid, mins], pi) in expandedMergedProviders"
                        :key="pid"
                        class="detail-provider-row"
                      >
                        <span
                          class="dp-dot"
                          :style="{ background: PROVIDER_COLORS[pi % PROVIDER_COLORS.length] }"
                        ></span>
                        <span class="dp-name">{{ formatProviderName(pid) }}</span>
                        <span class="dp-val">{{ mins }}m</span>
                      </div>
                    </div>
                  </div>
                </div>
              </Transition>
            </div>
          </div>
        </div>
      </Transition>
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
.today-view {
  padding-bottom: 24px;
}
.hero-card {
  margin: 0 24px 20px;
  background: var(--hero-gradient);
  border: 1px solid var(--hero-border);
  border-radius: 16px;
  padding: 28px 24px 20px;
  text-align: center;
}
.hero-steps {
  font-size: 52px;
  font-weight: 800;
  color: var(--text-brightest);
  font-variant-numeric: tabular-nums;
  letter-spacing: -3px;
  line-height: 1;
}
.hero-label {
  font-size: 13px;
  color: var(--text-dim);
  margin-top: 4px;
}
.hero-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 12px;
}
.state-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  transition: background 0.3s;
}
.state-text {
  font-size: 12px;
  color: var(--text-secondary);
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  padding: 0 24px;
  margin-bottom: 24px;
}
.stat-card {
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 14px 12px;
  text-align: center;
}
.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.stat-label {
  font-size: 10px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

.stat-value.accent {
  color: var(--accent-bright);
}

/* === Insights Section === */
.insights-section {
  padding: 0 24px;
  margin-bottom: 24px;
}
.section-heading {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-dim);
  margin: 0 0 12px;
}
.insight-card {
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 10px;
}
.insight-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}
.insight-hint {
  font-size: 10px;
  color: var(--text-tertiary);
  margin: -4px 0 8px;
}

/* === History Section === */
.history-section {
  padding: 0 24px;
}

.history-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 10px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.history-toggle:hover {
  background: var(--bg-surface-hover);
  color: var(--text);
}

.history-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.history-count {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-surface-hover);
  padding: 1px 6px;
  border-radius: 4px;
}

.chevron {
  width: 12px;
  height: 12px;
  margin-left: auto;
  transition: transform 0.2s;
  flex-shrink: 0;
}

.chevron.open {
  transform: rotate(180deg);
}

.history-panel {
  margin-top: 8px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px;
  max-height: 320px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--scrollbar) transparent;
}

.history-panel::-webkit-scrollbar {
  width: 4px;
}
.history-panel::-webkit-scrollbar-track {
  background: transparent;
}
.history-panel::-webkit-scrollbar-thumb {
  background: var(--scrollbar);
  border-radius: 2px;
}

.history-empty {
  text-align: center;
  padding: 20px 12px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.history-item {
  border-radius: 6px;
  overflow: hidden;
}

.history-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 6px;
  transition: background 0.1s;
}

.history-row:hover {
  background: var(--bg-surface-hover);
}

.history-row.expandable {
  cursor: pointer;
}

.history-row.expanded {
  background: var(--bg-surface-hover);
}

.detail-chevron {
  width: 12px;
  height: 12px;
  color: var(--text-muted);
  flex-shrink: 0;
  transition: transform 0.2s;
}
.detail-chevron.open {
  transform: rotate(180deg);
}

.history-detail {
  padding: 4px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-block {
  background: var(--bg-deeper, var(--bg-surface));
  border-radius: 6px;
  padding: 8px 10px;
}

.detail-heading {
  display: block;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.mini-bars {
  display: flex;
  gap: 1px;
  height: 32px;
  align-items: flex-end;
}
.mini-bar-col {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.mini-bar-fill {
  width: 100%;
  background: var(--accent);
  border-radius: 1.5px 1.5px 0 0;
  opacity: 0.7;
  min-height: 1px;
  transition: height 0.2s;
}
.mini-bar-fill.empty {
  background: var(--border);
  opacity: 0.4;
  min-height: 1px;
  height: 1px !important;
}

.detail-providers {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.detail-provider-row {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
}
.dp-dot {
  width: 6px;
  height: 6px;
  border-radius: 2px;
  flex-shrink: 0;
}
.dp-name {
  color: var(--text-secondary);
  text-transform: capitalize;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dp-val {
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

/* === Detail Transition === */
.detail-enter-active {
  transition: all 0.2s ease-out;
}
.detail-leave-active {
  transition: all 0.15s ease-in;
}
.detail-enter-from,
.detail-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
  overflow: hidden;
}
.detail-enter-to,
.detail-leave-from {
  max-height: 200px;
}

.history-date {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  width: 40px;
  flex-shrink: 0;
}

.date-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.date-weekday {
  font-size: 9px;
  color: var(--text-tertiary);
}

.history-bar-wrap {
  flex: 1;
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
  min-width: 40px;
}

.history-bar {
  height: 100%;
  border-radius: 3px;
  background: var(--accent);
  min-width: 2px;
  transition: width 0.3s ease-out;
}

.history-stats {
  display: flex;
  align-items: baseline;
  gap: 4px;
  width: 80px;
  flex-shrink: 0;
  justify-content: flex-end;
}

.history-steps {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-bright);
  font-variant-numeric: tabular-nums;
}

.history-meta {
  font-size: 9px;
  color: var(--text-tertiary);
}

/* === History Transition === */
.history-enter-active {
  transition: all 0.2s ease-out;
}
.history-leave-active {
  transition: all 0.15s ease-in;
}
.history-enter-from,
.history-leave-to {
  opacity: 0;
  max-height: 0;
  margin-top: 0;
  padding: 0 8px;
  overflow: hidden;
}
.history-enter-to,
.history-leave-from {
  max-height: 320px;
}
</style>
