<script setup lang="ts">
import type { MoodState } from '@/types'

defineProps<{ mood: MoodState }>()
</script>

<template>
  <span v-if="mood !== 'normal'" class="mood-icon" :class="`mi-${mood}`" aria-hidden="true">
    <template v-if="mood === 'sleepy'">
      <span class="zzz-a">z</span>
      <span class="zzz-b">z</span>
    </template>
  </span>
</template>

<style scoped>
.mood-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  vertical-align: middle;
  line-height: 1;
}

/* ═══ Sleepy: "zz" — matches MoodEffect z-drift ═══ */
.mi-sleepy {
  gap: 0.5px;
  align-items: flex-end;
}

.zzz-a,
.zzz-b {
  font-weight: 800;
  font-style: italic;
  color: #93c5fd;
  display: inline-block;
}

.zzz-a {
  font-size: 1em;
  animation: mi-zzz-bob 2s ease-in-out infinite;
}

.zzz-b {
  font-size: 0.7em;
  margin-bottom: 0.3em;
  animation: mi-zzz-bob 2s ease-in-out 0.4s infinite;
}

@keyframes mi-zzz-bob {
  0%,
  100% {
    opacity: 0.4;
    transform: translateY(0);
  }
  50% {
    opacity: 1;
    transform: translateY(-1.5px);
  }
}

/* ═══ Excited: smoke puff — matches MoodEffect smoke ═══ */
.mi-excited {
  position: relative;
  width: 1em;
  height: 1em;
}

.mi-excited::before,
.mi-excited::after {
  content: '';
  position: absolute;
  border-radius: 50%;
}

.mi-excited::before {
  width: 0.6em;
  height: 0.6em;
  bottom: 0;
  left: 10%;
  background: radial-gradient(
    circle at 40% 40%,
    rgba(255, 220, 180, 0.8),
    rgba(200, 160, 120, 0.3)
  );
  animation: mi-puff 1.2s ease-in-out infinite;
}

.mi-excited::after {
  width: 0.45em;
  height: 0.45em;
  bottom: 0.2em;
  left: 40%;
  background: radial-gradient(
    circle at 40% 40%,
    rgba(255, 230, 200, 0.7),
    rgba(200, 170, 130, 0.2)
  );
  animation: mi-puff 1.2s ease-in-out 0.4s infinite;
}

@keyframes mi-puff {
  0%,
  100% {
    opacity: 0.3;
    transform: scale(0.7) translateY(0);
  }
  50% {
    opacity: 0.8;
    transform: scale(1.1) translateY(-1px);
  }
}

/* ═══ Happy: sparkle star — matches MoodEffect stars ═══ */
.mi-happy {
  position: relative;
  width: 1em;
  height: 1em;
}

.mi-happy::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0.7em;
  height: 0.7em;
  background: linear-gradient(135deg, #fde68a, #fbbf24);
  clip-path: polygon(50% 0%, 56% 44%, 100% 50%, 56% 56%, 50% 100%, 44% 56%, 0% 50%, 44% 44%);
  transform: translate(-50%, -50%);
  animation: mi-sparkle 2s ease-in-out infinite;
  filter: drop-shadow(0 0 2px rgba(251, 191, 36, 0.5));
}

.mi-happy::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0.35em;
  height: 0.35em;
  background: linear-gradient(135deg, #fef9c3, #fde68a);
  clip-path: polygon(50% 0%, 56% 44%, 100% 50%, 56% 56%, 50% 100%, 44% 56%, 0% 50%, 44% 44%);
  transform: translate(-50%, -50%) rotate(45deg);
  animation: mi-sparkle-sub 3s linear infinite;
}

@keyframes mi-sparkle {
  0%,
  100% {
    transform: translate(-50%, -50%) rotate(0deg) scale(1);
    opacity: 1;
  }
  50% {
    transform: translate(-50%, -50%) rotate(15deg) scale(0.8);
    opacity: 0.7;
  }
}

@keyframes mi-sparkle-sub {
  0% {
    transform: translate(-50%, -50%) rotate(45deg) scale(0.7);
    opacity: 0.5;
  }
  50% {
    transform: translate(-50%, -50%) rotate(225deg) scale(1);
    opacity: 1;
  }
  100% {
    transform: translate(-50%, -50%) rotate(405deg) scale(0.7);
    opacity: 0.5;
  }
}
</style>
