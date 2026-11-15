<script setup lang="ts">
import { computed, type Component } from 'vue'
import UiIcon from './UiIcon.vue'
import UiSpinner from './UiSpinner.vue'
import { vTip } from './tooltip'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-ghost'
    size?: 'sm' | 'md' | 'lg'
    icon?: Component
    iconRight?: Component
    loading?: boolean
    /** loading label keeps the original action recognisable, e.g. "导出中…" */
    loadingLabel?: string
    disabled?: boolean
    /** shown as tooltip + sr text when disabled */
    disabledReason?: string | null
    kbd?: string
    type?: 'button' | 'submit'
    block?: boolean
  }>(),
  { variant: 'secondary', size: 'md', type: 'button' },
)
const emit = defineEmits<{ click: [MouseEvent] }>()
const inactive = computed(() => props.disabled || props.loading)
const reasonId = `btn-reason-${Math.random().toString(36).slice(2, 8)}`

function onClick(e: MouseEvent) {
  if (inactive.value) {
    e.preventDefault()
    return
  }
  emit('click', e)
}
</script>

<template>
  <button
    :type="type"
    class="btn"
    :class="[`btn--${variant}`, `btn--${size}`, { 'btn--block': block, 'is-loading': loading }]"
    :aria-disabled="inactive || undefined"
    :aria-busy="loading || undefined"
    :aria-describedby="disabled && disabledReason ? reasonId : undefined"
    v-tip="disabled && disabledReason ? disabledReason : null"
    @click="onClick"
  >
    <UiSpinner v-if="loading" :size="size === 'sm' ? 12 : 14" />
    <UiIcon v-else-if="icon" :icon="icon" :size="size === 'lg' ? 'md' : size === 'sm' ? 'sm' : 'md'" />
    <span class="btn__label"><template v-if="loading && loadingLabel">{{ loadingLabel }}</template><slot v-else /></span>
    <UiIcon v-if="iconRight && !loading" :icon="iconRight" size="sm" />
    <span v-if="kbd" class="kbd btn__kbd">{{ kbd }}</span>
    <span v-if="disabled && disabledReason" :id="reasonId" class="sr-only">{{ disabledReason }}</span>
  </button>
</template>

<style scoped>
.btn {
  --btn-h: var(--h-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: var(--btn-h);
  padding: 0 13px;
  border-radius: var(--r-2);
  font-size: var(--fs-13);
  font-weight: var(--fw-semibold);
  white-space: nowrap;
  border: 0;
  transition:
    background-color var(--dur-press) var(--ease-standard),
    color var(--dur-press) var(--ease-standard),
    box-shadow var(--dur-press) var(--ease-standard),
    transform var(--dur-spring) var(--ease-spring);
}
.btn:active:not([aria-disabled]) {
  transform: scale(0.95);
}
.btn--sm {
  --btn-h: var(--h-sm);
  padding: 0 10px;
  font-size: var(--fs-12);
  gap: 5px;
}
.btn--lg {
  --btn-h: var(--h-lg);
  padding: 0 18px;
  font-size: var(--fs-14);
  border-radius: var(--r-3);
}
.btn--block {
  width: 100%;
}
.btn__label {
  display: inline-flex;
  align-items: center;
}
.btn__kbd {
  margin-left: 2px;
  margin-right: -4px;
}

.btn--primary {
  background: var(--primary);
  color: var(--primary-text);
  font-weight: var(--fw-bold);
}
.btn--primary:hover:not([aria-disabled]) {
  background: var(--primary-hover);
}
.btn--primary:active:not([aria-disabled]) {
  background: var(--primary-pressed);
}
.btn--primary .btn__kbd {
  background: rgba(0, 0, 0, 0.08);
  border-color: rgba(0, 0, 0, 0.14);
  color: var(--primary-text);
}

.btn--secondary {
  background: var(--bg-control);
  color: var(--text-1);
  box-shadow: inset 0 0 0 1px var(--line);
}
.btn--secondary:hover:not([aria-disabled]) {
  background: var(--bg-control-hover);
}
.btn--secondary:active:not([aria-disabled]) {
  background: var(--bg-control-active);
}

.btn--ghost {
  color: var(--text-2);
  padding: 0 9px;
  background: transparent;
  font-weight: var(--fw-medium);
}
.btn--ghost:hover:not([aria-disabled]) {
  background: var(--bg-control);
  color: var(--text-1);
}
.btn--ghost:active:not([aria-disabled]) {
  background: var(--bg-control-hover);
}

.btn--danger {
  background: var(--danger);
  color: #fff;
}
.btn--danger:hover:not([aria-disabled]) {
  background: var(--danger-hover);
}
.btn--danger-ghost {
  color: var(--danger);
  background: var(--danger-soft);
}
.btn--danger-ghost:hover:not([aria-disabled]) {
  background: rgba(255, 69, 58, 0.2);
}

.btn[aria-disabled]:not(.is-loading) {
  opacity: 0.38;
  cursor: not-allowed;
}
.btn.is-loading {
  cursor: progress;
}
</style>
