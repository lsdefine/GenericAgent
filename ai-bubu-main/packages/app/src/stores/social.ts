import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PeerInfo } from '@/types'
import { isValidMovementState } from '@/utils/movement'

export const useSocialStore = defineStore('social', () => {
  const peers = ref<Map<string, PeerInfo>>(new Map())
  const isConnected = ref(false)

  const onlinePeers = computed(() => Array.from(peers.value.values()).filter((p) => p.isOnline))

  const leaderboard = computed(() =>
    Array.from(peers.value.values())
      .filter((p) => p.isOnline)
      .sort((a, b) => b.dailySteps - a.dailySteps),
  )

  function updatePeer(data: PeerInfo) {
    const validated = { ...data }
    if (!isValidMovementState(validated.movementState)) {
      validated.movementState = 'idle'
    }
    validated.nickname = (validated.nickname || '').slice(0, 20)
    if (validated.isOnline) {
      peers.value.set(validated.peerId, { ...validated, lastSeen: Date.now() })
    } else {
      peers.value.delete(validated.peerId)
    }
  }

  function clearAll() {
    peers.value.clear()
    isConnected.value = false
  }

  return {
    peers,
    isConnected,
    onlinePeers,
    leaderboard,
    updatePeer,
    clearAll,
  }
})
