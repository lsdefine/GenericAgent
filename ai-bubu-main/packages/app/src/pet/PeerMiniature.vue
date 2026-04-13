<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import type { PeerInfo, SkinManifest } from '@/types'
import { useI18n } from '@/composables/useI18n'
import { useSkinStore } from '@/stores/skin'
import { resolveAnimation } from '@/utils/skin'
import { MOVEMENT_STATE_KEYS } from '@/utils/movement'
import SpriteRenderer from './renderers/SpriteRenderer.vue'
import ImageRenderer from './renderers/ImageRenderer.vue'
import MoodEffect from './MoodEffect.vue'
import MoodIcon from './MoodIcon.vue'

const { t } = useI18n()
const skinStore = useSkinStore()

const props = defineProps<{
  peer: PeerInfo
  scale: number
}>()

const manifest = ref<SkinManifest | null>(null)
const loadFailed = ref(false)
const hovered = ref(false)

const skinBasePath = computed(() => `/skins/${props.peer.petSkin}/`)

const currentAnimation = computed(() => {
  if (!manifest.value) return null
  const result = resolveAnimation(props.peer.movementState, manifest.value)
  if (!result) return null
  return { ...result, src: skinBasePath.value + result.config.file }
})

const baseSize = computed(() => manifest.value?.size ?? { width: 48, height: 48 })

const rendererStyle = computed(() => {
  const w = Math.round(baseSize.value.width * props.scale)
  const h = Math.round(baseSize.value.height * props.scale)
  return { width: `${w}px`, height: `${h}px` }
})

const initial = computed(() => (props.peer.nickname || '?').charAt(0))

const capsuleSize = computed(() => {
  const s = Math.round(32 * props.scale)
  return {
    width: `${s}px`,
    height: `${s}px`,
    fontSize: `${Math.max(9, Math.round(11 * props.scale))}px`,
  }
})

const effectiveMood = computed(() => {
  const mood = props.peer.moodState ?? 'normal'
  if (mood === 'sleepy' && props.peer.movementState !== 'idle') return 'normal'
  return mood
})

const moodClass = computed(() => {
  if (effectiveMood.value === 'normal') return ''
  return `mood-${effectiveMood.value}`
})

const tooltipText = computed(() => {
  const name = props.peer.nickname || t('lbSelf')
  const steps = props.peer.dailySteps.toLocaleString()
  const state = t(MOVEMENT_STATE_KEYS[props.peer.movementState])
  return { name, steps, state }
})

const peerEl = ref<HTMLElement | null>(null)
const tipOffset = ref('translateX(-50%)')
const arrowPos = ref('50%')

function updateTipPosition() {
  if (!peerEl.value) return
  const rect = peerEl.value.getBoundingClientRect()
  const centerX = rect.left + rect.width / 2
  const winW = window.innerWidth
  const margin = 60
  if (centerX < margin) {
    tipOffset.value = 'translateX(-10%)'
    arrowPos.value = '10%'
  } else if (centerX > winW - margin) {
    tipOffset.value = 'translateX(-90%)'
    arrowPos.value = '90%'
  } else {
    tipOffset.value = 'translateX(-50%)'
    arrowPos.value = '50%'
  }
  hovered.value = true
}

function onEnter() {
  updateTipPosition()
}

function onLeave() {
  hovered.value = false
}

async function loadManifest(skinId: string) {
  if (!skinId || !skinStore.isBuiltin(skinId)) {
    loadFailed.value = true
    return
  }
  const m = await skinStore.getManifest(skinId)
  if (m) {
    manifest.value = m
    loadFailed.value = false
  } else {
    loadFailed.value = true
  }
}

watch(
  () => props.peer.petSkin,
  (id) => loadManifest(id),
  { immediate: false },
)
onMounted(() => loadManifest(props.peer.petSkin))
</script>

<template>
  <div ref="peerEl" class="peer-mini" @mouseenter="onEnter" @mouseleave="onLeave">
    <!-- sprite 动画渲染 -->
    <div
      v-if="currentAnimation && !loadFailed"
      class="peer-sprite-wrap"
      :class="moodClass"
      :style="rendererStyle"
    >
      <SpriteRenderer
        v-if="manifest?.format === 'sprite' && currentAnimation.config.sprite"
        :src="currentAnimation.src"
        :frame-width="currentAnimation.config.sprite.frameWidth"
        :frame-height="currentAnimation.config.sprite.frameHeight"
        :frame-count="currentAnimation.config.sprite.frameCount"
        :columns="currentAnimation.config.sprite.columns"
        :fps="currentAnimation.config.sprite.fps"
        :start-frame="currentAnimation.config.sprite.startFrame ?? 0"
        :loop="currentAnimation.config.loop"
      />
      <ImageRenderer v-else :src="currentAnimation.src" />
      <MoodEffect v-if="effectiveMood !== 'normal'" :mood="effectiveMood" />
    </div>

    <!-- 非内置皮肤 fallback: 圆形首字母 -->
    <div v-else class="peer-capsule" :class="moodClass" :style="capsuleSize">
      <span class="peer-initial">{{ initial }}</span>
      <MoodEffect v-if="effectiveMood !== 'normal'" :mood="effectiveMood" />
    </div>

    <!-- hover tooltip -->
    <Transition name="tip">
      <div v-if="hovered" class="peer-tip" :style="{ transform: tipOffset }">
        <div class="tip-name">{{ tooltipText.name }}</div>
        <div class="tip-detail">
          <span class="tip-steps">{{ tooltipText.steps }}{{ t('steps') }}</span>
          <span class="tip-state">{{ tooltipText.state }}</span>
          <MoodIcon v-if="effectiveMood !== 'normal'" :mood="effectiveMood" class="tip-mood" />
        </div>
        <span class="tip-arrow" :style="{ left: arrowPos }"></span>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.peer-mini {
  position: relative;
  opacity: 0.85;
  transition:
    opacity 0.2s,
    transform 0.2s;
  flex-shrink: 0;
  cursor: default;
}
.peer-mini:hover {
  opacity: 1;
  transform: scale(1.12);
  z-index: 50;
}

.peer-sprite-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  image-rendering: pixelated;
  position: relative;
}

.peer-capsule {
  position: relative;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.6), rgba(139, 92, 246, 0.5));
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1.5px solid rgba(255, 255, 255, 0.18);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
}

.peer-initial {
  color: #f1f5f9;
  font-weight: 700;
  line-height: 1;
  user-select: none;
}

/* tooltip */
.peer-tip {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  background: rgb(15, 23, 42);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 5px;
  padding: 3px 6px;
  max-width: 140px;
  pointer-events: none;
  z-index: 100;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.35);
}

.tip-arrow {
  position: absolute;
  bottom: -4px;
  transform: translateX(-50%) rotate(45deg);
  width: 6px;
  height: 6px;
  background: rgb(15, 23, 42);
  border-right: 1px solid rgba(148, 163, 184, 0.1);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
}

.tip-name {
  font-size: 9px;
  font-weight: 600;
  color: #f1f5f9;
  margin-bottom: 1px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tip-detail {
  display: flex;
  gap: 4px;
  font-size: 8px;
  white-space: nowrap;
}

.tip-steps {
  color: #a78bfa;
  font-weight: 500;
}

.tip-state {
  color: #94a3b8;
}

.tip-mood {
  font-size: 9px;
}

.tip-enter-active {
  transition: all 0.15s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.tip-leave-active {
  transition: all 0.08s ease-in;
}
.tip-enter-from {
  opacity: 0;
}
.tip-leave-to {
  opacity: 0;
}
</style>
