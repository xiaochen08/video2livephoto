<script setup lang="ts">
/**
 * Trim track for the focused clip (direction C).
 *
 * Every change is a backend-confirmed edit command, never a local mutation:
 *   edge drag / set in-out / nudge / numeric → move_cut   (the neighbour changes with it)
 *   slide (keep duration)                     → two move_cut, ordered so constraints hold
 *   split → add_cut · merge → remove_cut (audio conflict dialog) · cover → set_cover · mute → set_clip_props
 * While a drag is in progress the UI shows a local tentative value; after release it waits for the
 * confirmed timeline. Rejections restore the confirmed state and show the backend's reason.
 * Units are frames; display time codes are derived only for presentation.
 */
import {
  ArrowLeftToLine, Check, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Image, Magnet, Maximize2, Minus, MoveHorizontal, Play, Plus,
  Redo2, RotateCcw, Scissors, SquareArrowLeft, SquareArrowRight, Undo2, Volume2, VolumeX,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useActions, useApp } from '@/app/context'
import FrameImage from '@/components/FrameImage.vue'
import UiSpinner from '@/components/UiSpinner.vue'
import { toAppError } from '@/domain/errors'
import { clipDisplayName, padIndex } from '@/domain/naming'
import { formatTime, framesToUs, usToFrame } from '@/domain/time'
import type { Cut } from '@/domain/types'

const emit = defineEmits<{ done: [] }>()
const { session, selection, playhead, ui, view } = useApp()
const actions = useActions()
const t = session.timeline
const stream = session.stream
const project = session.project

const rate = computed(() => stream.value!.frame_rate)
const fps = computed(() => rate.value.num / rate.value.den)
const fc = computed(() => t.value?.frame_count ?? 1)
const tcode = (f: number) => formatTime(framesToUs(f, rate.value))
const clampN = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

const idx = computed(() => session.clipIndexById.value.get(selection.state.focusedId ?? '') ?? -1)
const clip = computed(() => (idx.value >= 0 ? t.value!.clips[idx.value] : null))
const prev = computed(() => (idx.value > 0 ? t.value!.clips[idx.value - 1] : null))
const next = computed(() => (idx.value >= 0 ? (t.value!.clips[idx.value + 1] ?? null) : null))
const leftCut = computed<Cut | null>(() => (idx.value > 0 ? t.value!.cuts[idx.value - 1] : null))
const rightCut = computed<Cut | null>(() => (idx.value >= 0 ? (t.value!.cuts[idx.value] ?? null) : null))

/* ------------------------------ tentative (local) values ------------------------------ */
const tent = ref<{ start?: number; end?: number; cover?: number } | null>(null)
const start = computed(() => tent.value?.start ?? clip.value?.start_frame ?? 0)
const end = computed(() => tent.value?.end ?? clip.value?.end_frame ?? 1)
const coverF = computed(() => tent.value?.cover ?? clip.value?.cover.frame ?? 0)
const busy = computed(() => !!session.state.pending)

/* ------------------------------------ entry / deltas ------------------------------------ */
const entry = shallowRef<{ id: string; start: number; end: number } | null>(null)
function markEntry() {
  entry.value = clip.value ? { id: clip.value.clip_id, start: clip.value.start_frame, end: clip.value.end_frame } : null
}
watch(() => clip.value?.clip_id, () => {
  markEntry()
  pan.value = 0
})
const headDelta = computed(() => (entry.value && clip.value && entry.value.id === clip.value.clip_id ? entry.value.start - start.value : 0))
const tailDelta = computed(() => (entry.value && clip.value && entry.value.id === clip.value.clip_id ? end.value - entry.value.end : 0))
const changed = computed(() => headDelta.value !== 0 || tailDelta.value !== 0)
const fmtDelta = (frames: number) => `${frames > 0 ? '+' : '−'}${(Math.abs(frames) / fps.value).toFixed(2)}s`

/* ----------------------------------------- view ----------------------------------------- */
const mode = ref<'trim' | 'slide'>('trim')
const snapPlayhead = ref(true)
const pan = ref(0) // frames
const trackEl = ref<HTMLElement>()
const phEl = ref<HTMLElement>()
const width = ref(1000)
const frozen = ref<{ a: number; b: number } | null>(null)
const liveWin = computed(() => {
  const c = clip.value
  if (!c) return { a: 0, b: fc.value }
  const len = c.end_frame - c.start_frame
  const ctx = Math.max(1.2 * fps.value, len * 0.45)
  const span = Math.min(fc.value, Math.max(12, (len + ctx * 2) / view.state.trimZoom))
  const center = c.start_frame + len / 2 + pan.value
  const a = clampN(center - span / 2, 0, fc.value - span)
  return { a, b: a + span }
})
const win = computed(() => frozen.value ?? liveWin.value)
const pct = (f: number) => ((f - win.value.a) / (win.value.b - win.value.a)) * 100
const pxPerFrame = computed(() => width.value / (win.value.b - win.value.a))
const ticks = computed(() => {
  const spanSec = (win.value.b - win.value.a) / fps.value
  const step = [0.2, 0.5, 1, 2, 5, 10, 30, 60].find((s) => spanSec / s <= 14) ?? 120
  const out: { f: number; label: string | null }[] = []
  for (let sec = Math.ceil(win.value.a / fps.value / step) * step; sec * fps.value <= win.value.b; sec += step) {
    const f = Math.round(sec * fps.value)
    out.push({ f, label: Math.round(sec / step) % 2 === 0 ? tcode(f).slice(0, step < 1 ? 9 : 5) : null })
  }
  return out
})
const others = computed(() =>
  (t.value?.clips ?? [])
    .filter((c) => c.clip_id !== clip.value?.clip_id && c.end_frame > win.value.a && c.start_frame < win.value.b)
    .map((c) => {
      // neighbours follow the tentative edge so the track never shows a gap while dragging
      const s0 = c.clip_id === next.value?.clip_id ? end.value : c.start_frame
      const e0 = c.clip_id === prev.value?.clip_id ? start.value : c.end_frame
      const l = Math.max(0, pct(s0))
      const r = Math.min(100, pct(e0))
      return { c, left: l, width: Math.max(0, r - l), adj: c.clip_id === prev.value?.clip_id || c.clip_id === next.value?.clip_id, right: c.start_frame > (clip.value?.start_frame ?? 0) }
    }),
)
const tiles = computed(() => {
  const w = ((pct(end.value) - pct(start.value)) / 100) * width.value
  const n = clampN(Math.round(w / 110), 1, 10)
  const len = end.value - start.value
  return Array.from({ length: n }, (_, k) => start.value + Math.floor(((k + 0.5) * len) / n))
})

/* ------------------------------------- commands ------------------------------------- */
async function run(fn: () => Promise<unknown>) {
  try {
    await fn()
  } catch (e) {
    const err = toAppError(e)
    if (err.code !== 'EDIT_VERSION_CONFLICT') ui.toast(err.message, { tone: 'danger', timeout: 6000 })
  } finally {
    tent.value = null
  }
}
const moveCut = (cut: Cut, frame: number) => session.edit({ type: 'move_cut', cut_id: cut.cut_id, frame })
function startBounds() {
  return { lo: (prev.value?.start_frame ?? 0) + 1, hi: (clip.value?.end_frame ?? 1) - 1 }
}
function endBounds() {
  return { lo: (clip.value?.start_frame ?? 0) + 1, hi: (next.value?.end_frame ?? fc.value) - 1 }
}
function setStart(frame: number) {
  const cut = leftCut.value
  if (!cut || !clip.value) return
  const b = startBounds()
  const f = clampN(Math.round(frame), b.lo, b.hi)
  if (f === clip.value.start_frame) return
  tent.value = { start: f }
  void run(() => moveCut(cut, f))
  playhead.requestSeek(f)
}
function setEnd(frame: number) {
  const cut = rightCut.value
  if (!cut || !clip.value) return
  const b = endBounds()
  const f = clampN(Math.round(frame), b.lo, b.hi)
  if (f === clip.value.end_frame) return
  tent.value = { end: f }
  void run(() => moveCut(cut, f))
  playhead.requestSeek(f - 1)
}
function slideTo(newStart: number) {
  const c = clip.value
  if (!leftCut.value || !rightCut.value || !c || !prev.value || !next.value) return
  const len = c.end_frame - c.start_frame
  const s = clampN(Math.round(newStart), prev.value.start_frame + 1, next.value.end_frame - 1 - len)
  if (s === c.start_frame) return
  tent.value = { start: s, end: s + len }
  // Both boundaries are submitted as one backend transaction so a failed
  // slide leaves the confirmed timeline intact and creates one undo entry.
  void run(() => session.edit({ type: 'set_clip_bounds', clip_id: c.clip_id, start_frame: s, end_frame: s + len }))
}
function inside(f: number) {
  return !!clip.value && f > clip.value.start_frame && f < clip.value.end_frame
}
function split() {
  if (!inside(playhead.frame)) {
    ui.toast('请先把播放头移到本段内部（两侧各至少 1 帧）再拆分。', { tone: 'warning' })
    return
  }
  void actions.addCutAtPlayhead()
}
function setCover(frame: number) {
  const c = clip.value
  if (!c) return
  const f = clampN(Math.round(frame), c.start_frame, c.end_frame - 1)
  if (f === c.cover.frame && c.cover.origin === 'user') return
  tent.value = { cover: f }
  void run(() => session.edit({ type: 'set_cover', clip_id: c.clip_id, frame: f }))
}
function setCoverHere() {
  const f = playhead.frame
  if (!clip.value || f < clip.value.start_frame || f >= clip.value.end_frame) {
    ui.toast('播放头不在本段内，无法设为封面。', { tone: 'warning' })
    return
  }
  setCover(f)
}
function toggleMute() {
  const c = clip.value
  if (c) void actions.setAudio([c.clip_id], c.audio === 'muted' ? 'source' : 'muted')
}
function resetClip() {
  const e = entry.value
  const c = clip.value
  if (!e || !c || e.id !== c.clip_id) return
  void run(() => session.edit({ type: 'set_clip_bounds', clip_id: c.clip_id, start_frame: e.start, end_frame: e.end }))
}

/* ------------------------------------ pointer drag ------------------------------------ */
type DragKind = 'start' | 'end' | 'slide' | 'cover' | 'scrub'
const drag = ref<{ kind: DragKind; x0: number; s0: number; value: number; snapped: boolean } | null>(null)
function frameAt(clientX: number) {
  const r = trackEl.value!.getBoundingClientRect()
  return win.value.a + clampN((clientX - r.left) / r.width, 0, 1) * (win.value.b - win.value.a)
}
function down(kind: DragKind, e: PointerEvent) {
  if (e.button !== 0 || !clip.value) return
  if (kind === 'slide' && mode.value !== 'slide') kind = 'scrub'
  if ((kind === 'start' || kind === 'end' || kind === 'slide' || kind === 'cover') && busy.value) return
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  frozen.value = { ...win.value }
  drag.value = { kind, x0: e.clientX, s0: clip.value.start_frame, value: 0, snapped: false }
  if (kind === 'scrub') playhead.requestSeek(Math.floor(frameAt(e.clientX)))
}
function move(e: PointerEvent) {
  const g = drag.value
  const c = clip.value
  if (!g || !c) return
  let f = frameAt(e.clientX)
  if (g.kind === 'scrub') return playhead.requestSeek(clampN(Math.floor(f), 0, fc.value - 1))
  if (g.kind === 'slide') {
    const len = c.end_frame - c.start_frame
    const s = clampN(Math.round(g.s0 + (e.clientX - g.x0) / pxPerFrame.value), (prev.value?.start_frame ?? 0) + 1, (next.value?.end_frame ?? fc.value) - 1 - len)
    g.value = s
    tent.value = { start: s, end: s + len }
    playhead.requestSeek(s)
    return
  }
  g.snapped = false
  if (snapPlayhead.value && g.kind !== 'cover' && Math.abs((f - playhead.frame) * pxPerFrame.value) < 7) {
    f = playhead.frame
    g.snapped = true
  }
  if (g.kind === 'cover') {
    const v = clampN(Math.round(f), c.start_frame, c.end_frame - 1)
    g.value = v
    tent.value = { cover: v }
    playhead.requestSeek(v)
  } else if (g.kind === 'start') {
    const b = startBounds()
    const v = clampN(Math.round(f), b.lo, b.hi)
    g.value = v
    tent.value = { start: v }
    playhead.requestSeek(v)
  } else {
    const b = endBounds()
    const v = clampN(Math.round(f), b.lo, b.hi)
    g.value = v
    tent.value = { end: v }
    playhead.requestSeek(v - 1)
  }
}
function up() {
  const g = drag.value
  if (!g) return
  drag.value = null
  frozen.value = null
  if (g.kind === 'scrub') return
  if (!tent.value) return
  // one confirmed command per gesture
  if (g.kind === 'start') setStart(g.value)
  else if (g.kind === 'end') setEnd(g.value)
  else if (g.kind === 'slide') slideTo(g.value)
  else setCover(g.value)
  if (tent.value && ((g.kind === 'start' && g.value === clip.value?.start_frame) || (g.kind === 'end' && g.value === clip.value?.end_frame))) tent.value = null
}
function cancelDrag(e: KeyboardEvent) {
  if (e.key === 'Escape' && drag.value) {
    e.stopPropagation()
    cancelPointer()
  }
}
function cancelPointer(e?: PointerEvent) {
  if (!drag.value) return
  if (e && trackEl.value?.hasPointerCapture(e.pointerId)) trackEl.value.releasePointerCapture(e.pointerId)
  drag.value = null
  frozen.value = null
  tent.value = null
}
function onWindowBlur() {
  cancelPointer()
}
function onVisibilityChange() {
  if (document.hidden) cancelPointer()
}
function onWheel(e: WheelEvent) {
  e.preventDefault()
  if (e.ctrlKey || e.metaKey) view.state.trimZoom = clampN(view.state.trimZoom * (e.deltaY < 0 ? 1.2 : 1 / 1.2), 1, 16)
  else pan.value = clampN(pan.value + ((e.deltaY + e.deltaX) / pxPerFrame.value) * 0.6, -fc.value, fc.value)
}
function fit() {
  view.state.trimZoom = 1
  pan.value = 0
}
function onHandleKey(edge: 'start' | 'end', e: KeyboardEvent) {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  e.preventDefault()
  e.stopPropagation()
  const d = (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 10 : 1)
  if (edge === 'start') setStart(start.value + d)
  else setEnd(end.value + d)
}

/* --------------------------------- numeric fields --------------------------------- */
const fields = ref({ start: '', end: '', dur: '' })
const bad = ref({ start: false, end: false, dur: false })
watch([() => clip.value?.start_frame, () => clip.value?.end_frame], () => {
  if (!clip.value) return
  fields.value = { start: tcode(clip.value.start_frame), end: tcode(clip.value.end_frame), dur: ((clip.value.end_frame - clip.value.start_frame) / fps.value).toFixed(2) }
}, { immediate: true })
/** "mm:ss.mmm" / "ss.mmm" → frame; "#123" → frame 123 */
function parseFrame(v: string): number | null {
  const s = v.trim()
  if (/^#\d+$/.test(s)) return Number(s.slice(1))
  const m = s.match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/)
  if (!m) return null
  return usToFrame(((m[1] ? Number(m[1]) * 60 : 0) + Number(m[2])) * 1e6 + 1, rate.value)
}
function applyField(k: 'start' | 'end' | 'dur') {
  const c = clip.value
  if (!c) return
  let f: number | null
  if (k === 'dur') {
    const sec = Number(fields.value.dur)
    f = Number.isFinite(sec) && sec > 0 ? c.start_frame + Math.max(1, Math.round(sec * fps.value)) : null
  } else f = parseFrame(fields.value[k])
  const b = k === 'start' ? startBounds() : endBounds()
  const blocked = (k === 'start' && !leftCut.value) || (k !== 'start' && !rightCut.value)
  if (f === null || blocked || f < b.lo || f > b.hi) {
    bad.value[k] = true
    setTimeout(() => (bad.value[k] = false), 600)
    fields.value = { start: tcode(c.start_frame), end: tcode(c.end_frame), dur: ((c.end_frame - c.start_frame) / fps.value).toFixed(2) }
    return
  }
  if (k === 'start') setStart(f)
  else setEnd(f)
}

/* ------------------------------------- keyboard ------------------------------------- */
function onKey(e: KeyboardEvent) {
  if (e.isComposing || ui.state.overlays.length || e.ctrlKey || e.metaKey || e.altKey) return
  const tg = e.target as HTMLElement
  if (tg && (tg.tagName === 'INPUT' || tg.tagName === 'TEXTAREA' || tg.tagName === 'SELECT' || tg.isContentEditable)) return
  const k = e.key.toLowerCase()
  if (k === 'i') {
    e.preventDefault()
    setStart(playhead.frame)
  } else if (k === 'o') {
    e.preventDefault()
    setEnd(playhead.frame + 1)
  }
}
let ro: ResizeObserver | null = null
let offPh: (() => void) | null = null
onMounted(() => {
  markEntry()
  window.addEventListener('keydown', onKey)
  window.addEventListener('keydown', cancelDrag, true)
  window.addEventListener('blur', onWindowBlur)
  document.addEventListener('visibilitychange', onVisibilityChange)
  ro = new ResizeObserver(() => (width.value = trackEl.value?.clientWidth ?? 1000))
  if (trackEl.value) ro.observe(trackEl.value)
  offPh = playhead.subscribe((f) => {
    if (!phEl.value) return
    const p = pct(f)
    phEl.value.style.left = p + '%'
    phEl.value.style.display = p < 0 || p > 100 ? 'none' : 'block'
  })
})
watch(win, () => {
  if (!phEl.value) return
  const p = pct(playhead.frame)
  phEl.value.style.left = p + '%'
  phEl.value.style.display = p < 0 || p > 100 ? 'none' : 'block'
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('keydown', cancelDrag, true)
  window.removeEventListener('blur', onWindowBlur)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  ro?.disconnect()
  offPh?.()
})

function done() {
  const c = clip.value
  if (c && changed.value) ui.toast(`片段 ${padIndex(c.display_index)} 已调整为 ${((c.end_frame - c.start_frame) / fps.value).toFixed(2)} 秒`, { tone: 'success' })
  emit('done')
}
const dragLabel = computed(() => {
  const g = drag.value
  if (!g || g.kind === 'scrub') return null
  const name = { start: '开头', end: '结尾', slide: '平移', cover: '封面', scrub: '' }[g.kind]
  const f = g.kind === 'end' ? end.value : g.kind === 'cover' ? coverF.value : start.value
  return `${name} ${tcode(f)} · #${f}${g.snapped ? ' · 吸附播放头' : ''}`
})
</script>

<template>
  <div v-if="clip && project" class="t">
    <div class="t-head">
      <slot name="lead" />
      <b class="t-name truncate">{{ padIndex(clip.display_index) }} {{ clipDisplayName(clip) }}</b>
      <span class="t-dur num"><template v-if="changed && entry">{{ ((entry.end - entry.start) / fps).toFixed(2) }}s → </template><b>{{ ((end - start) / fps).toFixed(2) }} 秒</b> · {{ end - start }} 帧</span>
      <TransitionGroup name="t-chip" tag="span" class="t-chips">
        <em v-if="headDelta" key="h" :class="headDelta > 0 ? 'up' : 'down'">开头 {{ fmtDelta(headDelta) }}</em>
        <em v-if="tailDelta" key="t" :class="tailDelta > 0 ? 'up' : 'down'">结尾 {{ fmtDelta(tailDelta) }}</em>
      </TransitionGroup>
      <span v-if="busy" class="t-busy small"><UiSpinner :size="10" /> 等待确认</span>
      <span class="grow"></span>
      <button type="button" class="t-ib" :disabled="!project.history.can_undo" :aria-label="project.history.can_undo ? `撤销：${project.history.undo_label}` : '撤销'" v-tip="{ text: project.history.can_undo ? `撤销：${project.history.undo_label}` : '没有可撤销的操作', kbd: 'Ctrl+Z' }" @click="session.undo()"><Undo2 :size="15" /></button>
      <button type="button" class="t-ib" :disabled="!project.history.can_redo" :aria-label="project.history.can_redo ? `重做：${project.history.redo_label}` : '重做'" v-tip="{ text: project.history.can_redo ? `重做：${project.history.redo_label}` : '没有可重做的操作', kbd: 'Ctrl+Shift+Z' }" @click="session.redo()"><Redo2 :size="15" /></button>
      <button type="button" class="t-btn t-btn--ghost" :disabled="!changed || busy" @click="resetClip"><RotateCcw :size="14" /> 恢复进入时长度</button>
      <button type="button" class="t-done" @click="done"><Check :size="15" :stroke-width="2.8" /> 完成</button>
    </div>

    <div class="t-tools" role="toolbar" aria-label="剪辑工具">
      <div class="t-seg" role="radiogroup" aria-label="编辑方式">
        <span class="t-seg__pill" :style="{ transform: `translateX(${mode === 'trim' ? 0 : 100}%)` }"></span>
        <button type="button" role="radio" :aria-checked="mode === 'trim'" v-tip="'单独拖动开头或结尾'" @click="mode = 'trim'"><ArrowLeftToLine :size="13" /> 修剪</button>
        <button type="button" role="radio" :aria-checked="mode === 'slide'" :disabled="!prev || !next" v-tip="'保持时长，整段在前后片段之间平移'" @click="mode = 'slide'"><MoveHorizontal :size="13" /> 滑动</button>
      </div>
      <span class="t-sep"></span>
      <button type="button" class="t-tool" :disabled="!leftCut || busy" v-tip="{ text: '把开头设到播放头', kbd: 'I' }" @click="setStart(playhead.frame)"><SquareArrowRight :size="14" /> 开头到这里</button>
      <button type="button" class="t-tool" :disabled="!rightCut || busy" v-tip="{ text: '把结尾设到播放头所在帧之后', kbd: 'O' }" @click="setEnd(playhead.frame + 1)"><SquareArrowLeft :size="14" /> 结尾到这里</button>
      <button type="button" class="t-tool" :disabled="busy" v-tip="{ text: '在播放头处拆分，新片段继承音频设置', kbd: 'C' }" @click="split"><Scissors :size="14" /> 拆分</button>
      <span class="t-sep"></span>
      <button type="button" class="t-tool" :disabled="!leftCut || busy" v-tip="'删除开头切点，与前一段合并'" @click="leftCut && actions.removeCut(leftCut.cut_id)"><ChevronsLeft :size="14" /> 并入前段</button>
      <button type="button" class="t-tool" :disabled="!rightCut || busy" v-tip="'删除结尾切点，与后一段合并'" @click="rightCut && actions.removeCut(rightCut.cut_id)">并入后段 <ChevronsRight :size="14" /></button>
      <span class="t-sep"></span>
      <button type="button" class="t-tool" :disabled="busy" v-tip="'把封面设为播放头所在帧'" @click="setCoverHere"><Image :size="14" /> 设为封面</button>
      <button
        type="button"
        class="t-tool"
        :class="{ on: clip.audio === 'muted' }"
        :disabled="!session.hasAudio.value || busy"
        v-tip="!session.hasAudio.value ? '源视频无音轨' : clip.audio === 'muted' ? '恢复原声' : '本段导出时静音'"
        @click="toggleMute"
      >
        <VolumeX v-if="clip.audio === 'muted' || !session.hasAudio.value" :size="14" /><Volume2 v-else :size="14" /> {{ !session.hasAudio.value ? '无音轨' : clip.audio === 'muted' ? '已静音' : '原声' }}
      </button>
      <span class="grow"></span>
      <button type="button" class="t-tool" :class="{ on: snapPlayhead }" :aria-pressed="snapPlayhead" v-tip="'拖动把手时吸附到播放头'" @click="snapPlayhead = !snapPlayhead"><Magnet :size="13" /> 吸附</button>
      <span class="t-sep"></span>
      <button type="button" class="t-ib" aria-label="缩小" :disabled="view.state.trimZoom <= 1" @click="view.state.trimZoom = Math.max(1, view.state.trimZoom / 1.4)"><Minus :size="14" /></button>
      <input v-model.number="view.state.trimZoom" class="t-zoom" type="range" min="1" max="16" step="0.1" aria-label="剪辑轨道缩放" />
      <button type="button" class="t-ib" aria-label="放大" :disabled="view.state.trimZoom >= 16" @click="view.state.trimZoom = Math.min(16, view.state.trimZoom * 1.4)"><Plus :size="14" /></button>
      <button type="button" class="t-ib" aria-label="适应本段" v-tip="'适应本段'" @click="fit"><Maximize2 :size="13" /></button>
    </div>

    <div class="t-ruler" @pointerdown="down('scrub', $event)" @pointermove="move" @pointerup="up">
      <span v-for="k in ticks" :key="k.f" class="t-tick" :class="{ major: !!k.label }" :style="{ left: pct(k.f) + '%' }"><i v-if="k.label" class="num">{{ k.label }}</i></span>
    </div>

    <div ref="trackEl" class="t-track" :class="{ dragging: drag && drag.kind !== 'scrub', slide: mode === 'slide' }" @pointermove="move" @pointerup="up" @pointercancel="cancelPointer" @lostpointercapture="cancelPointer" @wheel="onWheel">
      <div class="t-bg" @pointerdown="down('scrub', $event)"></div>
      <div v-for="o in others" :key="o.c.clip_id" class="t-nb" :class="{ adj: o.adj }" :style="{ left: o.left + '%', width: o.width + '%' }">
        <FrameImage :project-id="project.project_id" :frame="o.c.cover.frame" size="thumb" alt="" :show-state="false" />
        <span v-if="(o.width / 100) * width > 74" :class="{ r: o.right }">{{ padIndex(o.c.display_index) }} · {{ ((o.c.end_frame - o.c.start_frame) / fps).toFixed(2) }}s</span>
      </div>
      <div class="t-cur" :class="{ dragging: drag?.kind === 'slide' }" :style="{ left: pct(start) + '%', width: pct(end) - pct(start) + '%' }" @pointerdown.self="down('slide', $event)">
        <div class="t-strip" aria-hidden="true">
          <FrameImage v-for="f in tiles" :key="f" :project-id="project.project_id" :frame="f" size="thumb" alt="" :show-state="false" />
        </div>
        <div class="t-cur__hit" @pointerdown="down('slide', $event)"></div>
        <button
          type="button"
          class="t-handle t-handle--s"
          :class="{ active: drag?.kind === 'start' }"
          :disabled="!leftCut || mode === 'slide'"
          :aria-label="leftCut ? '开头把手：拖动，或用 ←/→ 逐帧（Shift 10 帧）' : '视频开头，不能再向前'"
          @pointerdown.stop="down('start', $event)"
          @keydown="onHandleKey('start', $event)"
        ><i></i><i></i></button>
        <span class="t-len num"><b>{{ ((end - start) / fps).toFixed(2) }}</b> 秒<template v-if="mode === 'slide'"> · 拖动整段平移</template></span>
        <button
          type="button"
          class="t-cover"
          :class="{ active: drag?.kind === 'cover', out: clip.cover.status === 'out_of_range' }"
          :style="{ left: ((coverF - start) / Math.max(1, end - start)) * 100 + '%' }"
          :aria-label="`封面 ${tcode(coverF)}，拖动调整`"
          v-tip="clip.cover.status === 'out_of_range' ? '封面已不在本段范围内，拖动或「设为封面」重新选择' : `封面 ${tcode(coverF)}（${clip.cover.origin === 'auto' ? '自动' : '手动'}）`"
          @pointerdown.stop="down('cover', $event)"
        ><Image :size="10" :stroke-width="2.5" /></button>
        <button
          type="button"
          class="t-handle t-handle--e"
          :class="{ active: drag?.kind === 'end' }"
          :disabled="!rightCut || mode === 'slide'"
          :aria-label="rightCut ? '结尾把手：拖动，或用 ←/→ 逐帧（Shift 10 帧）' : '视频结尾，不能再向后'"
          @pointerdown.stop="down('end', $event)"
          @keydown="onHandleKey('end', $event)"
        ><i></i><i></i></button>
        <span v-if="dragLabel" class="t-tip num">{{ dragLabel }}</span>
      </div>
      <div ref="phEl" class="t-ph" aria-hidden="true"></div>
    </div>

    <div class="t-foot">
      <button type="button" class="t-play" aria-label="播放本段" v-tip="'播放本段'" @click="playhead.requestPlay({ from: start, to: end - 1 })"><Play :size="13" fill="currentColor" /></button>
      <button type="button" class="t-tool" :disabled="!leftCut" v-tip="'播放开头切点前后各 1 秒'" @click="playhead.requestPlay({ from: Math.max(0, start - Math.round(fps)), to: Math.min(fc - 1, start + Math.round(fps)) })">试看开头</button>
      <button type="button" class="t-tool" :disabled="!rightCut" v-tip="'播放结尾切点前后各 1 秒'" @click="playhead.requestPlay({ from: Math.max(0, end - Math.round(fps)), to: Math.min(fc - 1, end + Math.round(fps)) })">试看结尾</button>
      <span class="t-sep"></span>
      <label class="t-field" :class="{ bad: bad.start }">开头
        <button type="button" :disabled="!leftCut || busy" aria-label="开头提前 1 帧" @click="setStart(start - 1)"><ChevronLeft :size="13" /></button>
        <input v-model="fields.start" class="num" :disabled="!leftCut" aria-label="开头时间（mm:ss.mmm 或 #帧号）" @keydown.enter="applyField('start')" @blur="applyField('start')" />
        <button type="button" :disabled="!leftCut || busy" aria-label="开头推后 1 帧" @click="setStart(start + 1)"><ChevronRight :size="13" /></button>
      </label>
      <label class="t-field" :class="{ bad: bad.end }">结尾
        <button type="button" :disabled="!rightCut || busy" aria-label="结尾提前 1 帧" @click="setEnd(end - 1)"><ChevronLeft :size="13" /></button>
        <input v-model="fields.end" class="num" :disabled="!rightCut" aria-label="结尾时间（不含该帧）" @keydown.enter="applyField('end')" @blur="applyField('end')" />
        <button type="button" :disabled="!rightCut || busy" aria-label="结尾推后 1 帧" @click="setEnd(end + 1)"><ChevronRight :size="13" /></button>
      </label>
      <label class="t-field t-field--dur" :class="{ bad: bad.dur }">时长
        <input v-model="fields.dur" class="num" :disabled="!rightCut" aria-label="时长（秒）" @keydown.enter="applyField('dur')" @blur="applyField('dur')" /><span>秒</span>
      </label>
      <span class="grow"></span>
      <span class="t-hint">滚轮平移 · Ctrl+滚轮缩放 · 移动切点时相邻片段同步变化，帧连续不丢失</span>
    </div>
  </div>
  <div v-else class="t-empty small muted">先在卡片或列表中选择一个片段。</div>
</template>

<style scoped>
.t {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 14px 10px;
}
.t-empty {
  padding: 24px;
}
.grow {
  flex: 1;
}
.t-head,
.t-tools,
.t-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: none;
}
.t-head {
  gap: 10px;
  height: 34px;
}
.t-name {
  font-size: var(--fs-14);
  max-width: 220px;
}
.t-dur {
  font-size: var(--fs-12);
  color: var(--text-3);
  white-space: nowrap;
}
.t-dur b {
  color: var(--text-1);
}
.t-chips {
  display: inline-flex;
  gap: 6px;
}
.t-chips em {
  font-style: normal;
  font-size: 11.5px;
  font-weight: var(--fw-semibold);
  padding: 2px 8px;
  border-radius: 8px;
  font-family: var(--font-mono);
  white-space: nowrap;
}
.t-chips em.up {
  color: var(--success);
  background: var(--success-soft);
}
.t-chips em.down {
  color: var(--warning);
  background: var(--warning-soft);
}
.t-chip-enter-active,
.t-chip-leave-active {
  transition: all var(--dur-spring) var(--ease-spring);
}
.t-chip-enter-from,
.t-chip-leave-to {
  opacity: 0;
  transform: scale(0.6);
}
.t-busy {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-2);
}
.t-ib {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--text-2);
  flex: none;
  transition:
    background-color var(--dur-press),
    transform var(--dur-spring) var(--ease-spring);
}
.t-ib:hover:not(:disabled) {
  background: var(--bg-control);
  color: var(--text-1);
}
.t-ib:active:not(:disabled) {
  transform: scale(0.85);
}
button:disabled {
  opacity: 0.32;
  cursor: not-allowed;
}
.t-btn {
  height: 30px;
  padding: 0 11px;
  border-radius: 9px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-12);
  font-weight: var(--fw-semibold);
  background: var(--bg-control);
  color: var(--text-1);
  white-space: nowrap;
  transition:
    transform var(--dur-spring) var(--ease-spring),
    background-color var(--dur-press);
}
.t-btn:hover:not(:disabled) {
  background: var(--bg-control-hover);
}
.t-btn--ghost {
  background: transparent;
  color: var(--text-2);
}
.t-done {
  height: 32px;
  padding: 0 14px;
  border-radius: var(--r-2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: var(--fw-bold);
  background: var(--primary);
  color: var(--primary-text);
  transition: transform var(--dur-spring) var(--ease-spring);
}
.t-done:active {
  transform: scale(0.93);
}
.t-tools {
  height: 32px;
  gap: 4px;
  overflow-x: auto;
  scrollbar-width: none;
}
.t-sep {
  width: 1px;
  height: 16px;
  background: var(--line);
  margin: 0 4px;
  flex: none;
}
.t-tool {
  height: 28px;
  padding: 0 9px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-12);
  color: var(--text-2);
  white-space: nowrap;
  flex: none;
  transition:
    background-color var(--dur-press),
    color var(--dur-press),
    transform var(--dur-spring) var(--ease-spring);
}
.t-tool:hover:not(:disabled) {
  background: var(--bg-control);
  color: var(--text-1);
}
.t-tool:active:not(:disabled) {
  transform: scale(0.93);
}
.t-tool.on {
  background: var(--accent-soft);
  color: var(--accent-hover);
}
.t-seg {
  position: relative;
  display: inline-flex;
  padding: 2px;
  border-radius: 9px;
  background: var(--bg-well);
  box-shadow: inset 0 0 0 1px var(--line);
  flex: none;
}
.t-seg button {
  position: relative;
  z-index: 1;
  width: 70px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-size: var(--fs-12);
  font-weight: var(--fw-semibold);
  color: var(--text-2);
  transition: color var(--dur-select);
}
.t-seg button[aria-checked='true'] {
  color: var(--text-on-accent);
}
.t-seg__pill {
  position: absolute;
  top: 2px;
  bottom: 2px;
  left: 2px;
  width: 70px;
  border-radius: 7px;
  background: var(--accent);
  transition: transform var(--dur-spring) var(--ease-spring);
}
.t-zoom {
  width: 80px;
  accent-color: var(--text-2);
  flex: none;
}
.t-ruler {
  position: relative;
  height: 18px;
  flex: none;
  cursor: text;
}
.t-tick {
  position: absolute;
  bottom: 0;
  width: 1px;
  height: 4px;
  background: rgba(255, 255, 255, 0.18);
}
.t-tick.major {
  height: 8px;
  background: rgba(255, 255, 255, 0.35);
}
.t-tick i {
  position: absolute;
  bottom: 9px;
  left: 3px;
  font-style: normal;
  font-size: 10.5px;
  color: var(--text-3);
  white-space: nowrap;
}
.t-track {
  position: relative;
  flex: 1;
  min-height: 64px;
  border-radius: var(--r-3);
  background: var(--bg-well);
  overflow: hidden;
}
.t-track.dragging {
  cursor: ew-resize;
}
.t-bg {
  position: absolute;
  inset: 0;
  cursor: text;
}
.t-nb {
  position: absolute;
  top: 12px;
  bottom: 12px;
  border-radius: 6px;
  overflow: hidden;
  pointer-events: none;
  box-shadow: inset -2px 0 0 var(--bg-well);
}
.t-nb :deep(.frame) {
  width: 100%;
  height: 100%;
  filter: grayscale(0.7) brightness(0.3);
}
.t-nb.adj :deep(.frame) {
  filter: grayscale(0.5) brightness(0.45);
}
.t-nb span {
  position: absolute;
  left: 8px;
  bottom: 6px;
  font-size: 11px;
  color: #ddd;
  white-space: nowrap;
}
.t-nb span.r {
  left: auto;
  right: 8px;
}
.t-cur {
  position: absolute;
  top: 4px;
  bottom: 4px;
  border-radius: 10px;
  z-index: 1;
  overflow: visible;
}
.t-strip {
  position: absolute;
  inset: 0;
  display: flex;
  border-radius: 10px;
  overflow: hidden;
  pointer-events: none;
}
.t-strip :deep(.frame) {
  flex: 1;
  min-width: 0;
  height: 100%;
}
.t-cur::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 10px;
  box-shadow: inset 0 0 0 3px var(--accent);
  pointer-events: none;
}
.t-cur__hit {
  position: absolute;
  inset: 0;
  cursor: text;
}
.t-track.slide .t-cur__hit {
  cursor: grab;
}
.t-track.slide .t-cur.dragging .t-cur__hit {
  cursor: grabbing;
}
.t-len {
  position: absolute;
  left: 50%;
  top: 7px;
  transform: translateX(-50%);
  padding: 2px 10px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.78);
  font-size: var(--fs-12);
  white-space: nowrap;
  pointer-events: none;
  z-index: 2;
}
.t-tip {
  position: absolute;
  bottom: 7px;
  left: 50%;
  transform: translateX(-50%);
  padding: 2px 8px;
  border-radius: 7px;
  background: var(--accent);
  color: var(--text-on-accent);
  font-size: 11.5px;
  font-weight: var(--fw-bold);
  white-space: nowrap;
  pointer-events: none;
  z-index: 3;
}
.t-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  background: var(--accent);
  cursor: ew-resize;
  touch-action: none;
  z-index: 3;
  transition:
    width var(--dur-select) var(--ease-spring),
    background-color var(--dur-press);
}
.t-handle--s {
  left: 0;
  border-radius: 10px 0 0 10px;
}
.t-handle--e {
  right: 0;
  border-radius: 0 10px 10px 0;
}
.t-handle i {
  width: 2px;
  height: 18px;
  border-radius: 1px;
  background: rgba(0, 0, 0, 0.55);
}
.t-handle:hover:not(:disabled),
.t-handle.active {
  width: 22px;
  background: var(--accent-hover);
}
.t-handle:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}
.t-handle:disabled {
  background: #3a3a3a;
  width: 10px;
  opacity: 1;
}
.t-handle:disabled i {
  display: none;
}
.t-cover {
  position: absolute;
  top: -1px;
  width: 20px;
  height: 20px;
  margin-left: -10px;
  border-radius: 0 0 8px 8px;
  display: grid;
  place-items: center;
  background: var(--primary);
  color: var(--primary-text);
  cursor: ew-resize;
  touch-action: none;
  z-index: 3;
  transition: transform var(--dur-spring) var(--ease-spring);
}
.t-cover.out {
  background: var(--warning);
}
.t-cover:hover,
.t-cover.active {
  transform: scaleY(1.15);
}
.t-ph {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  margin-left: -1px;
  background: var(--playhead);
  z-index: 4;
  pointer-events: none;
}
.t-foot {
  height: 32px;
  gap: 6px;
  font-size: var(--fs-12);
  color: var(--text-3);
}
.t-play {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--primary);
  color: var(--primary-text);
  flex: none;
  transition: transform var(--dur-spring) var(--ease-spring);
}
.t-play:active {
  transform: scale(0.85);
}
.t-field {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  white-space: nowrap;
}
.t-field input {
  width: 82px;
  height: 26px;
  border: 0;
  border-radius: 7px;
  background: var(--bg-control);
  color: var(--text-1);
  font-size: var(--fs-12);
  text-align: center;
  transition: box-shadow var(--dur-press);
}
.t-field--dur input {
  width: 54px;
}
.t-field input:focus {
  outline: none;
  box-shadow: 0 0 0 1.5px var(--accent);
}
.t-field.bad input {
  box-shadow: 0 0 0 1.5px var(--danger);
  animation: t-shake 0.4s;
}
@keyframes t-shake {
  25% {
    transform: translateX(-3px);
  }
  75% {
    transform: translateX(3px);
  }
}
.t-field button {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  color: var(--text-2);
  transition:
    background-color var(--dur-press),
    transform var(--dur-spring) var(--ease-spring);
}
.t-field button:hover:not(:disabled) {
  background: var(--bg-control);
  color: var(--text-1);
}
.t-field button:active:not(:disabled) {
  transform: scale(0.8);
}
.t-hint {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
</style>
