<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import lottie from 'lottie-web'
import type { AnimationItem } from 'lottie-web'

const props = defineProps<{
  src: string
  loop: boolean
}>()

const containerRef = ref<HTMLDivElement>()
let animation: AnimationItem | null = null

function load() {
  destroy()
  if (!containerRef.value) return

  animation = lottie.loadAnimation({
    container: containerRef.value,
    renderer: 'svg',
    loop: props.loop,
    autoplay: true,
    path: props.src,
  })
}

function destroy() {
  if (animation) {
    animation.destroy()
    animation = null
  }
}

watch([() => props.src, () => props.loop], () => load())

onMounted(() => load())
onUnmounted(() => destroy())
</script>

<template>
  <div ref="containerRef" class="lottie-renderer"></div>
</template>

<style scoped>
.lottie-renderer {
  width: 100%;
  height: 100%;
}
</style>
