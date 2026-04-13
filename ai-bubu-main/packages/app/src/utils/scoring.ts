/**
 * Scoring logic mirrored from Rust backend (src-tauri/src/monitor/scoring.rs
 * and sqlite_adapter.rs). Kept in sync so we can unit-test the algorithm in
 * vitest and reuse it for UI previews / tooltips.
 */

import type { MovementState, ActivityLevel, ProviderStatus } from '@/types'

export type { ActivityLevel }

export type ProbeResult = Pick<
  ProviderStatus,
  'providerId' | 'providerName' | 'activity' | 'lastActiveTs'
>

const ACTIVITY_RANK: Record<ActivityLevel, number> = {
  inactive: 0,
  active_low: 1,
  active_medium: 2,
  active_high: 3,
}

export interface ScoredOutput {
  score: number
  movement: MovementState
}

export function activityFromElapsed(elapsedSeconds: number): ActivityLevel {
  if (elapsedSeconds <= 10) return 'active_high'
  if (elapsedSeconds <= 60) return 'active_medium'
  if (elapsedSeconds <= 300) return 'active_low'
  return 'inactive'
}

export function determineActivity(
  tsMs: number | null,
  status: string | null,
  statusMap: Record<string, ActivityLevel>,
  nowMs: number = Date.now(),
): ActivityLevel {
  if (status && statusMap[status] === 'active_high') {
    return 'active_high'
  }

  if (tsMs == null) return 'inactive'

  const elapsedS = Math.max(0, (nowMs - tsMs) / 1000)
  return activityFromElapsed(elapsedS)
}

export function computeScore(results: ProbeResult[], nowMs: number = Date.now()): ScoredOutput {
  if (results.length === 0) {
    return { score: 0, movement: 'idle' }
  }

  const maxActivity = results.reduce<ActivityLevel>((max, r) => {
    return ACTIVITY_RANK[r.activity] > ACTIVITY_RANK[max] ? r.activity : max
  }, 'inactive')

  const freshestTs = results.reduce<number | null>((best, r) => {
    if (r.lastActiveTs == null) return best
    if (best == null) return r.lastActiveTs
    return r.lastActiveTs > best ? r.lastActiveTs : best
  }, null)

  const freshnessS = freshestTs != null ? Math.max(0, (nowMs - freshestTs) / 1000) : Infinity

  const activeProviderCount = results.filter(
    (r) => ACTIVITY_RANK[r.activity] >= ACTIVITY_RANK['active_low'],
  ).length

  const baseScore: number = {
    active_high: 85,
    active_medium: 60,
    active_low: 35,
    inactive: 5,
  }[maxActivity]

  let freshnessFactor: number
  if (freshnessS <= 10) freshnessFactor = 1.0
  else if (freshnessS <= 30) freshnessFactor = 0.9
  else if (freshnessS <= 60) freshnessFactor = 0.7
  else if (freshnessS <= 300) freshnessFactor = 0.5
  else if (freshnessS <= 600) freshnessFactor = 0.3
  else freshnessFactor = 0.1

  let multiToolBonus: number
  if (activeProviderCount >= 3) multiToolBonus = 15
  else if (activeProviderCount === 2) multiToolBonus = 10
  else multiToolBonus = 0

  const rawScore = Math.min(100, baseScore * freshnessFactor + multiToolBonus)

  let movement: MovementState
  if (rawScore >= 75) movement = 'sprint'
  else if (rawScore >= 50) movement = 'run'
  else if (rawScore >= 20) movement = 'walk'
  else movement = 'idle'

  return { score: rawScore, movement }
}
