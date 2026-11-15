<script setup lang="ts" generic="T extends string">
import { ChevronDown } from 'lucide-vue-next'

defineProps<{ modelValue: T; options: { value: T; label: string; disabled?: boolean }[]; ariaLabel?: string; label?: string; size?: 'sm' | 'md'; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [T] }>()
const sid = `sel-${Math.random().toString(36).slice(2, 8)}`
</script>

<template>
  <div class="sel" :class="`sel--${size ?? 'md'}`">
    <label v-if="label" :for="sid" class="sel__label">{{ label }}</label>
    <div class="sel__box">
      <select :id="sid" :value="modelValue" :aria-label="ariaLabel" :disabled="disabled" @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value as T)">
        <option v-for="o in options" :key="o.value" :value="o.value" :disabled="o.disabled">{{ o.label }}</option>
      </select>
      <ChevronDown :size="14" :stroke-width="1.75" class="sel__chev" aria-hidden="true" />
    </div>
  </div>
</template>

<style scoped>
.sel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.sel__label {
  font-size: var(--fs-12);
  color: var(--text-2);
  font-weight: var(--fw-medium);
}
.sel__box {
  position: relative;
  display: flex;
}
select {
  appearance: none;
  width: 100%;
  height: var(--h-md);
  padding: 0 28px 0 9px;
  background: var(--bg-control);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-2);
  font-size: var(--fs-13);
  color: var(--text-1);
  cursor: pointer;
}
.sel--sm select {
  height: var(--h-sm);
  font-size: var(--fs-12);
}
select:hover:not(:disabled) {
  background: var(--bg-control-hover);
}
select:focus-visible {
  box-shadow: var(--focus-ring);
}
select:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
option {
  background: var(--bg-overlay);
}
.sel__chev {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  color: var(--text-3);
}
</style>
