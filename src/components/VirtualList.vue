<script setup lang="ts" generic="T">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

/** Fixed-row-height virtual list. Keys are stable ids supplied by `keyOf`. */
const props = withDefaults(defineProps<{ items: T[]; rowHeight: number; keyOf: (item: T) => string; overscan?: number; ariaLabel?: string; role?: string; indicatorIndex?: number }>(), { overscan: 6, role: 'listbox', indicatorIndex: -1 })
const scroller = ref<HTMLElement>()
const scrollTop = ref(0)
const height = ref(400)
let ro: ResizeObserver | null = null

const range = computed(() => {
  const start = Math.max(0, Math.floor(scrollTop.value / props.rowHeight) - props.overscan)
  const end = Math.min(props.items.length, Math.ceil((scrollTop.value + height.value) / props.rowHeight) + props.overscan)
  return { start, end }
})
const visible = computed(() => props.items.slice(range.value.start, range.value.end).map((item, i) => ({ item, index: range.value.start + i })))

function onScroll() {
  scrollTop.value = scroller.value?.scrollTop ?? 0
}
function scrollToIndex(i: number) {
  const el = scroller.value
  if (!el || i < 0) return
  const top = i * props.rowHeight
  if (top < el.scrollTop) el.scrollTop = top
  else if (top + props.rowHeight > el.scrollTop + el.clientHeight) el.scrollTop = top + props.rowHeight - el.clientHeight
}
onMounted(() => {
  ro = new ResizeObserver(() => (height.value = scroller.value?.clientHeight ?? 400))
  if (scroller.value) ro.observe(scroller.value)
})
onBeforeUnmount(() => ro?.disconnect())
defineExpose({ scrollToIndex, el: scroller })
</script>

<template>
  <div ref="scroller" class="vlist" :role="role" :aria-label="ariaLabel" :aria-multiselectable="role === 'listbox' || undefined" tabindex="0" @scroll.passive="onScroll">
    <div class="vlist__spacer" :style="{ height: items.length * rowHeight + 'px' }">
      <div v-if="indicatorIndex >= 0" class="vlist__ind" :style="{ transform: `translateY(${indicatorIndex * rowHeight}px)`, height: rowHeight + 'px' }" aria-hidden="true"><slot name="indicator" /></div>
      <div v-for="v in visible" :key="keyOf(v.item)" class="vlist__row" :style="{ transform: `translateY(${v.index * rowHeight}px)`, height: rowHeight + 'px' }">
        <slot :item="v.item" :index="v.index" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.vlist {
  overflow-y: auto;
  overflow-x: hidden;
  position: relative;
  min-height: 0;
  height: 100%;
  contain: strict;
}
.vlist:focus-visible {
  box-shadow: inset 0 0 0 2px var(--accent);
  border-radius: 0;
}
.vlist__spacer {
  position: relative;
  width: 100%;
}
.vlist__ind {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  transition: transform var(--dur-spring) var(--ease-spring);
  pointer-events: none;
}
.vlist__row {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
}
</style>
