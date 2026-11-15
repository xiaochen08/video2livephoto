<script setup lang="ts">
withDefaults(defineProps<{ size?: number; label?: string }>(), { size: 14 })
</script>

<template>
  <span class="spinner" :style="{ width: size + 'px', height: size + 'px' }" role="status" :aria-label="label ?? '处理中'"></span>
</template>

<style scoped>
.spinner {
  display: inline-block;
  flex: none;
  border-radius: 50%;
  border: 1.75px solid currentColor;
  border-right-color: transparent;
  opacity: 0.85;
  animation: v2-spin 0.8s linear infinite;
}
</style>
