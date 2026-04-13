import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import type { StepRecord } from '@/types'
import { SCORE_THRESHOLDS, TIMING, LIMITS, getLocalDateString } from '@/utils/activity'

function emptyHourlySteps(): number[] {
  return new Array(24).fill(0)
}

export const useActivityStore = defineStore('activity', () => {
  const todayDate = ref(getLocalDateString())
  const peakScore = ref(0)
  const activeMinutes = ref(0)
  const history = ref<StepRecord[]>([])
  const hourlySteps = ref<number[]>(emptyHourlySteps())
  const providerMinutes = reactive<Record<string, number>>({})

  let lastActiveTimestamp = 0

  function trackActiveMinute(score: number, activeProviderIds: string[]) {
    if (score < SCORE_THRESHOLDS.walk) return
    const now = Date.now()
    if (now - lastActiveTimestamp >= TIMING.activeMinuteWindowMs) {
      activeMinutes.value++
      lastActiveTimestamp = now
      const deduped = [...new Set(activeProviderIds.map((id) => id.replace(/-process$/, '')))]
      for (const pid of deduped) {
        providerMinutes[pid] = (providerMinutes[pid] || 0) + 1
      }
    }
  }

  function addHourlySteps(steps: number) {
    const hour = new Date().getHours()
    hourlySteps.value[hour] += steps
  }

  function updatePeak(score: number) {
    if (score > peakScore.value) {
      peakScore.value = score
    }
  }

  function tryRollover(): {
    rolled: boolean
    previousPeak: number
    previousMinutes: number
    previousHourly: number[]
    previousProviders: Record<string, number>
  } {
    const today = getLocalDateString()
    if (today === todayDate.value) {
      return {
        rolled: false,
        previousPeak: peakScore.value,
        previousMinutes: activeMinutes.value,
        previousHourly: [...hourlySteps.value],
        previousProviders: { ...providerMinutes },
      }
    }

    const previousPeak = peakScore.value
    const previousMinutes = activeMinutes.value
    const previousHourly = [...hourlySteps.value]
    const previousProviders = { ...providerMinutes }

    todayDate.value = today
    peakScore.value = 0
    activeMinutes.value = 0
    hourlySteps.value = emptyHourlySteps()
    for (const key of Object.keys(providerMinutes)) {
      delete providerMinutes[key]
    }

    return { rolled: true, previousPeak, previousMinutes, previousHourly, previousProviders }
  }

  function addHistoryRecord(record: StepRecord) {
    history.value.push(record)
    if (history.value.length > LIMITS.historyMaxDays) {
      history.value = history.value.slice(-LIMITS.historyMaxDays)
    }
  }

  function restoreToday(record: StepRecord) {
    if (record.hourlySteps) {
      hourlySteps.value = [...record.hourlySteps]
    }
    if (record.providerMinutes) {
      for (const key of Object.keys(providerMinutes)) {
        delete providerMinutes[key]
      }
      Object.assign(providerMinutes, record.providerMinutes)
    }
  }

  return {
    todayDate,
    peakScore,
    activeMinutes,
    history,
    hourlySteps,
    providerMinutes,
    trackActiveMinute,
    addHourlySteps,
    updatePeak,
    tryRollover,
    addHistoryRecord,
    restoreToday,
  }
})
