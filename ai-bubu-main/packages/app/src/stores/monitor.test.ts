import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useMonitorStore } from './monitor'
import type { MonitorUpdate } from '@/types'

describe('useMonitorStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initializes with idle defaults', () => {
    const store = useMonitorStore()
    expect(store.providers).toEqual([])
    expect(store.score).toBe(0)
    expect(store.movement).toBe('idle')
    expect(store.activeProviderCount).toBe(0)
  })

  it('updates from monitor event', () => {
    const store = useMonitorStore()
    const event: MonitorUpdate = {
      providers: [
        {
          providerId: 'cursor',
          providerName: 'Cursor AI',
          activity: 'active_high',
          lastActiveTs: Date.now(),
          linesAdded: 100,
          filesChanged: 5,
          modelName: 'claude-4',
        },
      ],
      score: 85,
      movement: 'sprint',
      activeProviderCount: 1,
      timestamp: Date.now(),
    }

    store.updateFromEvent(event)
    expect(store.score).toBe(85)
    expect(store.movement).toBe('sprint')
    expect(store.activeProviderCount).toBe(1)
    expect(store.providers).toHaveLength(1)
    expect(store.providers[0].providerId).toBe('cursor')
  })

  it('activeProviders filters out inactive', () => {
    const store = useMonitorStore()
    store.updateFromEvent({
      providers: [
        {
          providerId: 'cursor',
          providerName: 'Cursor AI',
          activity: 'active_high',
          lastActiveTs: Date.now(),
          linesAdded: null,
          filesChanged: null,
          modelName: null,
        },
        {
          providerId: 'claude-code',
          providerName: 'Claude Code',
          activity: 'inactive',
          lastActiveTs: null,
          linesAdded: null,
          filesChanged: null,
          modelName: null,
        },
      ],
      score: 85,
      movement: 'sprint',
      activeProviderCount: 1,
      timestamp: Date.now(),
    })

    expect(store.activeProviders).toHaveLength(1)
    expect(store.activeProviders[0].providerId).toBe('cursor')
  })
})
