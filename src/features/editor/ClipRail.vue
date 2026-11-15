<script setup lang="ts">
import { Check, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useActions, useApp } from '@/app/context'
import FrameImage from '@/components/FrameImage.vue'
import { clipDisplayName, padIndex } from '@/domain/naming'
import { clipDurationUs, formatDurationShort } from '@/domain/time'
import type { Clip } from '@/domain/types'

/**
 * Clip cards (direction C). Wheel scrolls horizontally, purple arrows mark hidden content,
 * double-click opens the trim track. Thumbnails load lazily as cards scroll into view.
 */
const { session, selection, view } = useApp()
const actions = useActions()
const rail = ref<HTMLElement>()
const canLeft = ref(false)
const canRight = ref(false)
const portrait = computed(() => {
  const s = session.stream.value
  return !!s && s.height > s.width
})
const ids = computed(() => view.visibleIds.value)

function updateEdges() {
  const el = rail.value
  if (!el) return
  canLeft.value = el.scrollLeft > 4
  canRight.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 4
}
function onWheel(e: WheelEvent) {
  const el = rail.value
  if (!el) return
  const delta = Math.abs(e.deltaY) > Math.abs(e.deltaX) ? e.deltaY : e.deltaX
  if (!delta) return
  e.preventDefault()
  el.scrollLeft += delta * (e.deltaMode === 1 ? 32 : 1.1)
  updateEdges()
}
function page(dir: -1 | 1) {
  rail.value?.scrollBy({ left: dir * rail.value.clientWidth * 0.8, behavior: 'smooth' })
}
function onClick(c: Clip, e: MouseEvent) {
  const mods = { ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey }
  selection.click(c.clip_id, mods, ids.value)
  if (!mods.ctrl && !mods.shift) actions.focusClip(c.clip_id)
}
function openTrim(c: Clip) {
  actions.focusClip(c.clip_id)
  view.state.dock = 'trim'
}
let ro: ResizeObserver | null = null
onMounted(() => {
  ro = new ResizeObserver(updateEdges)
  if (rail.value) ro.observe(rail.value)
  nextTick(updateEdges)
  revealFocused('auto')
})
onBeforeUnmount(() => ro?.disconnect())
function revealFocused(behavior: ScrollBehavior = 'smooth') {
  const id = selection.state.focusedId
  if (!id || !rail.value) return
  rail.value.querySelector(`[data-clip="${id}"]`)?.scrollIntoView({ behavior, inline: 'nearest', block: 'nearest' })
}
watch(() => selection.state.focusedId, () => nextTick(() => revealFocused()))
watch(() => ids.value.length, () => setTimeout(updateEdges, 420))
</script>

<template>
  <div class="rail-box" @wheel="onWheel">
    <Transition name="arrow">
      <button v-if="canLeft" type="button" class="arrow arrow--l" aria-label="向左查看更多片段" @click="page(-1)"><ChevronLeft :size="18" :stroke-width="2.6" /></button>
    </Transition>
    <Transition name="arrow">
      <button v-if="canRight" type="button" class="arrow arrow--r" aria-label="向右查看更多片段" @click="page(1)"><ChevronRight :size="18" :stroke-width="2.6" /></button>
    </Transition>
    <div class="fade fade--l" :class="{ on: canLeft }" aria-hidden="true"></div>
    <div class="fade fade--r" :class="{ on: canRight }" aria-hidden="true"></div>
    <div ref="rail" class="rail" role="listbox" aria-label="片段卡片，双击进入剪辑轨道" aria-multiselectable="true" @scroll.passive="updateEdges">
    <TransitionGroup name="card">
      <div
        v-for="c in view.visible.value"
        :key="c.clip_id"
        :data-clip="c.clip_id"
        class="card"
        :class="{ on: selection.state.focusedId === c.clip_id, sel: selection.selectedSet.value.has(c.clip_id), off: !c.export_selected }"
        role="option"
        :aria-selected="selection.selectedSet.value.has(c.clip_id)"
        :aria-label="`${padIndex(c.display_index)} ${clipDisplayName(c)}`"
        @click="onClick(c, $event)"
        @dblclick="openTrim(c)"
      >
        <div class="card__img" :class="{ portrait }">
          <FrameImage v-if="session.project.value" :project-id="session.project.value.project_id" :frame="c.cover.frame" size="thumb" :fit="portrait ? 'contain' : 'cover'" alt="" />
          <span class="card__live">LIVE</span>
          <button type="button" class="card__check" :class="{ on: c.export_selected }" :aria-label="`${clipDisplayName(c)} 参与导出`" :aria-pressed="c.export_selected" @click.stop="actions.setExport([c.clip_id], !c.export_selected)">
            <Check :size="11" :stroke-width="3.2" />
          </button>
          <span class="card__dur num">{{ formatDurationShort(clipDurationUs(c, session.stream.value!)) }}</span>
        </div>
        <div class="card__t">
          <span class="truncate"><i class="num">{{ padIndex(c.display_index) }}</i> {{ clipDisplayName(c) }}</span>
          <span class="pills">
            <em v-if="(session.hints.value.get(c.clip_id) ?? []).includes('review')" class="rev">待检查</em>
            <em v-if="(session.hints.value.get(c.clip_id) ?? []).includes('short')">超短</em>
            <em v-if="(session.hints.value.get(c.clip_id) ?? []).includes('long')">超长</em>
            <em v-if="(session.hints.value.get(c.clip_id) ?? []).includes('cover')">封面</em>
            <em v-if="session.outdated.value.has(c.clip_id)">待更新</em>
            <em v-if="session.hasAudio.value && c.audio === 'muted'" class="mute">静音</em>
          </span>
        </div>
      </div>
    </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.rail-box {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
}
.rail {
  position: relative;
  flex: 1;
  display: flex;
  gap: 10px;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 6px 14px 10px;
  scrollbar-width: none;
}
.rail::-webkit-scrollbar {
  display: none;
}
.fade {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 56px;
  z-index: 2;
  pointer-events: none;
  opacity: 0;
  transition: opacity var(--dur-panel) var(--ease-out);
}
.fade.on {
  opacity: 1;
}
.fade--l {
  left: 0;
  background: linear-gradient(90deg, var(--bg-panel), transparent);
}
.fade--r {
  right: 0;
  background: linear-gradient(270deg, var(--bg-panel), transparent);
}
.arrow {
  position: absolute;
  top: 50%;
  z-index: 3;
  width: 32px;
  height: 32px;
  margin-top: -22px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--accent);
  color: var(--text-on-accent);
  transition:
    transform var(--dur-spring) var(--ease-spring),
    background-color var(--dur-press);
}
.arrow:hover {
  background: var(--accent-hover);
  transform: scale(1.12);
}
.arrow:active {
  transform: scale(0.88);
}
.arrow--l {
  left: 8px;
}
.arrow--r {
  right: 8px;
}
.arrow--l svg {
  animation: nudge-l 1.8s ease-in-out infinite;
}
.arrow--r svg {
  animation: nudge-r 1.8s ease-in-out infinite;
}
@keyframes nudge-r {
  50% {
    transform: translateX(2px);
  }
}
@keyframes nudge-l {
  50% {
    transform: translateX(-2px);
  }
}
.arrow-enter-active,
.arrow-leave-active {
  transition:
    opacity var(--dur-select),
    transform var(--dur-spring) var(--ease-spring);
}
.arrow-enter-from,
.arrow-leave-to {
  opacity: 0;
  transform: scale(0.5);
}
.card {
  flex: none;
  width: 168px;
  align-self: flex-start;
  padding: 6px;
  border-radius: var(--r-3);
  cursor: default;
  transition:
    transform var(--dur-spring) var(--ease-spring),
    background-color var(--dur-select) var(--ease-standard),
    box-shadow var(--dur-select) var(--ease-standard);
}
.card:hover {
  transform: translateY(-3px);
  background: var(--bg-raised);
}
.card.sel {
  background: var(--accent-soft);
}
.card.on {
  background: var(--bg-raised);
  box-shadow: 0 0 0 2px var(--accent);
  transform: translateY(-3px);
}
.card__img {
  position: relative;
  aspect-ratio: 3 / 2;
  border-radius: var(--r-2);
  overflow: hidden;
  background: #000;
}
.card__img :deep(.frame) {
  width: 100%;
  height: 100%;
}
.card__img :deep(img) {
  transition: transform 600ms var(--ease-out);
}
.card:hover .card__img :deep(img) {
  transform: scale(1.07);
}
.card.off .card__img :deep(img) {
  filter: grayscale(1) brightness(0.55);
}
.card__live {
  position: absolute;
  left: 6px;
  top: 6px;
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--brand);
  color: #fff;
  font-size: 10px;
  font-weight: var(--fw-bold);
  letter-spacing: 0.06em;
  opacity: 0;
  transform: translateY(-4px);
  transition:
    opacity var(--dur-select),
    transform var(--dur-spring) var(--ease-spring);
}
.card:hover .card__live,
.card.on .card__live {
  opacity: 1;
  transform: none;
}
.card__check {
  position: absolute;
  right: 6px;
  top: 6px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.55);
  color: transparent;
  box-shadow: inset 0 0 0 1.5px rgba(255, 255, 255, 0.7);
  transition:
    background-color var(--dur-select),
    color var(--dur-select),
    transform var(--dur-spring) var(--ease-spring);
}
.card__check.on {
  background: var(--accent);
  color: var(--text-on-accent);
  box-shadow: none;
}
.card__check:active {
  transform: scale(0.72);
}
.card__dur {
  position: absolute;
  right: 6px;
  bottom: 6px;
  font-size: 11px;
  font-weight: var(--fw-bold);
  padding: 1px 6px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.72);
}
.card__t {
  display: grid;
  gap: 4px;
  padding: 7px 2px 0;
  font-size: var(--fs-12);
  min-width: 0;
}
.card__t i {
  font-style: normal;
  color: var(--text-3);
}
.pills {
  display: flex;
  gap: 4px;
  min-height: 18px;
  overflow: hidden;
}
.pills em {
  font-style: normal;
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 6px;
  color: var(--warning);
  background: var(--warning-soft);
  white-space: nowrap;
}
.pills em.rev {
  color: #1f1a00;
  background: var(--warning);
  font-weight: var(--fw-semibold);
}
.pills em.mute {
  color: var(--text-2);
  background: rgba(255, 255, 255, 0.07);
}
.card-move,
.card-enter-active,
.card-leave-active {
  transition:
    opacity var(--dur-panel) var(--ease-out),
    transform var(--dur-spring) var(--ease-out);
}
.card-enter-from,
.card-leave-to {
  opacity: 0;
  transform: scale(0.86);
}
.card-leave-active {
  position: absolute;
}
</style>
