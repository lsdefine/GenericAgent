import { onMounted, onUnmounted } from 'vue'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { useMonitorStore } from '@/stores/monitor'
import type { MonitorUpdate } from '@/types'

export function useMonitor() {
  const store = useMonitorStore()
  let unlisten: UnlistenFn | null = null
  let mounted = true

  onMounted(async () => {
    try {
      const fn = await listen<MonitorUpdate>('monitor-update', (event) => {
        store.updateFromEvent(event.payload)
      })
      if (mounted) {
        unlisten = fn
      } else {
        fn()
      }
    } catch (err) {
      console.error('Failed to listen for monitor updates:', err)
    }
  })

  onUnmounted(() => {
    mounted = false
    unlisten?.()
  })

  return { store }
}
