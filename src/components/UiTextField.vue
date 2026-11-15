<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  modelValue: string
  label?: string
  hint?: string | null
  error?: string | null
  warning?: string | null
  placeholder?: string
  mono?: boolean
  disabled?: boolean
  id?: string
  maxlength?: number
  size?: 'sm' | 'md'
  /** commit on Enter / blur instead of every keystroke */
  commitOnBlur?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [string]; commit: [string]; cancel: [] }>()
const fid = props.id ?? `tf-${Math.random().toString(36).slice(2, 8)}`
const composing = ref(false)
const local = ref(props.modelValue)
const input = ref<HTMLInputElement>()

function onInput(e: Event) {
  const v = (e.target as HTMLInputElement).value
  local.value = v
  if (!props.commitOnBlur) emit('update:modelValue', v)
}
function onKeydown(e: KeyboardEvent) {
  // IME: Enter during composition confirms the candidate, never commits the field
  if (composing.value || e.isComposing) return
  if (e.key === 'Enter') {
    emit('commit', local.value)
    if (props.commitOnBlur) emit('update:modelValue', local.value)
  } else if (e.key === 'Escape' && props.commitOnBlur) {
    local.value = props.modelValue
    emit('cancel')
    e.stopPropagation()
    input.value?.blur()
  }
}
function onBlur() {
  if (props.commitOnBlur && local.value !== props.modelValue) {
    emit('update:modelValue', local.value)
    emit('commit', local.value)
  }
}
defineExpose({ focus: () => input.value?.focus(), select: () => input.value?.select() })
</script>

<template>
  <div class="tf" :class="[`tf--${size ?? 'md'}`, { 'is-error': error, 'is-warning': !error && warning }]">
    <label v-if="label" :for="fid" class="tf__label">{{ label }}</label>
    <div class="tf__box">
      <slot name="prefix" />
      <input
        :id="fid"
        ref="input"
        class="tf__input"
        :class="{ mono }"
        :value="commitOnBlur ? local : modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :maxlength="maxlength"
        :aria-invalid="!!error || undefined"
        :aria-describedby="error || warning || hint ? `${fid}-msg` : undefined"
        spellcheck="false"
        @input="onInput"
        @keydown="onKeydown"
        @blur="onBlur"
        @compositionstart="composing = true"
        @compositionend="composing = false"
        @focus="local = modelValue"
      />
      <slot name="suffix" />
    </div>
    <p v-if="error || warning || hint" :id="`${fid}-msg`" class="tf__msg" :role="error ? 'alert' : undefined">{{ error || warning || hint }}</p>
  </div>
</template>

<style scoped>
.tf {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.tf__label {
  font-size: var(--fs-12);
  color: var(--text-2);
  font-weight: var(--fw-medium);
}
.tf__box {
  display: flex;
  align-items: center;
  gap: 6px;
  height: var(--h-md);
  padding: 0 10px;
  background: var(--bg-well);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-2);
  transition: border-color var(--dur-press) var(--ease-standard);
}
.tf--sm .tf__box {
  height: var(--h-sm);
}
.tf__box:hover {
  border-color: rgba(255, 255, 255, 0.24);
}
.tf__box:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.tf__input {
  flex: 1;
  min-width: 0;
  height: 100%;
  border: 0;
  background: transparent;
  font-size: var(--fs-13);
  color: var(--text-1);
}
.tf__input:focus-visible {
  box-shadow: none;
}
.tf__input::placeholder {
  color: var(--text-3);
}
.tf__msg {
  font-size: var(--fs-12);
  color: var(--text-3);
  line-height: 1.45;
}
.is-error .tf__box {
  border-color: var(--danger);
}
.is-error .tf__msg {
  color: var(--danger);
}
.is-warning .tf__msg {
  color: var(--warning);
}
</style>
