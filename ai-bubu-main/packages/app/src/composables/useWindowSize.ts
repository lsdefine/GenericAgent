import { computed, watch, ref, onUnmounted } from 'vue'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { LogicalSize } from '@tauri-apps/api/dpi'
import { useSkinStore } from '@/stores/skin'
import { usePeerEscort } from './usePeerEscort'

const OUTER_PADDING = 16
const TOOLTIP_HEIGHT = 60
const TOOLTIP_MIN_WIDTH = 84
const PEER_GAP = 2
const PEER_BASE_SIZE = 48
const OVERFLOW_BADGE_WIDTH = 38
const DEBOUNCE_MS = 100

function peerSideWidth(peers: { scale: number }[], hasOverflow: boolean): number {
  if (peers.length === 0 && !hasOverflow) return 0
  let w = peers.reduce((sum, ep) => sum + Math.round(PEER_BASE_SIZE * ep.scale), 0)
  if (peers.length > 1) w += (peers.length - 1) * PEER_GAP
  if (hasOverflow) {
    if (peers.length > 0) w += PEER_GAP
    w += OVERFLOW_BADGE_WIDTH
  }
  return w
}

export function useWindowSize() {
  const skinStore = useSkinStore()
  const { visibleBehind, visibleAhead, overflowBehind, overflowAhead } = usePeerEscort()
  const currentWindow = getCurrentWindow()

  const petSize = computed(() => skinStore.currentManifest.size)

  const leftWidth = computed(() => peerSideWidth(visibleBehind.value, !!overflowBehind.value))

  const rightWidth = computed(() => peerSideWidth(visibleAhead.value, !!overflowAhead.value))

  const contentWidth = computed(() => {
    const totalRow = leftWidth.value + petSize.value.width + rightWidth.value
    const tooltipHalf = Math.ceil(TOOLTIP_MIN_WIDTH / 2)
    const petCenter = leftWidth.value + Math.floor(petSize.value.width / 2)
    const leftOverhang = Math.max(0, tooltipHalf - petCenter)
    const rightOverhang = Math.max(0, tooltipHalf - (totalRow - petCenter))
    return totalRow + leftOverhang + rightOverhang
  })

  const windowWidth = computed(() => contentWidth.value + OUTER_PADDING)
  const windowHeight = computed(() => petSize.value.height + TOOLTIP_HEIGHT + OUTER_PADDING)

  const appliedWidth = ref(0)
  const appliedHeight = ref(0)
  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  function applySize(w: number, h: number) {
    if (w === appliedWidth.value && h === appliedHeight.value) return
    appliedWidth.value = w
    appliedHeight.value = h
    currentWindow.setSize(new LogicalSize(w, h)).catch((e) => {
      console.error('useWindowSize: setSize failed', e)
    })
  }

  watch(
    [windowWidth, windowHeight],
    ([w, h]) => {
      if (debounceTimer) clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => applySize(w, h), DEBOUNCE_MS)
    },
    { immediate: true },
  )

  onUnmounted(() => {
    if (debounceTimer) clearTimeout(debounceTimer)
  })

  return { windowWidth, windowHeight }
}
