import { watch, onMounted, onUnmounted } from 'vue'
import { useMonitorStore } from '@/stores/monitor'
import { usePetStore } from '@/stores/pet'
import { useActivityStore } from '@/stores/activity'
import { getLocalDateString, msUntilLocalMidnight } from '@/utils/activity'
import type { MovementState, StepRecord } from '@/types'

function accumulateSteps(
  movement: MovementState,
  score: number,
  petStore: ReturnType<typeof usePetStore>,
  activityStore: ReturnType<typeof useActivityStore>,
) {
  const isMoving = movement === 'walk' || movement === 'run' || movement === 'sprint'
  if (isMoving) {
    const steps = Math.floor(score / 10)
    petStore.addSteps(steps)
    activityStore.addHourlySteps(steps)
  }
}

function handleDateRollover(
  petStore: ReturnType<typeof usePetStore>,
  activityStore: ReturnType<typeof useActivityStore>,
) {
  const { rolled, previousPeak, previousMinutes, previousHourly, previousProviders } =
    activityStore.tryRollover()
  if (!rolled) return

  if (petStore.dailySteps > 0) {
    const d = new Date()
    d.setDate(d.getDate() - 1)
    const record: StepRecord = {
      date: getLocalDateString(d),
      steps: petStore.dailySteps,
      peakScore: previousPeak,
      activeMinutes: previousMinutes,
      hourlySteps: previousHourly,
      providerMinutes: previousProviders,
    }
    activityStore.addHistoryRecord(record)
  }
  petStore.resetDailySteps()
}

export function useActivityScore() {
  const monitorStore = useMonitorStore()
  const petStore = usePetStore()
  const activityStore = useActivityStore()

  let midnightTimer: ReturnType<typeof setTimeout> | null = null

  function update() {
    const movement = monitorStore.movement
    const score = monitorStore.score

    petStore.setMovement(movement, Math.round(score))

    activityStore.updatePeak(score)

    const activeIds = monitorStore.activeProviders.map((p) => p.providerId)
    activityStore.trackActiveMinute(score, activeIds)

    accumulateSteps(movement, score, petStore, activityStore)
    handleDateRollover(petStore, activityStore)
  }

  function scheduleMidnightReset() {
    if (midnightTimer) clearTimeout(midnightTimer)
    const ms = msUntilLocalMidnight() + 1000
    midnightTimer = setTimeout(() => {
      handleDateRollover(petStore, activityStore)
      scheduleMidnightReset()
    }, ms)
  }

  watch(
    () => [monitorStore.score, monitorStore.movement],
    () => update(),
    { immediate: true },
  )

  onMounted(() => {
    scheduleMidnightReset()
  })

  onUnmounted(() => {
    if (midnightTimer) clearTimeout(midnightTimer)
  })

  return {}
}
