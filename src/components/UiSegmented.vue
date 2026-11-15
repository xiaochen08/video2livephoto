<script setup lang="ts" generic="T extends string">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{ modelValue: T; options: { value: T; label: string; count?: number | null; disabled?: boolean; tone?: 'warn' }[]; ariaLabel?: string; size?: 'sm' | 'md' }>()
const emit = defineEmits<{ 'update:modelValue': [T] }>()
const root = ref<HTMLElement>()
const pill = ref({ x: 0, w: 0, ready: false })
let ro: ResizeObserver | null = null

/** The selection pill slides (spring) to the active option; widths are measured, so labels can differ. */
function measure() {
  const el = root.value?.querySelector<HTMLElement>('[aria-checked="true"]')
  if (!el) return
  pill.value = { x: el.offsetLeft, w: el.offsetWidth, ready: true }
}
watch(() => [props.modelValue, props.options.map((o) => o.label + (o.count ?? '')).join('|')], () => nextTick(measure))
onMounted(() => {
  measure()
  ro = new ResizeObserver(measure)
  if (root.value) ro.observe(root.value)
})
onBeforeUnmount(() => ro?.disconnect())

function onKey(e: KeyboardEvent) {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  e.preventDefault()
  const enabled = props.options.filter((o) => !o.disabled)
  const i = enabled.findIndex((o) => o.value === props.modelValue)
  const next = enabled[(i + (e.key === 'ArrowRight' ? 1 : -1) + enabled.length) % enabled.length]
  if (next) emit('update:modelValue', next.value)
}
</script>

<template>
  <div ref="root" class="seg" :class="`seg--${size ?? 'md'}`" role="radiogroup" :aria-label="ariaLabel" @keydown="onKey">
    <span class="seg__pill" :class="{ ready: pill.ready }" :style="{ transform: `translateX(${pill.x - 3}px)`, width: pill.w + 'px' }" aria-hidden="true"></span>
    <button
      v-for="o in options"
      :key="o.value"
      type="button"
      role="radio"
      class="seg__opt"
      :aria-checked="o.value === modelValue"
      :tabindex="o.value === modelValue ? 0 : -1"
      :aria-disabled="o.disabled || undefined"
      @click="!o.disabled && emit('update:modelValue', o.value)"
    >
      {{ o.label }}<span v-if="o.count !== undefined && o.count !== null" class="seg__count num" :class="{ warn: o.tone === 'warn' }">{{ o.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.seg {
  position: relative;
  display: inline-flex;
  padding: 3px;
  gap: 2px;
  background: var(--bg-well);
  box-shadow: inset 0 0 0 1px var(--line);
  border-radius: var(--r-2);
}
.seg__pill {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: 3px;
  border-radius: calc(var(--r-2) - 3px);
  background: var(--bg-control-active);
  opacity: 0;
}
.seg__pill.ready {
  opacity: 1;
  transition:
    transform var(--dur-spring) var(--ease-spring),
    width var(--dur-spring) var(--ease-spring);
}
.seg__opt {
  position: relative;
  z-index: 1;
  height: calc(var(--h-md) - 6px);
  padding: 0 12px;
  border-radius: calc(var(--r-2) - 3px);
  color: var(--text-2);
  font-size: var(--fs-13);
  font-weight: var(--fw-medium);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  white-space: nowrap;
  transition: color var(--dur-select) var(--ease-standard);
}
.seg--sm .seg__opt {
  height: calc(var(--h-sm) - 6px);
  padding: 0 10px;
  font-size: var(--fs-12);
}
.seg__opt:hover:not([aria-disabled]) {
  color: var(--text-1);
}
.seg__opt[aria-checked='true'] {
  color: var(--text-1);
}
.seg__opt[aria-disabled] {
  opacity: 0.4;
  cursor: not-allowed;
}
.seg__count {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  display: inline-grid;
  place-items: center;
  font-size: var(--fs-11);
  font-weight: var(--fw-semibold);
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-2);
}
.seg__count.warn {
  background: var(--warning);
  color: #1f1a00;
  font-weight: var(--fw-bold);
}
</style>
