import { watch, onMounted, onUnmounted } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { usePetStore } from '@/stores/pet'
import { useSettingsStore } from '@/stores/settings'
import { useSocialStore } from '@/stores/social'
import { TIMING } from '@/utils/activity'
import type { PeerInfo } from '@/types'

function generatePeerId(): string {
  return crypto.randomUUID()
}

export function useSocial() {
  const petStore = usePetStore()
  const settings = useSettingsStore()
  const socialStore = useSocialStore()

  let broadcastTimer: ReturnType<typeof setInterval> | null = null
  let peerId: string | null = null
  let unlisten: UnlistenFn | null = null
  let mounted = true

  async function start() {
    if (socialStore.isConnected) return

    if (!peerId) {
      peerId = generatePeerId()
    }

    try {
      await invoke('social_start', { peerId })
      socialStore.isConnected = true
      startBroadcast()
    } catch (err) {
      console.error('Failed to start social:', err)
    }
  }

  async function stop() {
    stopBroadcast()
    try {
      await invoke('social_stop')
    } catch (err) {
      console.error('Failed to stop social:', err)
    }
    socialStore.clearAll()
  }

  function startBroadcast() {
    stopBroadcast()
    broadcastTimer = setInterval(async () => {
      try {
        await invoke('social_broadcast', {
          nickname: settings.nickname,
          dailySteps: petStore.dailySteps,
          activityScore: Math.round(petStore.activityScore),
          movementState: petStore.movementState,
          petSkin: settings.currentSkinId,
        })
      } catch {
        // silent
      }
    }, TIMING.broadcastIntervalMs)
  }

  function stopBroadcast() {
    if (broadcastTimer) {
      clearInterval(broadcastTimer)
      broadcastTimer = null
    }
  }

  watch(
    () => settings.socialEnabled,
    async (enabled) => {
      if (enabled) {
        await start()
      } else {
        await stop()
      }
    },
  )

  onMounted(async () => {
    try {
      const fn = await listen<PeerInfo>('social-peer-update', (event) => {
        socialStore.updatePeer(event.payload)
      })
      if (mounted) {
        unlisten = fn
      } else {
        fn()
      }
    } catch (err) {
      console.error('Failed to listen for peer updates:', err)
    }

    if (settings.socialEnabled) {
      await start()
    }
  })

  onUnmounted(() => {
    mounted = false
    unlisten?.()
    stopBroadcast()
    if (socialStore.isConnected) {
      invoke('social_stop').catch(() => {})
      socialStore.clearAll()
    }
  })

  return { start, stop }
}
