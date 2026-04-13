<script setup lang="ts">
import { useSocialStore } from '@/stores/social'
import { usePetStore } from '@/stores/pet'
import { useSettingsStore } from '@/stores/settings'
import { useI18n } from '@/composables/useI18n'
import PeerAvatar from './PeerAvatar.vue'
import { computed } from 'vue'
import { SELF_PEER_ID } from '@/utils/activity'
import type { PeerInfo } from '@/types'

const socialStore = useSocialStore()
const petStore = usePetStore()
const settings = useSettingsStore()
const { t } = useI18n()

const selfPeer = computed<PeerInfo>(() => ({
  peerId: SELF_PEER_ID,
  nickname: settings.nickname || t('lbSelf'),
  dailySteps: petStore.dailySteps,
  activityScore: petStore.activityScore,
  movementState: petStore.movementState,
  petSkin: settings.currentSkinId,
  lastSeen: Date.now(),
  isOnline: true,
}))

const fullLeaderboard = computed(() => {
  const all = [selfPeer.value, ...socialStore.leaderboard]
  return all.sort((a, b) => b.dailySteps - a.dailySteps)
})
</script>

<template>
  <div class="leaderboard">
    <div class="table-head">
      <span>#</span>
      <span>{{ t('settingsNickname') }}</span>
      <span class="steps-head">{{ t('steps') }}</span>
    </div>

    <div v-if="socialStore.onlinePeers.length > 0" class="lb-list">
      <PeerAvatar
        v-for="(peer, idx) in fullLeaderboard"
        :key="peer.peerId"
        :peer="peer"
        :rank="idx + 1"
        :is-self="peer.peerId === SELF_PEER_ID"
      />
    </div>

    <div v-else class="lb-empty">
      <svg class="empty-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M7 6.5H17V8.5C17 11.2 14.8 13.4 12.1 13.4H11.9C9.2 13.4 7 11.2 7 8.5V6.5Z"
          stroke="currentColor"
          stroke-width="1.6"
        />
        <path
          d="M9 13.5V16.5M15 13.5V16.5"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
        />
        <path d="M8.5 18H15.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
        <path
          d="M6.8 8.8H5.5C5.2 8.8 5 9 5 9.3V9.6C5 10.7 5.9 11.6 7 11.6"
          stroke="currentColor"
          stroke-width="1.4"
        />
        <path
          d="M17.2 8.8H18.5C18.8 8.8 19 9 19 9.3V9.6C19 10.7 18.1 11.6 17 11.6"
          stroke="currentColor"
          stroke-width="1.4"
        />
      </svg>
      <div class="empty-title">
        {{ settings.socialEnabled ? t('lbEmptySearching') : t('lbEmpty') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.leaderboard {
  padding: 0 12px;
}
.table-head {
  display: grid;
  grid-template-columns: 42px 1fr auto;
  align-items: center;
  padding: 0 12px 8px;
  color: var(--text-tertiary);
  font-size: 11px;
}
.steps-head {
  text-align: right;
}
.lb-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.lb-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 40px 20px;
}
.empty-icon {
  width: 36px;
  height: 36px;
  color: var(--text-dim);
  margin-bottom: 12px;
  display: block;
}
.empty-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
</style>
