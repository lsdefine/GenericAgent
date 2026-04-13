<script setup lang="ts">
import { usePeerEscort } from '@/composables/usePeerEscort'
import PeerMiniature from './PeerMiniature.vue'
import OverflowBadge from './OverflowBadge.vue'

const { visibleBehind, visibleAhead, overflowBehind, overflowAhead, hasPeers } = usePeerEscort()
</script>

<template>
  <div class="peer-overlay" :class="{ 'has-peers': hasPeers }">
    <!-- 左侧：步数落后的同事 -->
    <div v-if="hasPeers" class="side side-left">
      <OverflowBadge
        v-if="overflowBehind"
        :count="overflowBehind.count"
        :peers="overflowBehind.peers"
        side="left"
      />
      <PeerMiniature
        v-for="ep in [...visibleBehind].reverse()"
        :key="ep.peer.peerId"
        :peer="ep.peer"
        :scale="ep.scale"
      />
    </div>

    <!-- 中央：主宠物 -->
    <div class="center">
      <slot></slot>
    </div>

    <!-- 右侧：步数领先的同事 -->
    <div v-if="hasPeers" class="side side-right">
      <PeerMiniature
        v-for="ep in visibleAhead"
        :key="ep.peer.peerId"
        :peer="ep.peer"
        :scale="ep.scale"
      />
      <OverflowBadge
        v-if="overflowAhead"
        :count="overflowAhead.count"
        :peers="overflowAhead.peers"
        side="right"
      />
    </div>
  </div>
</template>

<style scoped>
.peer-overlay {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 0;
  width: 100%;
}

.side {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  min-width: 0;
  position: relative;
  z-index: 1;
}

.side-left {
  justify-content: flex-end;
}

.side-right {
  justify-content: flex-start;
}

.center {
  flex-shrink: 0;
}
</style>
