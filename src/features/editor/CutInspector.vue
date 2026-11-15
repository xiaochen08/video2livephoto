<script setup lang="ts">
import { Check, ChevronLeft, ChevronRight, Eye, Trash2 } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useActions, useApp } from '@/app/context'
import ParamRow from '@/components/ParamRow.vue'
import StatusTag from '@/components/StatusTag.vue'
import UiButton from '@/components/UiButton.vue'
import UiTextField from '@/components/UiTextField.vue'
import { CUT_KIND_EXPLAIN, CUT_KIND_LABEL } from '@/domain/clipHints'
import { formatDurationShort, formatTime, framesToUs, frameToUs } from '@/domain/time'
import type { Cut } from '@/domain/types'
import InspectorSection from './InspectorSection.vue'

const props = defineProps<{ cut: Cut; reviewMode?: boolean }>()
const { session, ui, playhead } = useApp()
const actions = useActions()
const t = session.timeline
const s = computed(() => session.stream.value!)
const i = computed(() => t.value!.cuts.findIndex((c) => c.cut_id === props.cut.cut_id))
const left = computed(() => t.value!.clips[i.value])
const right = computed(() => t.value!.clips[i.value + 1])
const frameInput = ref(String(props.cut.frame))
watch(
  () => props.cut.frame,
  (f) => (frameInput.value = String(f)),
)
const frameError = computed(() => {
  const v = Number(frameInput.value)
  if (!Number.isInteger(v)) return '请输入整数帧号'
  if (v <= left.value.start_frame || v >= right.value.end_frame) return `可移动范围 #${left.value.start_frame + 1} – #${right.value.end_frame - 1}`
  return null
})

async function move(frame: number) {
  if (frame === props.cut.frame) return
  try {
    await session.edit({ type: 'move_cut', cut_id: props.cut.cut_id, frame })
    playhead.requestSeek(frame)
  } catch (e) {
    ui.toast((e as Error).message, { tone: 'danger', timeout: 6000 })
  }
}
async function confirm() {
  try {
    await session.edit({ type: 'review_cut', cut_id: props.cut.cut_id, action: 'confirm' })
  } catch (e) {
    ui.toast((e as Error).message, { tone: 'danger' })
  }
}
</script>

<template>
  <div class="cut-i">
    <InspectorSection :title="`切点 #${cut.frame}`">
      <template #aside><span class="small muted mono">{{ cut.cut_id }}</span></template>
      <div class="cut-i__tags">
        <StatusTag :label="CUT_KIND_LABEL[cut.kind]" tone="neutral" size="sm" />
        <StatusTag v-if="cut.review === 'pending'" :label="cut.skipped ? '已跳过 · 仍待检查' : '待检查'" tone="warning" icon="dot" size="sm" />
        <StatusTag v-else :label="cut.confirmed_by === 'user' ? '已确认' : '清晰切换（分析判定）'" tone="success" icon="check" size="sm" />
        <StatusTag v-if="cut.origin === 'user'" label="手动添加" tone="muted" size="sm" />
      </div>
      <dl class="cut-i__dl">
        <ParamRow label="位置" mono>{{ formatTime(frameToUs(cut.frame, s)) }} <span class="muted">#{{ cut.frame }}</span></ParamRow>
        <ParamRow label="PTS" :value="cut.pts ?? '待后端补充'" mono />
        <ParamRow v-if="cut.transition" label="过渡范围" mono>#{{ cut.transition.start_frame }} – #{{ cut.transition.end_frame - 1 }}（{{ cut.transition.end_frame - cut.transition.start_frame }} 帧）</ParamRow>
        <ParamRow label="置信信息" :value="cut.confidence === null ? '分析未提供置信分数（建议检查）' : cut.confidence.toFixed(2)" />
        <ParamRow label="两侧时长" mono>{{ formatDurationShort(framesToUs(left.end_frame - left.start_frame, s.frame_rate)) }} | {{ formatDurationShort(framesToUs(right.end_frame - right.start_frame, s.frame_rate)) }}</ParamRow>
      </dl>
      <p v-if="cut.reason" class="small cut-i__reason">{{ cut.reason }}</p>
      <p class="small muted">{{ CUT_KIND_EXPLAIN[cut.kind] }}</p>
    </InspectorSection>

    <InspectorSection title="调整位置">
      <div class="cut-i__nudge">
        <UiButton size="sm" :icon="ChevronLeft" :disabled="cut.frame - 1 <= left.start_frame" disabled-reason="左侧片段至少保留 1 帧" @click="move(cut.frame - 1)">前移 1 帧</UiButton>
        <UiButton size="sm" :icon-right="ChevronRight" :disabled="cut.frame + 1 >= right.end_frame" disabled-reason="右侧片段至少保留 1 帧" @click="move(cut.frame + 1)">后移 1 帧</UiButton>
      </div>
      <UiTextField v-model="frameInput" label="移动到帧号" mono size="sm" :error="frameError" @commit="!frameError && move(Number(frameInput))" />
      <p class="small muted">也可以在时间线上拖动，或选中后按 Alt+←/→。最终位置由后端时间线核心确认。</p>
    </InspectorSection>

    <InspectorSection title="操作">
      <div class="cut-i__btns">
        <UiButton v-if="cut.review === 'pending'" size="sm" variant="primary" :icon="Check" @click="confirm">确认此切点</UiButton>
        <UiButton v-if="!reviewMode" size="sm" :icon="Eye" @click="actions.startReview(cut.cut_id)">在检查区查看</UiButton>
        <UiButton size="sm" variant="danger-ghost" :icon="Trash2" kbd="Delete" @click="actions.removeCut(cut.cut_id)">删除切点</UiButton>
      </div>
      <p class="small muted">删除切点 = 合并相邻两个片段，画面不会丢失，可撤销。</p>
    </InspectorSection>
  </div>
</template>

<style scoped>
.cut-i__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.cut-i__dl {
  display: grid;
  gap: 2px;
}
.cut-i__reason {
  padding: 6px 8px;
  border-left: 2px solid var(--review);
  background: var(--warning-soft);
  color: var(--text-1);
  border-radius: 0 var(--r-1) var(--r-1) 0;
}
.cut-i__nudge,
.cut-i__btns {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
