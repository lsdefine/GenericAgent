<script setup lang="ts">
import { ref, watch } from 'vue'
import { usePetStore } from '@/stores/pet'
import type { InteractionAnimation } from '@/types'

const petStore = usePetStore()

interface Particle {
  id: number
  emoji: string
  left: string
  style: 'float' | 'burst'
}

const MAX_PARTICLES = 15

const particles = ref<Particle[]>([])
let nextId = 0

const INTERACTION_EMOJIS: Record<InteractionAnimation, string[]> = {
  pat: ['❤️', '💕'],
  poke: ['❗', '❓'],
  celebrate: ['🎉', '✨', '🎊', '⭐'],
  wave: ['👋'],
}

function spawnParticles(action: InteractionAnimation) {
  const emojis = INTERACTION_EMOJIS[action]
  const count = action === 'celebrate' ? 5 : action === 'pat' ? 2 : 1

  if (particles.value.length + count > MAX_PARTICLES) {
    particles.value = particles.value.slice(-(MAX_PARTICLES - count))
  }

  for (let i = 0; i < count; i++) {
    const offsetX = (Math.random() - 0.5) * 30
    const p: Particle = {
      id: nextId++,
      emoji: emojis[i % emojis.length],
      left: `calc(50% + ${offsetX}px)`,
      style: action === 'celebrate' ? 'burst' : 'float',
    }
    particles.value.push(p)

    setTimeout(
      () => {
        particles.value = particles.value.filter((pp) => pp.id !== p.id)
      },
      action === 'celebrate' ? 1800 : 1200,
    )
  }
}

watch(
  () => petStore.interactionTick,
  () => {
    const action = petStore.interactionState
    if (action) spawnParticles(action)
  },
)
</script>

<template>
  <div class="pet-effects">
    <span
      v-for="p in particles"
      :key="p.id"
      class="particle"
      :class="p.style"
      :style="{ left: p.left }"
    >
      {{ p.emoji }}
    </span>
  </div>
</template>

<style scoped>
.pet-effects {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: visible;
  z-index: 15;
}

.particle {
  position: absolute;
  top: 0;
  font-size: 16px;
  pointer-events: none;
  filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.2));
  transform: translateX(-50%);
}

.particle.float {
  animation: particle-float 1.2s ease-out forwards;
}

.particle.burst {
  animation: particle-burst 1.8s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards;
}

@keyframes particle-float {
  0% {
    opacity: 1;
    transform: translateX(-50%) translateY(0) scale(0.5);
  }
  30% {
    opacity: 1;
    transform: translateX(-50%) translateY(-16px) scale(1.1);
  }
  100% {
    opacity: 0;
    transform: translateX(-50%) translateY(-32px) scale(0.7);
  }
}

@keyframes particle-burst {
  0% {
    opacity: 1;
    transform: translateX(-50%) translateY(0) scale(0.3);
  }
  20% {
    opacity: 1;
    transform: translateX(-50%) translateY(-12px) scale(1.2);
  }
  60% {
    opacity: 0.8;
    transform: translateX(-50%) translateY(-28px) scale(1);
  }
  100% {
    opacity: 0;
    transform: translateX(-50%) translateY(-40px) scale(0.5);
  }
}
</style>
