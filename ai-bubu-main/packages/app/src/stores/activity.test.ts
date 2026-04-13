import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useActivityStore } from './activity'

describe('useActivityStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('updatePeak', () => {
    it('tracks the highest score', () => {
      const store = useActivityStore()
      store.updatePeak(30)
      expect(store.peakScore).toBe(30)
      store.updatePeak(80)
      expect(store.peakScore).toBe(80)
      store.updatePeak(50)
      expect(store.peakScore).toBe(80)
    })

    it('starts at 0', () => {
      const store = useActivityStore()
      expect(store.peakScore).toBe(0)
    })
  })

  describe('trackActiveMinute', () => {
    it('ignores scores below walk threshold', () => {
      const store = useActivityStore()
      store.trackActiveMinute(10, [])
      expect(store.activeMinutes).toBe(0)
    })

    it('increments on first qualifying call', () => {
      const store = useActivityStore()
      store.trackActiveMinute(25, ['cursor'])
      expect(store.activeMinutes).toBe(1)
    })

    it('does not increment again within 60s window', () => {
      const store = useActivityStore()
      store.trackActiveMinute(30, ['cursor'])
      expect(store.activeMinutes).toBe(1)
      store.trackActiveMinute(30, ['cursor'])
      expect(store.activeMinutes).toBe(1)
    })

    it('increments again after 60s window', () => {
      const store = useActivityStore()

      let fakeTime = 1_000_000
      vi.spyOn(Date, 'now').mockImplementation(() => fakeTime)

      store.trackActiveMinute(30, ['cursor'])
      expect(store.activeMinutes).toBe(1)

      fakeTime += 61_000
      store.trackActiveMinute(30, ['cursor'])
      expect(store.activeMinutes).toBe(2)
    })

    it('records provider minutes for active providers', () => {
      const store = useActivityStore()
      store.trackActiveMinute(30, ['cursor', 'claude-code'])
      expect(store.providerMinutes).toEqual({ cursor: 1, 'claude-code': 1 })
    })

    it('deduplicates -process suffix into base provider id', () => {
      const store = useActivityStore()
      store.trackActiveMinute(30, ['cursor', 'cursor-process'])
      expect(store.providerMinutes).toEqual({ cursor: 1 })
      expect(store.activeMinutes).toBe(1)
    })

    it('accumulates provider minutes across windows', () => {
      const store = useActivityStore()

      let fakeTime = 1_000_000
      vi.spyOn(Date, 'now').mockImplementation(() => fakeTime)

      store.trackActiveMinute(30, ['cursor'])
      fakeTime += 61_000
      store.trackActiveMinute(30, ['cursor', 'claude-code'])

      expect(store.providerMinutes).toEqual({ cursor: 2, 'claude-code': 1 })
      expect(store.activeMinutes).toBe(2)
    })
  })

  describe('addHourlySteps', () => {
    it('adds steps to the current hour bucket', () => {
      const store = useActivityStore()
      const hour = new Date().getHours()
      store.addHourlySteps(10)
      store.addHourlySteps(5)
      expect(store.hourlySteps[hour]).toBe(15)
    })

    it('initializes all 24 hours to 0', () => {
      const store = useActivityStore()
      expect(store.hourlySteps).toHaveLength(24)
      expect(store.hourlySteps.every((v) => v === 0)).toBe(true)
    })
  })

  describe('addHistoryRecord', () => {
    it('pushes records', () => {
      const store = useActivityStore()
      store.addHistoryRecord({
        date: '2026-04-01',
        steps: 1000,
        peakScore: 80,
        activeMinutes: 45,
      })
      expect(store.history).toHaveLength(1)
    })

    it('caps at historyMaxDays (90)', () => {
      const store = useActivityStore()
      for (let i = 0; i < 95; i++) {
        const d = new Date(2026, 0, i + 1)
        const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
        store.addHistoryRecord({
          date,
          steps: i * 100,
          peakScore: i,
          activeMinutes: i,
        })
      }
      expect(store.history).toHaveLength(90)
    })
  })

  describe('tryRollover', () => {
    it('returns rolled=false when date is the same', () => {
      const store = useActivityStore()
      const result = store.tryRollover()
      expect(result.rolled).toBe(false)
    })

    it('returns previous hourly and providers when not rolled', () => {
      const store = useActivityStore()
      store.addHourlySteps(10)
      store.trackActiveMinute(30, ['cursor'])

      const result = store.tryRollover()
      expect(result.rolled).toBe(false)
      expect(result.previousHourly).toHaveLength(24)
      expect(result.previousProviders).toEqual({ cursor: 1 })
    })

    it('returns rolled=true and resets when date changes', () => {
      const store = useActivityStore()
      store.updatePeak(90)
      store.trackActiveMinute(50, ['cursor'])
      store.addHourlySteps(42)

      store.todayDate = '2020-01-01'
      const result = store.tryRollover()
      expect(result.rolled).toBe(true)
      expect(result.previousPeak).toBe(90)
      expect(result.previousMinutes).toBe(1)
      expect(result.previousProviders).toEqual({ cursor: 1 })
      expect(store.peakScore).toBe(0)
      expect(store.activeMinutes).toBe(0)
      expect(store.hourlySteps.every((v) => v === 0)).toBe(true)
      expect(Object.keys(store.providerMinutes)).toHaveLength(0)
    })
  })

  describe('restoreToday', () => {
    it('restores hourlySteps from record', () => {
      const store = useActivityStore()
      const hourly = new Array(24).fill(0)
      hourly[9] = 100
      hourly[14] = 200
      store.restoreToday({
        date: '2026-04-04',
        steps: 500,
        peakScore: 60,
        activeMinutes: 10,
        hourlySteps: hourly,
      })
      expect(store.hourlySteps[9]).toBe(100)
      expect(store.hourlySteps[14]).toBe(200)
      expect(store.hourlySteps[0]).toBe(0)
    })

    it('restores providerMinutes from record', () => {
      const store = useActivityStore()
      store.restoreToday({
        date: '2026-04-04',
        steps: 500,
        peakScore: 60,
        activeMinutes: 10,
        providerMinutes: { cursor: 5, 'claude-code': 3 },
      })
      expect(store.providerMinutes).toEqual({ cursor: 5, 'claude-code': 3 })
    })

    it('clears old providerMinutes before restoring', () => {
      const store = useActivityStore()
      store.trackActiveMinute(30, ['old-tool'])
      expect(store.providerMinutes).toHaveProperty('old-tool')

      store.restoreToday({
        date: '2026-04-04',
        steps: 500,
        peakScore: 60,
        activeMinutes: 10,
        providerMinutes: { cursor: 2 },
      })
      expect(store.providerMinutes).toEqual({ cursor: 2 })
      expect(store.providerMinutes).not.toHaveProperty('old-tool')
    })

    it('handles missing optional fields gracefully', () => {
      const store = useActivityStore()
      store.addHourlySteps(10)
      const hourBefore = new Date().getHours()

      store.restoreToday({
        date: '2026-04-04',
        steps: 100,
        peakScore: 20,
        activeMinutes: 5,
      })

      expect(store.hourlySteps[hourBefore]).toBe(10)
    })
  })
})
