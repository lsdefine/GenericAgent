import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSocialStore } from './social'
import type { PeerInfo } from '@/types'

function makePeer(overrides: Partial<PeerInfo> = {}): PeerInfo {
  return {
    peerId: 'peer-1',
    nickname: 'Alice',
    dailySteps: 1000,
    activityScore: 50,
    movementState: 'walk',
    petSkin: 'vita',
    lastSeen: Date.now(),
    isOnline: true,
    ...overrides,
  }
}

describe('useSocialStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initializes with empty state', () => {
    const store = useSocialStore()
    expect(store.peers.size).toBe(0)
    expect(store.isConnected).toBe(false)
    expect(store.onlinePeers).toEqual([])
    expect(store.leaderboard).toEqual([])
  })

  describe('updatePeer', () => {
    it('adds online peer to the map', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer())
      expect(store.peers.size).toBe(1)
      expect(store.peers.get('peer-1')?.nickname).toBe('Alice')
    })

    it('removes offline peer from the map', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer())
      expect(store.peers.size).toBe(1)

      store.updatePeer(makePeer({ isOnline: false }))
      expect(store.peers.size).toBe(0)
    })

    it('updates existing peer data', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer({ dailySteps: 100 }))
      store.updatePeer(makePeer({ dailySteps: 500 }))
      expect(store.peers.get('peer-1')?.dailySteps).toBe(500)
    })

    it('validates invalid movementState to idle', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer({ movementState: 'invalid' as never }))
      expect(store.peers.get('peer-1')?.movementState).toBe('idle')
    })

    it('keeps valid movementState', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer({ movementState: 'sprint' }))
      expect(store.peers.get('peer-1')?.movementState).toBe('sprint')
    })

    it('truncates nickname to 20 chars', () => {
      const store = useSocialStore()
      const longName = 'a'.repeat(30)
      store.updatePeer(makePeer({ nickname: longName }))
      expect(store.peers.get('peer-1')?.nickname).toBe('a'.repeat(20))
    })

    it('handles empty nickname', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer({ nickname: '' }))
      expect(store.peers.get('peer-1')?.nickname).toBe('')
    })

    it('sets lastSeen to current time', () => {
      const store = useSocialStore()
      const before = Date.now()
      store.updatePeer(makePeer())
      const after = Date.now()
      const lastSeen = store.peers.get('peer-1')?.lastSeen ?? 0
      expect(lastSeen).toBeGreaterThanOrEqual(before)
      expect(lastSeen).toBeLessThanOrEqual(after)
    })
  })

  describe('onlinePeers', () => {
    it('returns only online peers', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer({ peerId: 'a', isOnline: true }))
      store.updatePeer(makePeer({ peerId: 'b', isOnline: true }))
      expect(store.onlinePeers).toHaveLength(2)
    })

    it('excludes peers that went offline', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer({ peerId: 'a', isOnline: true }))
      store.updatePeer(makePeer({ peerId: 'b', isOnline: false }))
      expect(store.onlinePeers).toHaveLength(1)
      expect(store.onlinePeers[0].peerId).toBe('a')
    })
  })

  describe('leaderboard', () => {
    it('sorts online peers by dailySteps descending', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer({ peerId: 'a', dailySteps: 100 }))
      store.updatePeer(makePeer({ peerId: 'b', dailySteps: 500 }))
      store.updatePeer(makePeer({ peerId: 'c', dailySteps: 300 }))

      const lb = store.leaderboard
      expect(lb.map((p) => p.peerId)).toEqual(['b', 'c', 'a'])
    })

    it('excludes offline peers', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer({ peerId: 'a', dailySteps: 9999, isOnline: true }))
      store.updatePeer(makePeer({ peerId: 'b', dailySteps: 1, isOnline: false }))
      expect(store.leaderboard).toHaveLength(1)
    })
  })

  describe('clearAll', () => {
    it('clears peers and resets connection', () => {
      const store = useSocialStore()
      store.updatePeer(makePeer())
      store.isConnected = true
      expect(store.peers.size).toBe(1)

      store.clearAll()
      expect(store.peers.size).toBe(0)
      expect(store.isConnected).toBe(false)
    })
  })
})
