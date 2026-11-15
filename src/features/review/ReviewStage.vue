<script setup lang="ts">
import { Check, CheckCheck, ChevronLeft, ChevronRight, CircleCheckBig, Play, SkipForward, Undo2, Upload } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useActions, useApp } from '@/app/context'
import EmptyState from '@/components/EmptyState.vue'
import FrameImage from '@/components/FrameImage.vue'
import StatusTag from '@/components/StatusTag.vue'
import UiButton from '@/components/UiButton.vue'
import { CUT_KIND_EXPLAIN, CUT_KIND_LABEL } from '@/domain/clipHints'
import { formatTime, frameToUs } from '@/domain/time'

const { session, view, ui, playhead, selection } = useApp()
const actions = useActions()
const t = session.timeline
const cut = computed(() => t.value?.cuts.find((c) => c.cut_id === view.state.reviewCutId) ?? null)
const pending = session.pendingCuts
const position = computed(() => (cut.value ? pending.value.findIndex((c) => c.cut_id === cut.value!.cut_id) : -1))
const project = session.project
const s = session.stream
const portrait = computed(() => !!s.value && s.value.height > s.value.width)
const transFrames = computed(() => {
  const tr = cut.value?.transition
  if (!tr) return []
  const n = tr.end_frame - tr.start_frame
  const step = Math.max(1, Math.ceil(n / 12))
  const out: number[] = []
  for (let f = tr.start_frame; f < tr.end_frame; f += step) out.push(f)
  return out
})
const done = computed(() => pending.value.length === 0)
const busy = computed(() => !!session.state.pending)

function nextPending(afterFrame: number) {
  return pending.value.find((c) => c.frame > afterFrame && c.cut_id !== cut.value?.cut_id) ?? pending.value.find((c) => c.cut_id !== cut.value?.cut_id) ?? null
}

async function review(action: 'confirm' | 'skip', advance: boolean) {
  const c = cut.value
  if (!c) return
  try {
    await session.edit({ type: 'review_cut', cut_id: c.cut_id, action })
    if (advance) {
      const n = nextPending(c.frame)
      if (n) {
        view.state.reviewCutId = n.cut_id
        playhead.requestSeek(n.frame)
      }
    }
  } catch (e) {
    ui.toast((e as Error).message, { tone: 'danger' })
  }
}
async function nudge(d: number) {
  const c = cut.value
  if (!c) return
  try {
    await session.edit({ type: 'move_cut', cut_id: c.cut_id, frame: c.frame + d })
  } catch (e) {
    ui.toast((e as Error).message, { tone: 'danger', timeout: 6000 })
  }
}
function playAround() {
  const c = cut.value
  if (!c || !s.value) return
  const sec = Math.round(s.value.frame_rate.num / s.value.frame_rate.den)
  ui.state.editorMode = 'edit'
  setTimeout(() => playhead.requestPlay({ from: Math.max(0, c.frame - sec), to: Math.min(t.value!.frame_count - 1, c.frame + sec) }), 60)
}
function backToTimeline() {
  const c = cut.value
  ui.state.editorMode = 'edit'
  if (!c) return
  const i = t.value!.cuts.indexOf(c)
  actions.focusClip(t.value!.clips[i + 1].clip_id, false)
  // keep the cut selected so Delete / Alt+arrows act on it, and show it in the inspector
  selection.selectCut(c.cut_id)
  setTimeout(() => playhead.requestSeek(c.frame), 60)
}
const stripStep = computed(() => (cut.value?.transition ? Math.max(1, Math.ceil((cut.value.transition.end_frame - cut.value.transition.start_frame) / 12)) : 1))

function onKey(e: KeyboardEvent) {
  if (e.isComposing || ui.state.overlays.length || ui.state.editorMode !== 'review') return
  const tg = e.target as HTMLElement
  if (tg && (tg.tagName === 'INPUT' || tg.tagName === 'TEXTAREA' || tg.isContentEditable)) return
  if (e.key === 'Enter' && !e.ctrlKey && !(tg?.tagName === 'BUTTON')) {
    e.preventDefault()
    if (cut.value?.review === 'pending') void review('confirm', true)
  } else if ((e.key === 's' || e.key === 'S') && !e.ctrlKey && !e.metaKey) {
    e.preventDefault()
    if (cut.value?.review === 'pending') void review('skip', true)
  }
}
onMounted(() => {
  window.addEventListener('keydown', onKey)
  if (!cut.value) view.state.reviewCutId = pending.value[0]?.cut_id ?? t.value?.cuts[0]?.cut_id ?? null
  if (cut.value) playhead.requestSeek(cut.value.frame)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
watch(
  () => t.value?.cuts.map((c) => c.cut_id).join(','),
  () => {
    if (view.state.reviewCutId && !cut.value) view.state.reviewCutId = pending.value[0]?.cut_id ?? null
  },
)
</script>

<template>
  <div class="rstage">
    <div v-if="done && (!cut || cut.review !== 'pending')" class="rstage__done" role="status">
      <EmptyState :icon="CircleCheckBig" title="切点检查完成">
        全部 {{ t?.cuts.length ?? 0 }} 个切点都已确认或判定为清晰切换。可以返回编辑，或直接确认导出。
        <template #actions>
          <UiButton :icon="Undo2" @click="ui.state.editorMode = 'edit'">返回编辑</UiButton>
          <UiButton variant="primary" :icon="Upload" @click="actions.openExport()">确认导出…</UiButton>
        </template>
      </EmptyState>
    </div>
    <template v-else-if="cut && project && s">
      <header class="rstage__head">
        <div class="rstage__meta">
          <StatusTag :label="CUT_KIND_LABEL[cut.kind]" size="sm" />
          <StatusTag v-if="cut.review === 'pending'" :label="cut.skipped ? '已跳过 · 仍待检查' : '待检查'" tone="warning" icon="dot" size="sm" />
          <StatusTag v-else label="已确认" tone="success" icon="check" size="sm" />
          <span class="small secondary num">
            切点 <span class="mono">#{{ cut.frame }}</span> · {{ formatTime(frameToUs(cut.frame, s)) }}
            <template v-if="position >= 0"> · 第 {{ position + 1 }} / {{ pending.length }} 处待检查</template>
          </span>
        </div>
        <p class="small rstage__reason">
          {{ cut.reason ?? CUT_KIND_EXPLAIN[cut.kind] }}
          <span class="muted"> · {{ cut.confidence === null ? '分析未提供置信分数' : `置信 ${cut.confidence.toFixed(2)}` }}</span>
        </p>
      </header>

      <div class="rstage__pair" :class="{ 'is-portrait': portrait }">
        <figure class="rframe">
          <FrameImage :project-id="project.project_id" :frame="cut.frame - 1" size="full" fit="contain" :lazy="false" :alt="`前一段最后一帧 #${cut.frame - 1}`" />
          <figcaption class="small">
            <span>前一段最后一帧</span><span class="mono num">#{{ cut.frame - 1 }} · {{ formatTime(frameToUs(cut.frame - 1, s)) }}</span>
          </figcaption>
        </figure>
        <div class="rstage__divider" aria-hidden="true"><span>切点</span></div>
        <figure class="rframe">
          <FrameImage :project-id="project.project_id" :frame="cut.frame" size="full" fit="contain" :lazy="false" :alt="`后一段第一帧 #${cut.frame}`" />
          <figcaption class="small">
            <span>后一段第一帧</span><span class="mono num">#{{ cut.frame }} · {{ formatTime(frameToUs(cut.frame, s)) }}</span>
          </figcaption>
        </figure>
      </div>

      <div v-if="transFrames.length" class="rstage__trans">
        <p class="small muted">叠化过渡 #{{ cut.transition!.start_frame }}–#{{ cut.transition!.end_frame - 1 }}：已合成的过渡画面全部保留在两侧片段中，不做修改。</p>
        <div class="rstage__strip">
          <div v-for="f in transFrames" :key="f" class="rstage__sf" :class="{ 'is-cut': f <= cut.frame && f + stripStep > cut.frame }">
            <FrameImage :project-id="project.project_id" :frame="f" size="thumb" alt="" />
            <span class="mono">#{{ f }}</span>
          </div>
        </div>
      </div>

      <div class="rstage__controls" role="toolbar" aria-label="切点检查操作">
        <div class="row">
          <UiButton size="sm" :icon="ChevronLeft" :disabled="busy" disabled-reason="正在应用上一项修改" @click="nudge(-1)">切点前移 1 帧</UiButton>
          <UiButton size="sm" :icon-right="ChevronRight" :disabled="busy" disabled-reason="正在应用上一项修改" @click="nudge(1)">切点后移 1 帧</UiButton>
          <UiButton size="sm" variant="ghost" :icon="Play" @click="playAround">播放切点前后 1 秒</UiButton>
          <UiButton size="sm" variant="ghost" @click="backToTimeline">回到时间线</UiButton>
        </div>
        <div class="row">
          <UiButton v-if="cut.review === 'pending'" :icon="SkipForward" kbd="S" @click="review('skip', true)">暂时跳过</UiButton>
          <UiButton v-if="cut.review === 'pending'" :icon="Check" @click="review('confirm', false)">确认</UiButton>
          <UiButton v-if="cut.review === 'pending'" variant="primary" :icon="CheckCheck" kbd="Enter" @click="review('confirm', true)">
            {{ pending.length > 1 ? '确认并下一处' : '确认（最后一处）' }}
          </UiButton>
          <span v-else class="small muted">此切点已确认。可在左侧选择其他切点。</span>
        </div>
      </div>
    </template>
    <EmptyState v-else title="没有可检查的切点">此视频没有切点，整条视频作为 1 个片段。可在编辑页添加切点。</EmptyState>
  </div>
</template>

<style scoped>
.rstage {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 12px 16px;
  gap: 12px;
  min-height: 0;
  overflow-y: auto;
}
.rstage__done {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.rstage__head {
  display: grid;
  gap: 6px;
}
.rstage__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.rstage__reason {
  color: var(--text-2);
}
.rstage__pair {
  flex: 1;
  min-height: 160px;
  display: grid;
  grid-template-columns: 1fr 28px 1fr;
  gap: 0;
  align-items: stretch;
}
.rframe {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
  min-width: 0;
}
.rframe :deep(.frame) {
  flex: 1;
  min-height: 0;
  border-radius: var(--r-1);
}
.rframe figcaption {
  display: flex;
  justify-content: space-between;
  color: var(--text-2);
}
.rstage__divider {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}
.rstage__divider::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 24px;
  left: 50%;
  width: 2px;
  background: var(--review);
  opacity: 0.6;
}
.rstage__divider span {
  position: relative;
  writing-mode: vertical-rl;
  font-size: var(--fs-11);
  color: var(--review);
  background: var(--bg-well);
  padding: 4px 0;
}
.rstage__trans {
  display: grid;
  gap: 6px;
}
.rstage__strip {
  display: flex;
  gap: 4px;
  overflow-x: auto;
}
.rstage__sf {
  flex: none;
  width: 84px;
  display: grid;
  gap: 2px;
  font-size: 10.5px;
  color: var(--text-3);
}
.rstage__sf :deep(.frame) {
  height: 47px;
  border-radius: 2px;
}
.rstage__sf.is-cut :deep(.frame) {
  box-shadow: 0 0 0 2px var(--review);
}
.rstage__controls {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 4px;
  border-top: 1px solid var(--line-subtle);
}
</style>
