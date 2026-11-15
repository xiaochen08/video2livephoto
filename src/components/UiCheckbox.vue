<script setup lang="ts">
const props = defineProps<{ checked: boolean | 'mixed'; label?: string; ariaLabel?: string; disabled?: boolean; small?: boolean }>()
const emit = defineEmits<{ change: [boolean, MouseEvent | KeyboardEvent] }>()
function toggle(e: MouseEvent | KeyboardEvent) {
  if (props.disabled) return
  emit('change', props.checked !== true, e)
}
</script>

<template>
  <button
    type="button"
    role="checkbox"
    class="cb"
    :class="{ 'cb--small': small }"
    :aria-checked="checked === 'mixed' ? 'mixed' : checked"
    :aria-label="ariaLabel"
    :aria-disabled="disabled || undefined"
    @click.stop="toggle"
  >
    <span class="cb__box" :data-state="checked === 'mixed' ? 'mixed' : checked ? 'on' : 'off'">
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path v-if="checked === 'mixed'" class="cb__mix" d="M4 8h8" />
        <path v-else class="cb__tick" d="M3.5 8.5l3 3 6-7" />
      </svg>
    </span>
    <span v-if="label" class="cb__label">{{ label }}</span>
  </button>
</template>

<style scoped>
.cb {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 22px;
  color: var(--text-1);
  font-size: var(--fs-13);
}
.cb__box {
  width: 18px;
  height: 18px;
  border-radius: var(--r-1);
  box-shadow: inset 0 0 0 1.5px var(--line-strong);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  transition:
    background-color var(--dur-select) var(--ease-standard),
    box-shadow var(--dur-select) var(--ease-standard),
    transform var(--dur-spring) var(--ease-spring);
}
.cb--small .cb__box {
  width: 16px;
  height: 16px;
}
.cb__box svg {
  width: 12px;
  height: 12px;
  fill: none;
  stroke: var(--text-on-accent);
  stroke-width: 2.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.cb__tick {
  stroke-dasharray: 16;
  stroke-dashoffset: 16;
  transition: stroke-dashoffset 280ms var(--ease-out);
}
.cb:hover .cb__box {
  box-shadow: inset 0 0 0 1.5px var(--text-3);
}
.cb:active:not([aria-disabled]) .cb__box {
  transform: scale(0.8);
}
.cb__box[data-state='on'],
.cb__box[data-state='mixed'] {
  background: var(--accent);
  box-shadow: none;
}
.cb__box[data-state='on'] .cb__tick {
  stroke-dashoffset: 0;
}
.cb[aria-disabled] {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
