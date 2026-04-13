import { watch, ref, onUnmounted } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { useSkinStore } from '@/stores/skin'
import { usePetStore } from '@/stores/pet'
import type { SkinAnimationConfig } from '@/types'

const TRAY_SIZE = 44

export function useTrayIcon() {
  const skinStore = useSkinStore()
  const petStore = usePetStore()
  const frameIndex = ref(0)
  let animTimer: ReturnType<typeof setInterval> | null = null
  let cachedImage: HTMLImageElement | null = null
  let cachedSrc = ''
  let loadGeneration = 0
  let lastKey = ''
  const rgbaBuffer: number[] = new Array(TRAY_SIZE * TRAY_SIZE * 4)

  function stopAnim() {
    if (animTimer !== null) {
      clearInterval(animTimer)
      animTimer = null
    }
  }

  let offCtx: CanvasRenderingContext2D | null = null

  function getOffscreenCtx(): CanvasRenderingContext2D {
    if (!offCtx) {
      const offscreen = document.createElement('canvas')
      offscreen.width = TRAY_SIZE
      offscreen.height = TRAY_SIZE
      offCtx = offscreen.getContext('2d')!
      offCtx.imageSmoothingEnabled = false
    }
    return offCtx
  }

  function extractAndSend(img: HTMLImageElement, config: SkinAnimationConfig, frame: number) {
    const sp = config.sprite
    if (!sp) return

    const ctx = getOffscreenCtx()
    const absFrame = (sp.startFrame ?? 0) + frame
    const col = absFrame % sp.columns
    const row = Math.floor(absFrame / sp.columns)

    ctx.clearRect(0, 0, TRAY_SIZE, TRAY_SIZE)
    ctx.drawImage(
      img,
      col * sp.frameWidth,
      row * sp.frameHeight,
      sp.frameWidth,
      sp.frameHeight,
      0,
      0,
      TRAY_SIZE,
      TRAY_SIZE,
    )

    const rgba = ctx.getImageData(0, 0, TRAY_SIZE, TRAY_SIZE).data
    for (let i = 0; i < rgba.length; i++) rgbaBuffer[i] = rgba[i]

    invoke('update_tray_icon', {
      rgba: rgbaBuffer,
      width: TRAY_SIZE,
      height: TRAY_SIZE,
    }).catch(() => {})
  }

  function startAnimLoop(img: HTMLImageElement, config: SkinAnimationConfig) {
    stopAnim()
    const sp = config.sprite
    if (!sp) return

    frameIndex.value = 0
    extractAndSend(img, config, 0)

    const fps = Math.min(sp.fps, 6)
    animTimer = setInterval(() => {
      frameIndex.value = (frameIndex.value + 1) % sp.frameCount
      extractAndSend(img, config, frameIndex.value)
    }, 1000 / fps)
  }

  function update() {
    const resolved = skinStore.getAnimationForState(petStore.movementState)
    if (!resolved) return

    const key = `${skinStore.currentManifest.id}:${petStore.movementState}`
    if (key === lastKey) return
    lastKey = key

    const { config, src } = resolved

    if (cachedSrc === src && cachedImage) {
      startAnimLoop(cachedImage, config)
      return
    }

    const gen = ++loadGeneration
    const img = new Image()
    img.onload = () => {
      if (gen !== loadGeneration) return
      cachedImage = img
      cachedSrc = src
      startAnimLoop(img, config)
    }
    img.onerror = () => {
      if (gen !== loadGeneration) return
      lastKey = ''
    }
    img.src = src
  }

  watch([() => skinStore.currentManifest.id, () => petStore.movementState], () => update(), {
    immediate: true,
  })

  onUnmounted(() => {
    stopAnim()
  })
}
