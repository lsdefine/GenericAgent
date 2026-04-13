<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    src: string
    frameWidth: number
    frameHeight: number
    frameCount: number
    columns: number
    fps: number
    loop: boolean
    startFrame?: number
  }>(),
  {
    startFrame: 0,
  },
)

const canvasRef = ref<HTMLCanvasElement>()
const image = ref<HTMLImageElement>()
const currentFrame = ref(0)
let rafId: number | null = null
let lastFrameTime = 0
let loadGeneration = 0

function stop() {
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
}

function drawFrame() {
  const canvas = canvasRef.value
  const img = image.value
  if (!canvas || !img) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const absFrame = props.startFrame + currentFrame.value
  const col = absFrame % props.columns
  const row = Math.floor(absFrame / props.columns)

  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(
    img,
    col * props.frameWidth,
    row * props.frameHeight,
    props.frameWidth,
    props.frameHeight,
    0,
    0,
    canvas.width,
    canvas.height,
  )
}

function tick(timestamp: number) {
  const interval = 1000 / props.fps
  if (timestamp - lastFrameTime >= interval) {
    lastFrameTime = timestamp - ((timestamp - lastFrameTime) % interval)

    if (currentFrame.value >= props.frameCount - 1) {
      if (props.loop) {
        currentFrame.value = 0
      } else {
        rafId = null
        return
      }
    } else {
      currentFrame.value++
    }
    drawFrame()
  }
  rafId = requestAnimationFrame(tick)
}

function startAnim() {
  stop()
  currentFrame.value = 0
  lastFrameTime = 0
  drawFrame()
  if (document.visibilityState === 'visible') {
    rafId = requestAnimationFrame(tick)
  }
}

function loadImage(src: string) {
  stop()
  const gen = ++loadGeneration
  const img = new Image()
  img.onload = () => {
    if (gen !== loadGeneration) return
    image.value = img
    startAnim()
  }
  img.onerror = () => {
    if (gen !== loadGeneration) return
    console.error('Failed to load sprite:', src)
  }
  img.src = src
}

watch(
  () => props.src,
  (newSrc) => {
    loadImage(newSrc)
  },
)

watch([() => props.startFrame, () => props.frameCount, () => props.fps], () => {
  if (image.value) startAnim()
})

function onVisibilityChange() {
  if (document.visibilityState === 'visible') {
    if (image.value && rafId === null) startAnim()
  } else {
    stop()
  }
}

onMounted(() => {
  loadImage(props.src)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  stop()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <canvas
    ref="canvasRef"
    :width="frameWidth"
    :height="frameHeight"
    class="sprite-renderer"
  ></canvas>
</template>

<style scoped>
.sprite-renderer {
  width: 100%;
  height: 100%;
  object-fit: contain;
  image-rendering: pixelated;
}
</style>
