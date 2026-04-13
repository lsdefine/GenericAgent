<script setup lang="ts">
defineProps<{
  src: string
}>()
</script>

<template>
  <img :src="src" class="image-renderer" :alt="src.split('/').pop() || 'pet animation'" />
</template>

<style scoped>
.image-renderer {
  width: 100%;
  height: 100%;
  object-fit: contain;
  pointer-events: none;
}
</style>
