<script setup lang="ts">
import { computed } from 'vue'

/** value/max → determinate; value null → indeterminate (total unknown). Values come from data events only. */
const props = withDefaults(defineProps<{ value: number | null; max?: number; label: string; tone?: 'accent' | 'success' | 'warning' | 'danger'; thin?: boolean }>(), {
  max: 1,
  tone: 'accent',
})
const pct = computed(() => (props.value === null ? null : Math.max(0, Math.min(100, (props.value / (props.max || 1)) * 100))))
</script>

<template>
  <div
    class="pb"
    :class="[`pb--${tone}`, { 'pb--thin': thin, 'pb--indeterminate': pct === null }]"
    role="progressbar"
    :aria-label="label"
    :aria-valuemin="pct === null ? undefined : 0"
    :aria-valuemax="pct === null ? undefined : 100"
    :aria-valuenow="pct === null ? undefined : Math.round(pct)"
  >
    <div class="pb__fill" :style="pct === null ? undefined : { transform: `scaleX(${pct / 100})` }"></div>
  </div>
</template>

<style scoped>
.pb {
  position: relative;
  height: 4px;
  border-radius: var(--r-pill);
  background: var(--bg-control-active);
  overflow: hidden;
  flex: 1 1 auto;
  min-width: 40px;
}
.pb--thin {
  height: 3px;
}
.pb__fill {
  position: absolute;
  inset: 0;
  transform-origin: left center;
  background: var(--primary);
  transition: transform var(--dur-select) linear;
}
.pb--success .pb__fill {
  background: var(--success);
}
.pb--warning .pb__fill {
  background: var(--warning);
}
.pb--danger .pb__fill {
  background: var(--danger);
}
.pb--indeterminate .pb__fill {
  width: 40%;
  animation: v2-indeterminate 1.4s var(--ease-standard) infinite;
  opacity: 0.85;
}
:root.reduce-motion .pb--indeterminate .pb__fill {
  width: 100%;
  opacity: 0.35;
}
</style>
