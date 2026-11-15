<script setup lang="ts">
/** Drag / keyboard resizable separator. Emits a delta in px; the parent clamps and stores it. */
const props = defineProps<{ orientation: 'vertical' | 'horizontal'; label: string; value: number; min: number; max: number }>()
const emit = defineEmits<{ resize: [number]; reset: [] }>()
let start = 0
let startValue = 0
let sign = 1

function down(e: PointerEvent) {
  const el = e.currentTarget as HTMLElement
  el.setPointerCapture(e.pointerId)
  start = props.orientation === 'vertical' ? e.clientX : e.clientY
  startValue = props.value
  sign = Number(el.dataset.sign ?? 1)
  el.addEventListener('pointermove', move)
  el.addEventListener('pointerup', up, { once: true })
}
function move(e: PointerEvent) {
  const pos = props.orientation === 'vertical' ? e.clientX : e.clientY
  emit('resize', Math.max(props.min, Math.min(props.max, startValue + sign * (pos - start))))
}
function up(e: PointerEvent) {
  const el = e.currentTarget as HTMLElement
  el.removeEventListener('pointermove', move)
}
function key(e: KeyboardEvent) {
  const step = e.shiftKey ? 40 : 10
  const s = Number((e.currentTarget as HTMLElement).dataset.sign ?? 1)
  const dec = props.orientation === 'vertical' ? 'ArrowLeft' : 'ArrowUp'
  const inc = props.orientation === 'vertical' ? 'ArrowRight' : 'ArrowDown'
  if (e.key === dec || e.key === inc) {
    e.preventDefault()
    e.stopPropagation()
    const d = (e.key === inc ? 1 : -1) * s * step
    emit('resize', Math.max(props.min, Math.min(props.max, props.value + d)))
  }
}
</script>

<template>
  <div
    class="resizer"
    :class="`resizer--${orientation}`"
    role="separator"
    tabindex="0"
    :aria-orientation="orientation"
    :aria-label="label"
    :aria-valuenow="value"
    :aria-valuemin="min"
    :aria-valuemax="max"
    @pointerdown="down"
    @keydown="key"
    @dblclick="emit('reset')"
  ></div>
</template>

<style scoped>
.resizer {
  position: relative;
  z-index: 3;
  flex: none;
  transition: background-color var(--dur-press) var(--ease-standard);
}
.resizer--vertical {
  width: 5px;
  margin: 0 -2px;
  cursor: col-resize;
}
.resizer--horizontal {
  height: 5px;
  margin: -2px 0;
  cursor: row-resize;
}
.resizer:hover,
.resizer:focus-visible {
  background: var(--accent-line);
  box-shadow: none;
  border-radius: 0;
}
</style>
