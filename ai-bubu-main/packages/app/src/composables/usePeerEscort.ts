import { computed } from 'vue'
import { useSocialStore } from '@/stores/social'
import { usePetStore } from '@/stores/pet'
import type { PeerInfo } from '@/types'

export interface EscortPeer {
  peer: PeerInfo
  stepDelta: number
  scale: number
}

export interface OverflowGroup {
  count: number
  peers: PeerInfo[]
}

const MAX_VISIBLE = 5
const MIN_SCALE = 0.35
const MAX_SCALE = 0.5

function computeScale(rank: number, total: number): number {
  if (total <= 1) return MAX_SCALE
  const t = rank / (total - 1)
  return MAX_SCALE - t * (MAX_SCALE - MIN_SCALE)
}

export function usePeerEscort() {
  const socialStore = useSocialStore()
  const petStore = usePetStore()

  const mySteps = computed(() => petStore.dailySteps)

  const peersAhead = computed(() =>
    socialStore.onlinePeers
      .filter((p) => p.dailySteps > mySteps.value)
      .sort((a, b) => a.dailySteps - b.dailySteps),
  )

  const peersBehind = computed(() =>
    socialStore.onlinePeers
      .filter((p) => p.dailySteps <= mySteps.value)
      .sort((a, b) => b.dailySteps - a.dailySteps),
  )

  const slotAllocation = computed(() => {
    const ahead = peersAhead.value.length
    const behind = peersBehind.value.length
    const total = ahead + behind
    if (total <= MAX_VISIBLE) return { ahead, behind }
    const aheadSlots = Math.min(ahead, Math.ceil((MAX_VISIBLE * ahead) / total))
    const behindSlots = Math.min(behind, MAX_VISIBLE - aheadSlots)
    return { ahead: aheadSlots, behind: behindSlots }
  })

  const visibleAhead = computed<EscortPeer[]>(() => {
    const slots = slotAllocation.value.ahead
    return peersAhead.value.slice(0, slots).map((peer, i) => ({
      peer,
      stepDelta: peer.dailySteps - mySteps.value,
      scale: computeScale(i, slots),
    }))
  })

  const visibleBehind = computed<EscortPeer[]>(() => {
    const slots = slotAllocation.value.behind
    return peersBehind.value.slice(0, slots).map((peer, i) => ({
      peer,
      stepDelta: mySteps.value - peer.dailySteps,
      scale: computeScale(i, slots),
    }))
  })

  const overflowAhead = computed<OverflowGroup | null>(() => {
    const slots = slotAllocation.value.ahead
    const rest = peersAhead.value.slice(slots)
    if (rest.length === 0) return null
    return { count: rest.length, peers: rest }
  })

  const overflowBehind = computed<OverflowGroup | null>(() => {
    const slots = slotAllocation.value.behind
    const rest = peersBehind.value.slice(slots)
    if (rest.length === 0) return null
    return { count: rest.length, peers: rest }
  })

  const hasPeers = computed(() => socialStore.onlinePeers.length > 0)

  return {
    visibleAhead,
    visibleBehind,
    overflowAhead,
    overflowBehind,
    hasPeers,
  }
}
