import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  getScoreColor,
  MOVEMENT_COLORS,
  SCORE_THRESHOLDS,
  TIMING,
  LIMITS,
  getLocalDateString,
  msUntilLocalMidnight,
} from './activity'

describe('getScoreColor', () => {
  it.each([
    [100, '#ef4444'],
    [85, '#ef4444'],
    [75, '#ef4444'],
    [74, '#f59e0b'],
    [50, '#f59e0b'],
    [20, '#4ade80'],
    [19, '#6366f1'],
    [0, '#6366f1'],
  ])('score %d → %s', (score, expected) => {
    expect(getScoreColor(score)).toBe(expected)
  })
})

describe('MOVEMENT_COLORS', () => {
  it('has all four states', () => {
    expect(MOVEMENT_COLORS).toHaveProperty('sprint')
    expect(MOVEMENT_COLORS).toHaveProperty('run')
    expect(MOVEMENT_COLORS).toHaveProperty('walk')
    expect(MOVEMENT_COLORS).toHaveProperty('idle')
  })

  it('sprint is red', () => {
    expect(MOVEMENT_COLORS.sprint.body).toBe('#ef4444')
  })
})

describe('SCORE_THRESHOLDS', () => {
  it('sprint > run > walk', () => {
    expect(SCORE_THRESHOLDS.sprint).toBeGreaterThan(SCORE_THRESHOLDS.run)
    expect(SCORE_THRESHOLDS.run).toBeGreaterThan(SCORE_THRESHOLDS.walk)
  })

  it('walk is the minimum moving threshold', () => {
    expect(SCORE_THRESHOLDS.walk).toBe(20)
  })
})

describe('TIMING constants', () => {
  it('active minute window is 60 seconds', () => {
    expect(TIMING.activeMinuteWindowMs).toBe(60_000)
  })
})

describe('LIMITS constants', () => {
  it('history max days is 90', () => {
    expect(LIMITS.historyMaxDays).toBe(90)
  })
})

describe('getLocalDateString', () => {
  it('formats date as YYYY-MM-DD', () => {
    const d = new Date(2026, 0, 5)
    expect(getLocalDateString(d)).toBe('2026-01-05')
  })

  it('pads month and day with zeros', () => {
    const d = new Date(2026, 3, 1)
    expect(getLocalDateString(d)).toBe('2026-04-01')
  })

  it('defaults to today when no arg', () => {
    const result = getLocalDateString()
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})

describe('msUntilLocalMidnight', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns positive ms until next midnight', () => {
    const ms = msUntilLocalMidnight()
    expect(ms).toBeGreaterThan(0)
    expect(ms).toBeLessThanOrEqual(24 * 60 * 60 * 1000)
  })

  it('returns ~1ms near midnight', () => {
    vi.useFakeTimers()
    const nearMidnight = new Date()
    nearMidnight.setHours(23, 59, 59, 999)
    vi.setSystemTime(nearMidnight)

    const ms = msUntilLocalMidnight()
    expect(ms).toBeGreaterThan(0)
    expect(ms).toBeLessThanOrEqual(2)
    vi.useRealTimers()
  })

  it('returns ~24h at midnight', () => {
    vi.useFakeTimers()
    const midnight = new Date()
    midnight.setHours(0, 0, 0, 0)
    vi.setSystemTime(midnight)

    const ms = msUntilLocalMidnight()
    expect(ms).toBe(24 * 60 * 60 * 1000)
    vi.useRealTimers()
  })
})
