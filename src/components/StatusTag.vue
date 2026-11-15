<script setup lang="ts">
import { AlertTriangle, Check, Clock, Pause, RefreshCw, SkipForward, X, CircleDot } from 'lucide-vue-next'
import { computed } from 'vue'
import type { Tone } from '@/domain/jobStates'
import UiSpinner from './UiSpinner.vue'

const props = withDefaults(defineProps<{ tone?: Tone; icon?: string; label: string; size?: 'sm' | 'md'; subtle?: boolean }>(), { tone: 'neutral', size: 'md' })
const iconCmp = computed(
  () => ({ check: Check, x: X, clock: Clock, pause: Pause, refresh: RefreshCw, skip: SkipForward, alert: AlertTriangle, dot: CircleDot })[props.icon ?? ''] ?? null,
)
</script>

<template>
  <span class="tag" :class="[`tag--${tone}`, `tag--${size}`, { 'tag--subtle': subtle }]">
    <UiSpinner v-if="icon === 'spinner'" :size="10" :label="label" />
    <component :is="iconCmp" v-else-if="iconCmp" :size="12" :stroke-width="2" aria-hidden="true" />
    <span>{{ label }}</span>
  </span>
</template>

<style scoped>
.tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 20px;
  padding: 0 7px;
  border-radius: var(--r-1);
  font-size: var(--fs-12);
  font-weight: var(--fw-medium);
  white-space: nowrap;
  line-height: 1;
  flex: none;
}
.tag--sm {
  height: 18px;
  padding: 0 5px;
  font-size: var(--fs-11);
}
.tag--neutral {
  background: var(--bg-control);
  color: var(--text-2);
}
.tag--muted {
  background: transparent;
  color: var(--text-3);
  box-shadow: 0 0 0 1px var(--line) inset;
}
.tag--accent {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-1);
}
.tag--success {
  background: var(--success-soft);
  color: var(--success);
}
.tag--warning {
  background: var(--warning-soft);
  color: var(--warning);
}
.tag--danger {
  background: var(--danger-soft);
  color: var(--danger);
}
.tag--subtle {
  background: transparent;
  padding: 0;
}
</style>
