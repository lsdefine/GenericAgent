import { watch, onMounted, onUnmounted } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { usePetStore } from '@/stores/pet'
import { useActivityStore } from '@/stores/activity'
import { TIMING } from '@/utils/activity'
import type { StepRecord } from '@/types'

export function useStepCounter() {
  const petStore = usePetStore()
  const activityStore = useActivityStore()

  let saveTimer: ReturnType<typeof setTimeout> | null = null

  async function saveSteps() {
    try {
      await invoke('save_steps', {
        date: activityStore.todayDate,
        steps: petStore.dailySteps,
        peakScore: activityStore.peakScore,
        activeMinutes: activityStore.activeMinutes,
        hourlySteps: [...activityStore.hourlySteps],
        providerMinutes: { ...activityStore.providerMinutes },
      })
    } catch (err) {
      console.error('Failed to save steps:', err)
    }
  }

  async function loadTodaySteps() {
    try {
      const record = await invoke<StepRecord | null>('load_steps', {
        date: activityStore.todayDate,
      })
      if (record) {
        petStore.dailySteps = record.steps
        activityStore.peakScore = record.peakScore
        activityStore.activeMinutes = record.activeMinutes
        activityStore.restoreToday(record)
      }
    } catch (err) {
      console.error('Failed to load steps:', err)
    }
  }

  async function loadHistory() {
    try {
      const records = await invoke<StepRecord[]>('load_step_history')
      activityStore.history = records
    } catch (err) {
      console.error('Failed to load history:', err)
    }
  }

  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(saveSteps, TIMING.stepSaveDebounceMs)
  }

  watch(
    [() => petStore.dailySteps, () => activityStore.activeMinutes, () => activityStore.peakScore],
    () => {
      scheduleSave()
    },
  )

  onMounted(async () => {
    await loadTodaySteps()
    await loadHistory()
  })

  onUnmounted(() => {
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
    void saveSteps()
  })

  return { saveSteps, loadTodaySteps }
}
