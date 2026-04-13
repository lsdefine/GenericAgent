<script setup lang="ts">
import { ref, computed } from 'vue'
import type { PeerInfo } from '@/types'
import { MOVEMENT_COLORS } from '@/utils/activity'
import { useI18n } from '@/composables/useI18n'
import { MOVEMENT_STATE_KEYS } from '@/utils/movement'

const { t } = useI18n()

const props = defineProps<{
  peer: PeerInfo
  rank?: number
  isSelf?: boolean
}>()

const stateColor = computed(() => MOVEMENT_COLORS[props.peer.movementState]?.body || '#6366f1')
const stateText = computed(() => t(MOVEMENT_STATE_KEYS[props.peer.movementState]))
const rankDisplay = computed(() => (props.rank ? String(props.rank) : ''))

const avatarFailed = ref(false)
const avatarSrc = computed(() => {
  if (props.peer.petSkin && !avatarFailed.value) {
    return `/skins/${props.peer.petSkin}/pet.png`
  }
  return ''
})
</script>

<template>
  <div class="peer-row" :class="{ 'is-self': isSelf }">
    <div class="rank-col">
      <span v-if="rank === 1" class="rank-medal gold">1</span>
      <span v-else-if="rank === 2" class="rank-medal silver">2</span>
      <span v-else-if="rank === 3" class="rank-medal bronze">3</span>
      <span v-else class="rank-num">{{ rankDisplay }}</span>
    </div>

    <div class="avatar-col">
      <img
        v-if="avatarSrc"
        class="avatar-img"
        :src="avatarSrc"
        :alt="peer.petSkin"
        @error="avatarFailed = true"
      />
      <div v-else class="avatar-custom" :title="t('anonymous')">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M12 4C8 4 5 7 5 10.5C5 14 7 16.5 9 18L10 20H14L15 18C17 16.5 19 14 19 10.5C19 7 16 4 12 4Z"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linejoin="round"
          />
          <circle cx="9.5" cy="11" r="1" fill="currentColor" />
          <circle cx="14.5" cy="11" r="1" fill="currentColor" />
          <path
            d="M10 14.5C10.8 15.3 13.2 15.3 14 14.5"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
          />
        </svg>
      </div>
    </div>

    <div class="info-col">
      <span class="peer-name">
        {{ peer.nickname || t('anonymous') }}
        <span v-if="isSelf" class="self-tag">{{ t('lbSelf') }}</span>
      </span>
      <span class="peer-state" :style="{ color: stateColor }">{{ stateText }}</span>
    </div>

    <div class="steps-col">
      <span class="steps-num">{{ peer.dailySteps.toLocaleString() }}</span>
      <span class="steps-label">{{ t('steps') }}</span>
    </div>
  </div>
</template>

<style scoped>
.peer-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  transition: background 0.15s;
}
.peer-row:hover {
  background: var(--bg-surface);
}
.peer-row.is-self {
  background: var(--accent-bg);
  border: 1px solid var(--accent-border);
}
.rank-col {
  width: 28px;
  text-align: center;
  flex-shrink: 0;
}
.rank-medal {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 800;
}
.rank-medal.gold {
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
  color: #451a03;
}
.rank-medal.silver {
  background: linear-gradient(135deg, #e2e8f0, #94a3b8);
  color: #1e293b;
}
.rank-medal.bronze {
  background: linear-gradient(135deg, #d97706, #b45309);
  color: #fff;
}
.rank-num {
  font-size: 12px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.avatar-col {
  flex-shrink: 0;
}
.avatar-img {
  width: 32px;
  height: 32px;
  image-rendering: pixelated;
  border-radius: 6px;
  background: var(--bg-surface);
}
.avatar-custom {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: var(--bg-surface-hover);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
}
.avatar-custom svg {
  width: 20px;
  height: 20px;
}
.info-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.peer-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 6px;
}
.self-tag {
  font-size: 10px;
  font-weight: 700;
  color: var(--accent-bright);
  background: var(--accent-bg-strong);
  padding: 1px 8px;
  border-radius: 4px;
  letter-spacing: 0.5px;
}
.peer-state {
  font-size: 11px;
  transition: color 0.3s;
}
.steps-col {
  text-align: right;
  flex-shrink: 0;
  display: flex;
  align-items: baseline;
  gap: 2px;
}
.steps-num {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-bright);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.3px;
}
.steps-label {
  font-size: 10px;
  color: var(--text-tertiary);
}
</style>
