<script setup lang="ts">
const props = defineProps<{ modelValue: boolean | 'mixed'; label?: string; ariaLabel?: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
function toggle() {
  if (props.disabled) return
  emit('update:modelValue', props.modelValue !== true)
}
</script>

<template>
  <button
    type="button"
    role="switch"
    class="sw"
    :aria-checked="modelValue === true"
    :aria-label="ariaLabel ?? label"
    :aria-disabled="disabled || undefined"
    :data-state="modelValue === 'mixed' ? 'mixed' : modelValue ? 'on' : 'off'"
    @click="toggle"
  >
    <span class="sw__track"><span class="sw__thumb"></span></span>
    <span v-if="label" class="sw__label">{{ label }}</span>
  </button>
</template>

<style scoped>
.sw {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: var(--fs-13);
}
.sw__track {
  position: relative;
  width: 38px;
  height: 22px;
  border-radius: var(--r-pill);
  background: var(--bg-control-active);
  transition: background-color var(--dur-select) var(--ease-standard);
  flex: none;
}
.sw__thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
  transition:
    transform var(--dur-spring) var(--ease-spring),
    width var(--dur-select) var(--ease-standard);
}
.sw:active:not([aria-disabled]) .sw__thumb {
  width: 20px;
}
.sw[data-state='on'] .sw__track {
  background: var(--accent);
}
.sw[data-state='on'] .sw__thumb {
  transform: translateX(16px);
}
.sw[data-state='on']:active:not([aria-disabled]) .sw__thumb {
  transform: translateX(12px);
}
.sw[data-state='mixed'] .sw__track {
  background: var(--accent-soft-strong);
}
.sw[data-state='mixed'] .sw__thumb {
  transform: translateX(8px);
}
.sw[aria-disabled] {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
