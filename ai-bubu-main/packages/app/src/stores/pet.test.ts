import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePetStore } from './pet'

describe('usePetStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('initializes with idle defaults', () => {
    const store = usePetStore()
    expect(store.movementState).toBe('idle')
    expect(store.activityScore).toBe(0)
    expect(store.dailySteps).toBe(0)
    expect(store.isDragging).toBe(false)
    expect(store.moodState).toBe('normal')
    expect(store.interactionState).toBeNull()
    expect(store.interactionTick).toBe(0)
  })

  it('setMovement updates state and score', () => {
    const store = usePetStore()
    store.setMovement('sprint', 95)
    expect(store.movementState).toBe('sprint')
    expect(store.activityScore).toBe(95)
  })

  it('addSteps accumulates', () => {
    const store = usePetStore()
    store.addSteps(100)
    store.addSteps(50)
    expect(store.dailySteps).toBe(150)
  })

  it('resetDailySteps clears to 0', () => {
    const store = usePetStore()
    store.addSteps(500)
    store.resetDailySteps()
    expect(store.dailySteps).toBe(0)
  })

  it('formattedSteps returns locale string', () => {
    const store = usePetStore()
    store.addSteps(12345)
    expect(store.formattedSteps).toBe('12,345')
  })

  describe('setMood', () => {
    it('updates moodState', () => {
      const store = usePetStore()
      store.setMood('sleepy')
      expect(store.moodState).toBe('sleepy')
    })

    it('can be set back to normal', () => {
      const store = usePetStore()
      store.setMood('excited')
      store.setMood('normal')
      expect(store.moodState).toBe('normal')
    })
  })

  describe('playInteraction', () => {
    it('sets interactionState and increments tick', () => {
      vi.useFakeTimers()
      const store = usePetStore()
      store.playInteraction('pat')
      expect(store.interactionState).toBe('pat')
      expect(store.interactionTick).toBe(1)
      vi.useRealTimers()
    })

    it('clears interactionState after duration', () => {
      vi.useFakeTimers()
      const store = usePetStore()
      store.playInteraction('pat')
      expect(store.interactionState).toBe('pat')

      vi.advanceTimersByTime(1500)
      expect(store.interactionState).toBeNull()
      vi.useRealTimers()
    })

    it('replaces current interaction when called again', () => {
      vi.useFakeTimers()
      const store = usePetStore()
      store.playInteraction('pat')
      expect(store.interactionTick).toBe(1)

      store.playInteraction('poke')
      expect(store.interactionState).toBe('poke')
      expect(store.interactionTick).toBe(2)

      vi.advanceTimersByTime(1000)
      expect(store.interactionState).toBeNull()
      vi.useRealTimers()
    })

    it('uses different durations per action', () => {
      vi.useFakeTimers()
      const store = usePetStore()

      store.playInteraction('poke')
      vi.advanceTimersByTime(999)
      expect(store.interactionState).toBe('poke')
      vi.advanceTimersByTime(1)
      expect(store.interactionState).toBeNull()

      store.playInteraction('celebrate')
      vi.advanceTimersByTime(1999)
      expect(store.interactionState).toBe('celebrate')
      vi.advanceTimersByTime(1)
      expect(store.interactionState).toBeNull()

      vi.useRealTimers()
    })
  })

  describe('resolvedAnimationState', () => {
    it('returns movementState when no interaction and normal mood', () => {
      const store = usePetStore()
      store.setMovement('run', 60)
      expect(store.resolvedAnimationState).toBe('run')
    })

    it('returns moodState when idle and mood is not normal', () => {
      const store = usePetStore()
      store.setMovement('idle', 0)
      store.setMood('sleepy')
      expect(store.resolvedAnimationState).toBe('sleepy')
    })

    it('returns movementState when not idle even if mood is set', () => {
      const store = usePetStore()
      store.setMovement('walk', 30)
      store.setMood('sleepy')
      expect(store.resolvedAnimationState).toBe('walk')
    })

    it('returns interactionState over everything else', () => {
      vi.useFakeTimers()
      const store = usePetStore()
      store.setMovement('sprint', 90)
      store.setMood('excited')
      store.playInteraction('pat')
      expect(store.resolvedAnimationState).toBe('pat')
      vi.useRealTimers()
    })
  })
})
