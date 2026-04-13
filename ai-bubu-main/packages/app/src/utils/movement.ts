import type { MovementState } from '@/types'
import type { MessageKey } from '@/composables/useI18n'

export function isValidMovementState(s: string): s is MovementState {
  return s === 'sprint' || s === 'run' || s === 'walk' || s === 'idle'
}

export const MOVEMENT_STATE_KEYS: Record<MovementState, MessageKey> = {
  idle: 'stateIdle',
  walk: 'stateWalk',
  run: 'stateRun',
  sprint: 'stateSprint',
}
