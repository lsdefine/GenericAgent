import { describe, it, expect } from 'vitest'
import {
  activityFromElapsed,
  determineActivity,
  computeScore,
  type ProbeResult,
  type ActivityLevel,
} from './scoring'

// ---------------------------------------------------------------------------
// activityFromElapsed
// ---------------------------------------------------------------------------
describe('activityFromElapsed', () => {
  it.each([
    [0, 'active_high'],
    [5, 'active_high'],
    [10, 'active_high'],
    [11, 'active_medium'],
    [30, 'active_medium'],
    [60, 'active_medium'],
    [61, 'active_low'],
    [200, 'active_low'],
    [300, 'active_low'],
    [301, 'inactive'],
    [9999, 'inactive'],
  ] as [number, ActivityLevel][])('elapsed %ds → %s', (elapsed, expected) => {
    expect(activityFromElapsed(elapsed)).toBe(expected)
  })
})

// ---------------------------------------------------------------------------
// determineActivity  (the bug-fix target)
// ---------------------------------------------------------------------------
describe('determineActivity', () => {
  const statusMap: Record<string, ActivityLevel> = {
    generating: 'active_high',
    streaming: 'active_high',
  }

  const NOW = 1_700_000_000_000

  it('returns active_high when status is "generating" regardless of age', () => {
    const oldTs = NOW - 600_000
    expect(determineActivity(oldTs, 'generating', statusMap, NOW)).toBe('active_high')
  })

  it('returns active_high when status is "streaming" regardless of age', () => {
    const oldTs = NOW - 600_000
    expect(determineActivity(oldTs, 'streaming', statusMap, NOW)).toBe('active_high')
  })

  it('BUG FIX: "aborted" within 10s → active_high (not inactive)', () => {
    const recentTs = NOW - 5_000
    expect(determineActivity(recentTs, 'aborted', statusMap, NOW)).toBe('active_high')
  })

  it('BUG FIX: "completed" within 30s → active_medium (not active_low)', () => {
    const recentTs = NOW - 20_000
    expect(determineActivity(recentTs, 'completed', statusMap, NOW)).toBe('active_medium')
  })

  it('BUG FIX: "aborted" within 60s → active_medium', () => {
    const ts = NOW - 45_000
    expect(determineActivity(ts, 'aborted', statusMap, NOW)).toBe('active_medium')
  })

  it('"aborted" 5 minutes ago → active_low', () => {
    const ts = NOW - 200_000
    expect(determineActivity(ts, 'aborted', statusMap, NOW)).toBe('active_low')
  })

  it('"completed" 10 minutes ago → inactive', () => {
    const ts = NOW - 600_000
    expect(determineActivity(ts, 'completed', statusMap, NOW)).toBe('inactive')
  })

  it('no timestamp → inactive', () => {
    expect(determineActivity(null, 'completed', statusMap, NOW)).toBe('inactive')
  })

  it('no status, fresh timestamp → active_high', () => {
    const recentTs = NOW - 3_000
    expect(determineActivity(recentTs, null, statusMap, NOW)).toBe('active_high')
  })

  it('no status, stale timestamp → inactive', () => {
    const oldTs = NOW - 3_600_000
    expect(determineActivity(oldTs, null, statusMap, NOW)).toBe('inactive')
  })

  it('unknown status falls through to timestamp', () => {
    const ts = NOW - 15_000
    expect(determineActivity(ts, 'some_unknown_status', statusMap, NOW)).toBe('active_medium')
  })
})

// ---------------------------------------------------------------------------
// computeScore
// ---------------------------------------------------------------------------
describe('computeScore', () => {
  const NOW = 1_700_000_000_000

  function probe(
    activity: ActivityLevel,
    lastActiveTs: number | null = null,
    id = 'test',
  ): ProbeResult {
    return {
      providerId: id,
      providerName: id,
      activity,
      lastActiveTs,
    }
  }

  it('empty results → score 0, idle', () => {
    const out = computeScore([], NOW)
    expect(out.score).toBe(0)
    expect(out.movement).toBe('idle')
  })

  // --- Single provider, ActiveHigh ---
  it('single ActiveHigh + fresh (≤10s) → sprint', () => {
    const out = computeScore([probe('active_high', NOW - 5_000)], NOW)
    expect(out.score).toBe(85)
    expect(out.movement).toBe('sprint')
  })

  it('single ActiveHigh + 30s stale → score ~76.5 → sprint', () => {
    const out = computeScore([probe('active_high', NOW - 25_000)], NOW)
    expect(out.score).toBeCloseTo(76.5)
    expect(out.movement).toBe('sprint')
  })

  it('single ActiveHigh + 60s stale → score ~59.5 → run', () => {
    const out = computeScore([probe('active_high', NOW - 45_000)], NOW)
    expect(out.score).toBeCloseTo(59.5)
    expect(out.movement).toBe('run')
  })

  it('single ActiveHigh + 5min stale → score ~42.5 → walk', () => {
    const out = computeScore([probe('active_high', NOW - 200_000)], NOW)
    expect(out.score).toBeCloseTo(42.5)
    expect(out.movement).toBe('walk')
  })

  it('single ActiveHigh + 10min stale → score ~25.5 → walk', () => {
    const out = computeScore([probe('active_high', NOW - 500_000)], NOW)
    expect(out.score).toBeCloseTo(25.5)
    expect(out.movement).toBe('walk')
  })

  it('single ActiveHigh + very stale → score ~8.5 → idle', () => {
    const out = computeScore([probe('active_high', NOW - 3_600_000)], NOW)
    expect(out.score).toBeCloseTo(8.5)
    expect(out.movement).toBe('idle')
  })

  // --- Single provider, ActiveMedium ---
  it('single ActiveMedium + fresh → score 60 → run', () => {
    const out = computeScore([probe('active_medium', NOW - 5_000)], NOW)
    expect(out.score).toBe(60)
    expect(out.movement).toBe('run')
  })

  // --- Single provider, ActiveLow ---
  it('single ActiveLow + fresh → score 35 → walk', () => {
    const out = computeScore([probe('active_low', NOW - 5_000)], NOW)
    expect(out.score).toBe(35)
    expect(out.movement).toBe('walk')
  })

  // --- Single provider, Inactive ---
  it('single Inactive → score ~5 → idle', () => {
    const out = computeScore([probe('inactive', NOW - 3_600_000)], NOW)
    expect(out.score).toBeCloseTo(0.5)
    expect(out.movement).toBe('idle')
  })

  // --- Multi-tool bonus ---
  it('2 active providers → +10 bonus', () => {
    const out = computeScore(
      [probe('active_high', NOW - 5_000, 'cursor'), probe('active_low', NOW - 5_000, 'claude')],
      NOW,
    )
    expect(out.score).toBe(95)
    expect(out.movement).toBe('sprint')
  })

  it('3 active providers → +15 bonus, capped at 100', () => {
    const out = computeScore(
      [
        probe('active_high', NOW - 5_000, 'cursor'),
        probe('active_low', NOW - 5_000, 'claude'),
        probe('active_low', NOW - 5_000, 'codex'),
      ],
      NOW,
    )
    expect(out.score).toBe(100)
    expect(out.movement).toBe('sprint')
  })

  it('1 active + 1 inactive → no bonus', () => {
    const out = computeScore(
      [
        probe('active_high', NOW - 5_000, 'cursor'),
        probe('inactive', NOW - 3_600_000, 'claude-code'),
      ],
      NOW,
    )
    expect(out.score).toBe(85)
    expect(out.movement).toBe('sprint')
  })

  // --- Movement boundaries ---
  it('score exactly 75 → sprint', () => {
    // ActiveHigh (85) * 0.9 freshness (11-30s) = 76.5 → sprint
    const out = computeScore([probe('active_high', NOW - 15_000)], NOW)
    expect(out.movement).toBe('sprint')
  })

  it('score exactly 50 → run', () => {
    // ActiveMedium (60) * 0.9 (11-30s) = 54 → run
    const out = computeScore([probe('active_medium', NOW - 15_000)], NOW)
    expect(out.score).toBe(54)
    expect(out.movement).toBe('run')
  })

  it('score exactly 20 → walk', () => {
    // ActiveLow (35) * 0.7 (31-60s) = 24.5 → walk
    const out = computeScore([probe('active_low', NOW - 45_000)], NOW)
    expect(out.score).toBeCloseTo(24.5)
    expect(out.movement).toBe('walk')
  })

  // --- No timestamp ---
  it('null timestamps → uses Infinity freshness → score = base*0.1', () => {
    const out = computeScore([probe('active_high', null)], NOW)
    expect(out.score).toBeCloseTo(8.5)
    expect(out.movement).toBe('idle')
  })
})
