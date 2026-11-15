<script setup lang="ts">
import type { Component } from 'vue'
defineProps<{ icon?: Component; title: string; compact?: boolean }>()
</script>

<template>
  <div class="empty" :class="{ 'empty--compact': compact }">
    <component :is="icon" v-if="icon" :size="compact ? 20 : 28" :stroke-width="1.5" class="empty__icon" aria-hidden="true" />
    <p class="empty__title">{{ title }}</p>
    <div v-if="$slots.default" class="empty__text"><slot /></div>
    <div v-if="$slots.actions" class="empty__actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 8px;
  padding: var(--sp-8) var(--sp-6);
  color: var(--text-2);
}
.empty--compact {
  padding: var(--sp-5) var(--sp-4);
  gap: 6px;
}
.empty__icon {
  color: var(--text-3);
  margin-bottom: 4px;
}
.empty__title {
  font-weight: var(--fw-semibold);
  color: var(--text-1);
}
.empty__text {
  font-size: var(--fs-13);
  color: var(--text-3);
  max-width: 42ch;
  line-height: 1.55;
}
.empty__actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
  justify-content: center;
}
</style>
