<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useActions, useApp } from '@/app/context'
import { CUT_KIND_LABEL } from '@/domain/clipHints'
import { padIndex } from '@/domain/naming'
import { formatTime, framesToUs } from '@/domain/time'

/**
 * Whole-video overview (direction C): one segment per clip, yellow dots for cuts that need review,
 * white playhead. Click a segment to focus it, a dot to review that cut, empty space to seek.
 */
const { session, selection, playhead } = useApp()
const actions = useActions()
const t = session.timeline
const fc = computed(() => t.value?.frame_count ?? 1)
const pct = (f: number) => (f / fc.value) * 100
const ph = ref<HTMLElement>()
let off: (() => void) | null = null
onMounted(() => {
  off = playhead.subscribe((f) => {
    if (ph.value) ph.value.style.left = pct(f) + '%'
  })
})
onBeforeUnmount(() => off?.())

function seek(e: MouseEvent) {
  const el = e.currentTarget as HTMLElement
  const r = el.getBoundingClientRect()
  playhead.requestSeek(Math.floor(((e.clientX - r.left) / r.width) * (fc.value - 1)))
}
function rate() {
  return session.stream.value!.frame_rate
}
</script>

<template>
  <div class="ov" role="group" aria-label="整条视频概览" @click="seek">
    <button
      v-for="c in t?.clips ?? []"
      :key="c.clip_id"
      type="button"
      class="ov__seg"
      :class="{ on: selection.state.focusedId === c.clip_id, sel: selection.selectedSet.value.has(c.clip_id), off: !c.export_selected, tiny: (c.end_frame - c.start_frame) / fc < 0.004 }"
      :style="{ left: pct(c.start_frame) + '%', width: pct(c.end_frame - c.start_frame) + '%' }"
      :aria-label="`片段 ${padIndex(c.display_index)}`"
      v-tip="`片段 ${padIndex(c.display_index)} · ${formatTime(framesToUs(c.end_frame - c.start_frame, rate()))}`"
      @click.stop="actions.focusClip(c.clip_id)"
    ></button>
    <button
      v-for="cut in session.pendingCuts.value"
      :key="cut.cut_id"
      type="button"
      class="ov__cut"
      :style="{ left: pct(cut.frame) + '%' }"
      :aria-label="`${CUT_KIND_LABEL[cut.kind]}切点待检查，点击检查`"
      v-tip="`${CUT_KIND_LABEL[cut.kind]} · 待检查（点击检查）`"
      @click.stop="actions.startReview(cut.cut_id)"
    ></button>
    <div ref="ph" class="ov__ph" aria-hidden="true"></div>
  </div>
</template>

<style scoped>
.ov {
  position: relative;
  flex: 1;
  min-width: 80px;
  height: 30px;
  cursor: text;
}
.ov__seg {
  position: absolute;
  top: 7px;
  bottom: 7px;
  min-width: 2px;
  border-radius: 4px;
  background: var(--clip-fill);
  box-shadow: inset -1px 0 0 var(--bg-panel);
  transition:
    background-color var(--dur-select) var(--ease-standard),
    top var(--dur-spring) var(--ease-spring),
    bottom var(--dur-spring) var(--ease-spring);
}
.ov__seg:hover {
  background: #383838;
}
.ov__seg.sel {
  background: var(--accent-soft-strong);
}
.ov__seg.on {
  top: 3px;
  bottom: 3px;
  background: var(--accent);
  z-index: 1;
}
.ov__seg.off {
  background: var(--clip-off);
}
.ov__seg.tiny {
  background: var(--warning);
  min-width: 3px;
}
.ov__cut {
  position: absolute;
  top: -2px;
  width: 10px;
  height: 10px;
  margin-left: -5px;
  border-radius: 50%;
  background: var(--warning);
  box-shadow: 0 0 0 3px rgba(255, 214, 10, 0.18);
  z-index: 2;
  transition: transform var(--dur-spring) var(--ease-spring);
}
.ov__cut:hover {
  transform: scale(1.4);
}
.ov__ph {
  position: absolute;
  top: -4px;
  bottom: -4px;
  width: 2px;
  margin-left: -1px;
  border-radius: 1px;
  background: var(--playhead);
  z-index: 3;
  pointer-events: none;
}
</style>
