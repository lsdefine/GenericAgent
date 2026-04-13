import { ref, onUnmounted } from 'vue'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { WebviewWindow } from '@tauri-apps/api/webviewWindow'
import { usePetStore } from '@/stores/pet'

export function usePetInteraction() {
  const petStore = usePetStore()
  const currentWindow = getCurrentWindow()

  const showTooltip = ref(false)
  const isHovering = ref(false)
  const pressing = ref(false)

  let hoverTimer: ReturnType<typeof setTimeout> | null = null
  let dragTimer: ReturnType<typeof setTimeout> | null = null
  let cleanupDragTimer: ReturnType<typeof setTimeout> | null = null
  let isClick = true
  let clickCount = 0
  let clickTimer: ReturnType<typeof setTimeout> | null = null

  function clearHoverTimer() {
    if (hoverTimer) {
      clearTimeout(hoverTimer)
      hoverTimer = null
    }
  }

  function onWindowEnter() {
    isHovering.value = true
  }

  function onWindowLeave() {
    isHovering.value = false
    pressing.value = false
    clearHoverTimer()
    showTooltip.value = false
    if (dragTimer) {
      clearTimeout(dragTimer)
      dragTimer = null
    }
    isClick = false
  }

  function onPetEnter() {
    hoverTimer = setTimeout(() => {
      showTooltip.value = true
    }, 300)
  }

  function onPetLeave() {
    clearHoverTimer()
    showTooltip.value = false
  }

  function onWindowMouseDown(e: MouseEvent) {
    if (e.button !== 0) return
    isClick = true
    pressing.value = true

    dragTimer = setTimeout(async () => {
      isClick = false
      pressing.value = false
      petStore.isDragging = true
      try {
        await currentWindow.startDragging()
      } finally {
        petStore.isDragging = false
      }
    }, 150)
  }

  function onPetClick() {
    showTooltip.value = false
    clearHoverTimer()

    clickCount++
    if (clickTimer) clearTimeout(clickTimer)

    if (clickCount >= 2) {
      clickCount = 0
      petStore.playInteraction('poke')
    } else {
      clickTimer = setTimeout(() => {
        clickCount = 0
        petStore.playInteraction('pat')
      }, 250)
    }
  }

  function onWindowMouseUp(e: MouseEvent) {
    pressing.value = false
    if (dragTimer) {
      clearTimeout(dragTimer)
      dragTimer = null
    }
    if (isClick) {
      const petEl = (e.currentTarget as HTMLElement)?.querySelector('.pet-canvas')
      if (petEl && e.target instanceof HTMLElement && petEl.contains(e.target)) {
        onPetClick()
      }
    }
    cleanupDragTimer = setTimeout(() => {
      petStore.isDragging = false
    }, 50)
  }

  async function onContextMenu(e: MouseEvent) {
    e.preventDefault()
    showTooltip.value = false
    clearHoverTimer()

    try {
      const social = await WebviewWindow.getByLabel('social')
      if (social) {
        const visible = await social.isVisible()
        if (visible) {
          await social.hide()
        } else {
          await social.show()
          await social.setFocus()
        }
      }
    } catch (err) {
      console.error('Failed to toggle social window:', err)
    }
  }

  function cleanup() {
    clearHoverTimer()
    if (dragTimer) clearTimeout(dragTimer)
    if (cleanupDragTimer) clearTimeout(cleanupDragTimer)
    if (clickTimer) clearTimeout(clickTimer)
  }

  onUnmounted(cleanup)

  return {
    showTooltip,
    isHovering,
    pressing,
    onWindowEnter,
    onWindowLeave,
    onPetEnter,
    onPetLeave,
    onWindowMouseDown,
    onWindowMouseUp,
    onContextMenu,
  }
}
