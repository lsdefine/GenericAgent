<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import type { MoodState } from '@/types'

const props = defineProps<{ mood: MoodState }>()

interface MoodParticle {
  id: number
  type: 'zzz' | 'smoke' | 'star'
  left: string
  size: number
  delay: number
  letter?: string
}

const MAX_MOOD_PARTICLES = 20

const particles = ref<MoodParticle[]>([])
let nextId = 0
let spawnTimer: ReturnType<typeof setInterval> | null = null

const ZZZ_CHARS = ['z', 'z', 'Z', 'z', 'z']

function trimParticles(incoming: number) {
  if (particles.value.length + incoming > MAX_MOOD_PARTICLES) {
    particles.value = particles.value.slice(-(MAX_MOOD_PARTICLES - incoming))
  }
}

function spawnSleepy() {
  const count = 2 + Math.floor(Math.random() * 2)
  trimParticles(count)
  for (let i = 0; i < count; i++) {
    const p: MoodParticle = {
      id: nextId++,
      type: 'zzz',
      left: `${55 + Math.random() * 35}%`,
      size: 6 + Math.random() * 5,
      delay: i * 300 + Math.random() * 200,
      letter: ZZZ_CHARS[Math.floor(Math.random() * ZZZ_CHARS.length)],
    }
    particles.value.push(p)
    setTimeout(() => remove(p.id), 2800 + p.delay)
  }
}

function spawnSmoke() {
  const count = 2 + Math.floor(Math.random() * 2)
  trimParticles(count)
  for (let i = 0; i < count; i++) {
    const side = Math.random() > 0.5
    const p: MoodParticle = {
      id: nextId++,
      type: 'smoke',
      left: side ? `${-5 + Math.random() * 25}%` : `${75 + Math.random() * 25}%`,
      size: 4 + Math.random() * 5,
      delay: i * 80 + Math.random() * 60,
    }
    particles.value.push(p)
    setTimeout(() => remove(p.id), 900 + p.delay)
  }
}

function spawnHappy() {
  const count = 1 + Math.floor(Math.random() * 2)
  trimParticles(count)
  for (let i = 0; i < count; i++) {
    const p: MoodParticle = {
      id: nextId++,
      type: 'star',
      left: `${15 + Math.random() * 70}%`,
      size: 5 + Math.random() * 5,
      delay: Math.random() * 200,
    }
    particles.value.push(p)
    setTimeout(() => remove(p.id), 1500 + p.delay)
  }
}

function remove(id: number) {
  particles.value = particles.value.filter((p) => p.id !== id)
}

function stopSpawn() {
  if (spawnTimer) {
    clearInterval(spawnTimer)
    spawnTimer = null
  }
  particles.value = []
}

function startSpawn(mood: MoodState) {
  stopSpawn()
  if (mood === 'normal') return

  const config = {
    sleepy: { fn: spawnSleepy, interval: 1500 },
    excited: { fn: spawnSmoke, interval: 300 },
    happy: { fn: spawnHappy, interval: 1200 },
  }[mood]

  config.fn()
  spawnTimer = setInterval(config.fn, config.interval)
}

watch(() => props.mood, startSpawn, { immediate: true })
onUnmounted(stopSpawn)
</script>

<template>
  <div v-if="mood !== 'normal'" class="mood-effect" aria-hidden="true">
    <span
      v-for="p in particles"
      :key="p.id"
      class="mp"
      :class="`mp-${p.type}`"
      :style="{
        left: p.left,
        animationDelay: `${p.delay}ms`,
        '--mp-size': `${p.size}px`,
      }"
    >
      {{ p.type === 'zzz' ? p.letter : '' }}
    </span>
  </div>
</template>

<style scoped>
.mood-effect {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: visible;
  z-index: 2;
}

.mp {
  position: absolute;
  pointer-events: none;
}

/* ═══ Sleepy: drifting z letters ═══ */
.mp-zzz {
  top: 0;
  font-weight: 800;
  font-style: italic;
  font-size: var(--mp-size, 8px);
  color: #93c5fd;
  opacity: 0;
  animation: me-zzz-drift 2.8s ease-out forwards;
}

@keyframes me-zzz-drift {
  0% {
    opacity: 0;
    transform: translateY(0) scale(0.5) rotate(-5deg);
  }
  12% {
    opacity: 0.85;
    transform: translateY(-4px) scale(1) rotate(0deg);
  }
  60% {
    opacity: 0.6;
    transform: translateY(-18px) scale(0.85) rotate(8deg);
  }
  100% {
    opacity: 0;
    transform: translateY(-30px) scale(0.4) rotate(15deg);
  }
}

/* ═══ Excited: speed smoke puffs ═══ */
.mp-smoke {
  bottom: 2px;
  top: auto;
  width: var(--mp-size, 5px);
  height: var(--mp-size, 5px);
  border-radius: 50%;
  background: radial-gradient(
    circle at 40% 40%,
    rgba(255, 220, 180, 0.7),
    rgba(200, 160, 120, 0.4) 60%,
    rgba(160, 130, 100, 0.1)
  );
  opacity: 0;
  animation: me-smoke-puff 0.8s ease-out forwards;
}

@keyframes me-smoke-puff {
  0% {
    opacity: 0;
    transform: translate(0, 0) scale(0.3);
  }
  20% {
    opacity: 0.7;
    transform: translate(0, -2px) scale(0.8);
  }
  60% {
    opacity: 0.4;
    transform: translate(0, -10px) scale(1.3);
  }
  100% {
    opacity: 0;
    transform: translate(0, -18px) scale(1.6);
  }
}

/* ═══ Happy: sparkle stars ═══ */
.mp-star {
  top: 0;
  width: var(--mp-size, 6px);
  height: var(--mp-size, 6px);
  background: linear-gradient(135deg, #fde68a, #fbbf24);
  clip-path: polygon(50% 0%, 56% 44%, 100% 50%, 56% 56%, 50% 100%, 44% 56%, 0% 50%, 44% 44%);
  opacity: 0;
  animation: me-star-twinkle 1.4s ease-out forwards;
}

@keyframes me-star-twinkle {
  0% {
    opacity: 0;
    transform: translateY(0) scale(0) rotate(0deg);
  }
  20% {
    opacity: 1;
    transform: translateY(-6px) scale(1.2) rotate(30deg);
  }
  60% {
    opacity: 0.8;
    transform: translateY(-16px) scale(1) rotate(60deg);
  }
  100% {
    opacity: 0;
    transform: translateY(-24px) scale(0.3) rotate(90deg);
  }
}
</style>
