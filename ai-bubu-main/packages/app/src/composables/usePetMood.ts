import { watch, onMounted, onUnmounted } from 'vue'
import { usePetStore } from '@/stores/pet'

const IS_DEV = import.meta.env.DEV
const SLEEPY_THRESHOLD_MS = IS_DEV ? 30 * 1000 : 10 * 60 * 1000
const EXCITED_SCORE_THRESHOLD = 90
const MOOD_CHECK_INTERVAL_MS = IS_DEV ? 3_000 : 10_000

export function usePetMood() {
  const petStore = usePetStore()

  let idleSince: number | null = null
  let moodTimer: ReturnType<typeof setInterval> | null = null

  watch(
    () => petStore.movementState,
    (state) => {
      if (state === 'idle') {
        idleSince ??= Date.now()
      } else {
        idleSince = null
        if (petStore.moodState === 'sleepy') {
          petStore.setMood('normal')
        }
      }

      if (state === 'sprint' || petStore.activityScore >= EXCITED_SCORE_THRESHOLD) {
        petStore.setMood('excited')
      } else if (state !== 'idle' && petStore.moodState === 'excited') {
        petStore.setMood('normal')
      }
    },
  )

  function checkMood() {
    if (petStore.interactionState) return

    if (petStore.activityScore >= EXCITED_SCORE_THRESHOLD) {
      petStore.setMood('excited')
      return
    }

    if (petStore.movementState === 'idle' && idleSince) {
      const elapsed = Date.now() - idleSince
      if (elapsed >= SLEEPY_THRESHOLD_MS) {
        petStore.setMood('sleepy')
        return
      }
    }

    if (petStore.moodState !== 'happy') {
      petStore.setMood('normal')
    }
  }

  onMounted(() => {
    if (petStore.movementState === 'idle') {
      idleSince = Date.now()
    }
    moodTimer = setInterval(checkMood, MOOD_CHECK_INTERVAL_MS)
  })

  onUnmounted(() => {
    if (moodTimer) {
      clearInterval(moodTimer)
      moodTimer = null
    }
  })

  return {}
}
