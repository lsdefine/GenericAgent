import type { MovementState } from '@/types'

export function getScoreColor(score: number): string {
  if (score >= 75) return '#ef4444'
  if (score >= 50) return '#f59e0b'
  if (score >= 20) return '#4ade80'
  return '#6366f1'
}

export const MOVEMENT_COLORS: Record<MovementState, { body: string }> = {
  sprint: { body: '#ef4444' },
  run: { body: '#f59e0b' },
  walk: { body: '#4ade80' },
  idle: { body: '#6366f1' },
}

export const SCORE_THRESHOLDS = {
  sprint: 75,
  run: 50,
  walk: 20,
} as const

export const TIMING = {
  broadcastIntervalMs: 5000,
  stepSaveDebounceMs: 10_000,
  activeMinuteWindowMs: 60_000,
} as const

export const LIMITS = {
  historyMaxDays: 90,
} as const

export const SELF_PEER_ID = '__self__'

export function getLocalDateString(d: Date = new Date()): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function msUntilLocalMidnight(): number {
  const now = new Date()
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 0, 0)
  return midnight.getTime() - now.getTime()
}
