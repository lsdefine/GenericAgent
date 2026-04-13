import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ProviderStatus, MonitorUpdate, MovementState } from '@/types'
import { isValidMovementState } from '@/utils/movement'

export const useMonitorStore = defineStore('monitor', () => {
  const providers = ref<ProviderStatus[]>([])
  const score = ref(0)
  const movement = ref<MovementState>('idle')
  const activeProviderCount = ref(0)
  const lastUpdate = ref(0)

  const activeProviders = computed(() => providers.value.filter((p) => p.activity !== 'inactive'))

  function updateFromEvent(data: MonitorUpdate) {
    providers.value = data.providers
    score.value = data.score
    movement.value = isValidMovementState(data.movement) ? data.movement : 'idle'
    activeProviderCount.value = data.activeProviderCount
    lastUpdate.value = data.timestamp
  }

  return {
    providers,
    score,
    movement,
    activeProviderCount,
    lastUpdate,
    activeProviders,
    updateFromEvent,
  }
})
