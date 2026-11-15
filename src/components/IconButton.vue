<script setup lang="ts">
import type { Component } from 'vue'
import UiIcon from './UiIcon.vue'
import UiSpinner from './UiSpinner.vue'
import { vTip } from './tooltip'

const props = withDefaults(
  defineProps<{
    icon: Component
    /** accessible name + tooltip (required for icon-only buttons) */
    label: string
    kbd?: string
    size?: 'sm' | 'md' | 'lg'
    pressed?: boolean | null
    disabled?: boolean
    disabledReason?: string | null
    loading?: boolean
    tone?: 'default' | 'danger'
  }>(),
  { size: 'md', pressed: null, tone: 'default' },
)
const emit = defineEmits<{ click: [MouseEvent] }>()
function onClick(e: MouseEvent) {
  if (props.disabled || props.loading) return
  emit('click', e)
}
</script>

<template>
  <button
    type="button"
    class="ibtn"
    :class="[`ibtn--${size}`, { 'is-pressed': pressed, 'ibtn--danger': tone === 'danger' }]"
    :aria-label="disabled && disabledReason ? `${label}（${disabledReason}）` : label"
    :aria-pressed="pressed === null ? undefined : pressed"
    :aria-disabled="disabled || loading || undefined"
    v-tip="{ text: disabled && disabledReason ? `${label} · ${disabledReason}` : label, kbd }"
    @click="onClick"
  >
    <UiSpinner v-if="loading" :size="12" />
    <UiIcon v-else :icon="icon" :size="size === 'lg' ? 'lg' : size === 'sm' ? 'sm' : 'md'" />
  </button>
</template>

<style scoped>
.ibtn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--h-md);
  height: var(--h-md);
  border-radius: var(--r-2);
  color: var(--text-2);
  flex: none;
  transition:
    background-color var(--dur-press) var(--ease-standard),
    color var(--dur-press) var(--ease-standard),
    transform var(--dur-spring) var(--ease-spring);
}
.ibtn--sm {
  width: var(--h-sm);
  height: var(--h-sm);
}
.ibtn--lg {
  width: var(--h-lg);
  height: var(--h-lg);
}
.ibtn:hover:not([aria-disabled]) {
  background: var(--bg-control);
  color: var(--text-1);
}
.ibtn:active:not([aria-disabled]) {
  background: var(--bg-control-hover);
  transform: scale(0.86);
}
.ibtn.is-pressed {
  background: var(--accent-soft);
  color: var(--accent-hover);
}
.ibtn--danger:hover:not([aria-disabled]) {
  color: var(--danger);
  background: var(--danger-soft);
}
.ibtn[aria-disabled] {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
