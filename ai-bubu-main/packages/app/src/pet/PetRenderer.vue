<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { useSkinStore } from '@/stores/skin'
import { usePetStore } from '@/stores/pet'
import SpriteRenderer from './renderers/SpriteRenderer.vue'
import LottieRenderer from './renderers/LottieRenderer.vue'
import ImageRenderer from './renderers/ImageRenderer.vue'

const skinStore = useSkinStore()
const petStore = usePetStore()

const currentAnimation = computed(() => skinStore.getAnimationForState(petStore.movementState))

const isIdle = computed(() => petStore.movementState === 'idle')

const animState = computed(() => petStore.resolvedAnimationState)

const rendererStyle = computed(() => ({
  width: `${skinStore.currentManifest.size.width}px`,
  height: `${skinStore.currentManifest.size.height}px`,
}))

const suppressInteract = ref(false)

watch(
  () => petStore.interactionTick,
  async () => {
    suppressInteract.value = true
    await nextTick()
    suppressInteract.value = false
  },
)

const rendererClasses = computed(() => ({
  breathing: isIdle.value && animState.value === 'idle',
  'mood-sleepy': animState.value === 'sleepy',
  'mood-excited': animState.value === 'excited',
  'mood-happy': animState.value === 'happy',
  'interact-pat': !suppressInteract.value && animState.value === 'pat',
  'interact-poke': !suppressInteract.value && animState.value === 'poke',
  'interact-celebrate': !suppressInteract.value && animState.value === 'celebrate',
  'interact-wave': !suppressInteract.value && animState.value === 'wave',
}))
</script>

<template>
  <div class="pet-canvas">
    <div class="pet-renderer" :class="rendererClasses" :style="rendererStyle">
      <template v-if="currentAnimation">
        <SpriteRenderer
          v-if="skinStore.currentManifest.format === 'sprite'"
          :src="currentAnimation.src"
          :frame-width="currentAnimation.config.sprite?.frameWidth ?? 128"
          :frame-height="currentAnimation.config.sprite?.frameHeight ?? 128"
          :frame-count="currentAnimation.config.sprite?.frameCount ?? 1"
          :columns="currentAnimation.config.sprite?.columns ?? 1"
          :fps="currentAnimation.config.sprite?.fps ?? 8"
          :start-frame="currentAnimation.config.sprite?.startFrame ?? 0"
          :loop="currentAnimation.config.loop"
        />

        <LottieRenderer
          v-else-if="skinStore.currentManifest.format === 'lottie'"
          :src="currentAnimation.src"
          :loop="currentAnimation.config.loop"
        />

        <ImageRenderer v-else :src="currentAnimation.src" />
      </template>
    </div>
  </div>
</template>

<style scoped>
.pet-canvas {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  padding: 2px;
}

.pet-renderer {
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1),
    filter 0.6s ease;
}

/* === Idle breathing === */
.pet-renderer.breathing {
  animation: breathe 2.5s ease-in-out infinite;
  will-change: transform;
}

@keyframes breathe {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.03);
  }
}

/* === Interaction: Pat === */
.pet-renderer.interact-pat {
  animation: pat-squish 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
  will-change: transform;
}

@keyframes pat-squish {
  0% {
    transform: scale(1, 1);
  }
  30% {
    transform: scale(1.06, 0.9);
  }
  60% {
    transform: scale(0.96, 1.06);
  }
  100% {
    transform: scale(1, 1);
  }
}

/* === Interaction: Poke === */
.pet-renderer.interact-poke {
  animation: poke-jump 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
  will-change: transform;
}

@keyframes poke-jump {
  0% {
    transform: translateY(0) rotate(0deg);
  }
  25% {
    transform: translateY(-10px) rotate(5deg) scale(1.1);
  }
  50% {
    transform: translateY(-6px) rotate(-3deg) scale(1.05);
  }
  75% {
    transform: translateY(-2px) rotate(1deg);
  }
  100% {
    transform: translateY(0) rotate(0deg) scale(1);
  }
}

/* === Interaction: Celebrate === */
.pet-renderer.interact-celebrate {
  animation: celebrate-jump 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) 3;
  filter: brightness(1.1) drop-shadow(0 0 4px rgba(250, 204, 21, 0.4));
  will-change: transform, filter;
}

@keyframes celebrate-jump {
  0%,
  100% {
    transform: translateY(0) scale(1) rotate(0deg);
  }
  30% {
    transform: translateY(-8px) scale(1.08) rotate(-3deg);
  }
  60% {
    transform: translateY(-6px) scale(1.04) rotate(3deg);
  }
}

/* === Interaction: Wave === */
.pet-renderer.interact-wave {
  animation: wave-sway 0.4s ease-in-out 3;
  will-change: transform;
}

@keyframes wave-sway {
  0%,
  100% {
    transform: translateX(0) rotate(0deg);
  }
  25% {
    transform: translateX(-3px) rotate(-4deg);
  }
  75% {
    transform: translateX(3px) rotate(4deg);
  }
}
</style>
