import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePeerEscort } from './usePeerEscort'
import { useSocialStore } from '@/stores/social'
import { usePetStore } from '@/stores/pet'
import type { PeerInfo } from '@/types'

function makePeer(id: string, steps: number): PeerInfo {
  return {
    peerId: id,
    nickname: id,
    dailySteps: steps,
    activityScore: 50,
    movementState: 'walk',
    petSkin: 'vita',
    lastSeen: Date.now(),
    isOnline: true,
  }
}

describe('usePeerEscort', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('hasPeers is false when no peers', () => {
    const { hasPeers } = usePeerEscort()
    expect(hasPeers.value).toBe(false)
  })

  it('hasPeers is true when peers exist', () => {
    const socialStore = useSocialStore()
    socialStore.updatePeer(makePeer('a', 100))
    const { hasPeers } = usePeerEscort()
    expect(hasPeers.value).toBe(true)
  })

  it('splits peers into ahead and behind based on my steps', () => {
    const petStore = usePetStore()
    petStore.dailySteps = 500

    const socialStore = useSocialStore()
    socialStore.updatePeer(makePeer('ahead1', 800))
    socialStore.updatePeer(makePeer('ahead2', 600))
    socialStore.updatePeer(makePeer('behind1', 300))
    socialStore.updatePeer(makePeer('behind2', 100))

    const { visibleAhead, visibleBehind } = usePeerEscort()
    expect(visibleAhead.value.map((ep) => ep.peer.peerId)).toEqual(['ahead2', 'ahead1'])
    expect(visibleBehind.value.map((ep) => ep.peer.peerId)).toEqual(['behind1', 'behind2'])
  })

  it('peers with equal steps go to behind group', () => {
    const petStore = usePetStore()
    petStore.dailySteps = 500

    const socialStore = useSocialStore()
    socialStore.updatePeer(makePeer('equal', 500))

    const { visibleBehind, visibleAhead } = usePeerEscort()
    expect(visibleBehind.value).toHaveLength(1)
    expect(visibleAhead.value).toHaveLength(0)
  })

  it('limits total visible to MAX_VISIBLE (5)', () => {
    const petStore = usePetStore()
    petStore.dailySteps = 500

    const socialStore = useSocialStore()
    for (let i = 0; i < 8; i++) {
      socialStore.updatePeer(makePeer(`peer-${i}`, 100 + i * 100))
    }

    const { visibleAhead, visibleBehind, overflowAhead, overflowBehind } = usePeerEscort()
    const totalVisible = visibleAhead.value.length + visibleBehind.value.length
    expect(totalVisible).toBeLessThanOrEqual(5)

    const totalOverflow = (overflowAhead.value?.count ?? 0) + (overflowBehind.value?.count ?? 0)
    expect(totalVisible + totalOverflow).toBe(8)
  })

  it('overflow contains remaining peers', () => {
    const petStore = usePetStore()
    petStore.dailySteps = 500

    const socialStore = useSocialStore()
    for (let i = 0; i < 10; i++) {
      socialStore.updatePeer(makePeer(`a-${i}`, 600 + i * 10))
    }

    const { overflowAhead } = usePeerEscort()
    expect(overflowAhead.value).not.toBeNull()
    expect(overflowAhead.value!.count).toBeGreaterThan(0)
    expect(overflowAhead.value!.peers.length).toBe(overflowAhead.value!.count)
  })

  it('no overflow when few peers', () => {
    const petStore = usePetStore()
    petStore.dailySteps = 500

    const socialStore = useSocialStore()
    socialStore.updatePeer(makePeer('a', 600))
    socialStore.updatePeer(makePeer('b', 400))

    const { overflowAhead, overflowBehind } = usePeerEscort()
    expect(overflowAhead.value).toBeNull()
    expect(overflowBehind.value).toBeNull()
  })

  it('computes stepDelta correctly', () => {
    const petStore = usePetStore()
    petStore.dailySteps = 500

    const socialStore = useSocialStore()
    socialStore.updatePeer(makePeer('ahead', 800))
    socialStore.updatePeer(makePeer('behind', 200))

    const { visibleAhead, visibleBehind } = usePeerEscort()
    expect(visibleAhead.value[0].stepDelta).toBe(300)
    expect(visibleBehind.value[0].stepDelta).toBe(300)
  })

  it('computes scale values between MIN and MAX', () => {
    const petStore = usePetStore()
    petStore.dailySteps = 500

    const socialStore = useSocialStore()
    socialStore.updatePeer(makePeer('a', 600))
    socialStore.updatePeer(makePeer('b', 700))
    socialStore.updatePeer(makePeer('c', 800))

    const { visibleAhead } = usePeerEscort()
    for (const ep of visibleAhead.value) {
      expect(ep.scale).toBeGreaterThanOrEqual(0.35)
      expect(ep.scale).toBeLessThanOrEqual(0.5)
    }
  })
})
