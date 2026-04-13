import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { MovementState, MoodState, InteractionAnimation, PetAnimationState } from '@/types'

const INTERACTION_DURATIONS: Record<InteractionAnimation, number> = {
  pat: 1500,
  poke: 1000,
  celebrate: 2000,
  wave: 1500,
}

export const usePetStore = defineStore('pet', () => {
  const movementState = ref<MovementState>('idle')
  const activityScore = ref(0)
  const dailySteps = ref(0)
  const isDragging = ref(false)

  const moodState = ref<MoodState>('normal')
  const interactionState = ref<InteractionAnimation | null>(null)
  const interactionTick = ref(0)
  let interactionTimer: ReturnType<typeof setTimeout> | null = null

  const formattedSteps = computed(() => dailySteps.value.toLocaleString())

  const resolvedAnimationState = computed<PetAnimationState>(() => {
    if (interactionState.value) return interactionState.value
    if (movementState.value === 'idle' && moodState.value !== 'normal') {
      return moodState.value
    }
    return movementState.value
  })

  function setMovement(state: MovementState, score: number) {
    movementState.value = state
    activityScore.value = score
  }

  function setMood(mood: MoodState) {
    moodState.value = mood
  }

  function playInteraction(action: InteractionAnimation) {
    if (interactionTimer) clearTimeout(interactionTimer)
    interactionState.value = action
    interactionTick.value++
    interactionTimer = setTimeout(() => {
      interactionState.value = null
      interactionTimer = null
    }, INTERACTION_DURATIONS[action])
  }

  function addSteps(count: number) {
    dailySteps.value += count
  }

  function resetDailySteps() {
    dailySteps.value = 0
  }

  return {
    movementState,
    activityScore,
    dailySteps,
    isDragging,
    moodState,
    interactionState,
    interactionTick,
    formattedSteps,
    resolvedAnimationState,
    setMovement,
    setMood,
    playInteraction,
    addSteps,
    resetDailySteps,
  }
})
