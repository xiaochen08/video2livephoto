<script setup lang="ts">
import { Pause, Play, RotateCcw, Square, StepForward } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useApp } from '@/app/context'
import StatusTag from '@/components/StatusTag.vue'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import UiProgress from '@/components/UiProgress.vue'
import UiSegmented from '@/components/UiSegmented.vue'
import UiSelect from '@/components/UiSelect.vue'
import VirtualList from '@/components/VirtualList.vue'
import { toAppError } from '@/domain/errors'
import { requestId } from '@/domain/ids'
import { BATCH_STATE_LABEL, countBatch, isRunningStage } from '@/domain/jobStates'
import { padIndex } from '@/domain/naming'
import { formatClock } from '@/domain/time'
import type { Job } from '@/domain/types'
import JobRow from './JobRow.vue'
import { progressText } from './jobText'
import { useJobActions } from './useJobActions'

const emit = defineEmits<{ open: [string, string] }>()
const { tasks, ui, session, adapter } = useApp()
const ja = useJobActions()
const batchId = ref<string>(tasks.activeBatch.value?.batch_id ?? tasks.batches.value[0]?.batch_id ?? '')
watch(
  () => tasks.batches.value.map((b) => b.batch_id).join(','),
  () => {
    if (!tasks.state.batches[batchId.value]) batchId.value = tasks.activeBatch.value?.batch_id ?? tasks.batches.value[0]?.batch_id ?? ''
  },
)
watch(
  () => tasks.activeBatch.value?.batch_id,
  (id) => id && (batchId.value = id),
)
const batch = computed(() => tasks.state.batches[batchId.value] ?? null)
const counts = computed(() => (batch.value ? countBatch(batch.value) : null))
type F = 'all' | 'running' | 'failed' | 'succeeded' | 'other'
const filter = ref<F>('all')
const jobs = computed<Job[]>(() => {
  const b = batch.value
  if (!b) return []
  switch (filter.value) {
    case 'running':
      return b.jobs.filter((j) => isRunningStage(j.stage))
    case 'failed':
      return b.jobs.filter((j) => j.stage === 'failed')
    case 'succeeded':
      return b.jobs.filter((j) => j.stage === 'succeeded')
    case 'other':
      return b.jobs.filter((j) => !isRunningStage(j.stage) && j.stage !== 'failed' && j.stage !== 'succeeded')
    default:
      return b.jobs
  }
})
const running = computed(() => batch.value?.jobs.filter((j) => isRunningStage(j.stage)) ?? [])
const coverOf = (j: Job) => batch.value?.snapshot.clips.find((c) => c.clip_id === j.clip_id)?.cover_frame ?? 0
const editedSince = computed(() => {
  const b = batch.value
  const p = session.project.value
  return b && p ? b.jobs.filter((j) => session.outdated.value.has(j.clip_id)).length : 0
})
const batchOptions = computed(() =>
  tasks.batches.value.map((b) => ({ value: b.batch_id, label: `${formatClock(b.created_at)} · ${b.jobs.length} 个片段 · 快照 v${b.snapshot.edit_version} · ${BATCH_STATE_LABEL[b.state]}` })),
)
const canContinue = computed(() => batch.value && (batch.value.state === 'stopped' || batch.value.state === 'interrupted') && (counts.value!.skipped + counts.value!.interrupted + counts.value!.failed + counts.value!.commitUnknown) > 0)

async function act(kind: 'pause' | 'resume' | 'stop' | 'retry') {
  const b = batch.value
  if (!b) return
  try {
    if (kind === 'stop') {
      const ok = await ui.confirm({
        title: '停止整批导出？',
        message: '停止后不再领取后续片段。正在编码的片段会被终止并清理临时文件；正在校验或提交的片段会在安全位置结束。',
        detail: '已成功的文件保留，恢复记录会被保存，之后可以「继续剩余任务」。',
        confirmLabel: '停止整批',
        tone: 'danger',
      })
      if (!ok) return
      await tasks.stop(b.batch_id)
    } else if (kind === 'pause') await tasks.pause(b.batch_id)
    else if (kind === 'resume') await tasks.resume(b.batch_id)
    else {
      const r = await tasks.retryFailed(b.batch_id)
      if (r) ui.toast(`已重新排队 ${r.retried} 个失败片段；成功的文件保持不变。`)
    }
  } catch (e) {
    ui.toast(toAppError(e).message, { tone: 'danger' })
  }
}

async function continueRemaining() {
  const b = batch.value
  const p = session.project.value
  if (!b || !p) return
  if (b.state === 'interrupted') {
    ui.dialogs.recovery.value = { project_id: p.project_id }
    return
  }
  const ok = await ui.confirm({
    title: '继续剩余任务？',
    message: `将重新排队 ${counts.value!.skipped + counts.value!.failed} 个未完成的片段，仍使用批次快照 v${b.snapshot.edit_version}。`,
    detail: '已成功的片段不会重新生成。',
    confirmLabel: '继续剩余任务',
  })
  if (!ok) return
  try {
    await tasks.once(`continue:${b.batch_id}`, (rid) => adapter.recovery.continueRemaining(p.project_id, rid || requestId('continue')))
  } catch (e) {
    ui.toast(toAppError(e).message, { tone: 'danger' })
  }
}
</script>

<template>
  <div v-if="batch && counts" class="queue">
    <section class="queue__summary">
      <div class="queue__row">
        <UiSelect v-if="batchOptions.length > 1" v-model="batchId" :options="batchOptions" aria-label="选择批次" size="sm" />
        <StatusTag :label="BATCH_STATE_LABEL[batch.state]" :tone="batch.state === 'running' ? 'accent' : batch.state === 'completed' ? (counts.failed ? 'danger' : 'success') : 'warning'" :icon="['running', 'pause_requested', 'stop_requested'].includes(batch.state) ? 'spinner' : undefined" />
        <span class="small muted num">快照 v{{ batch.snapshot.edit_version }} · {{ formatClock(batch.created_at) }} · 并行上限 {{ batch.active_slots }}</span>
        <span class="grow"></span>
        <UiButton v-if="batch.state === 'running'" size="sm" :icon="Pause" :loading="tasks.busy(`pause:${batch.batch_id}`)" loading-label="正在请求暂停…" v-tip="'等待当前片段安全结束后停止领取新任务'" @click="act('pause')">暂停队列</UiButton>
        <UiButton v-if="batch.state === 'paused' || batch.state === 'pause_requested'" size="sm" :icon="Play" :loading="tasks.busy(`resume:${batch.batch_id}`)" @click="act('resume')">继续队列</UiButton>
        <UiButton v-if="counts.failed" size="sm" :icon="RotateCcw" :loading="tasks.busy(`retry:${batch.batch_id}:all`)" loading-label="正在提交重试…" @click="act('retry')">重试失败（{{ counts.failed }}）</UiButton>
        <UiButton v-if="canContinue" size="sm" variant="primary" :icon="StepForward" :loading="tasks.busy(`continue:${batch.batch_id}`)" @click="continueRemaining">继续剩余任务</UiButton>
        <UiButton
          v-if="['running', 'paused', 'pause_requested'].includes(batch.state)"
          size="sm"
          variant="danger-ghost"
          :icon="Square"
          :loading="tasks.busy(`stop:${batch.batch_id}`)"
          loading-label="正在停止…"
          @click="act('stop')"
        >
          停止整批
        </UiButton>
      </div>
      <div class="queue__progress">
        <p class="queue__count num"><strong>{{ counts.succeeded }}</strong> / {{ counts.total }} 个片段已完成</p>
        <UiProgress :value="counts.succeeded" :max="counts.total" label="已完成片段数量" :tone="counts.failed ? 'warning' : 'success'" />
        <p class="small secondary num queue__chips">
          <span>处理中 {{ counts.running }}</span><span>待执行 {{ counts.queued }}</span><span :class="{ danger: counts.failed }">失败 {{ counts.failed }}</span><span>已跳过 {{ counts.skipped }}</span>
          <span v-if="counts.interrupted">已中断 {{ counts.interrupted }}</span><span v-if="counts.commitUnknown" class="warn">待核查 {{ counts.commitUnknown }}</span>
        </p>
      </div>
      <p v-if="running.length" class="small muted queue__now">
        正在处理：<span v-for="j in running" :key="j.job_id" class="queue__now-item">片段 {{ padIndex(j.display_index) }} · {{ progressText(j) }}</span>
      </p>
      <UiBanner v-if="batch.state === 'pause_requested'" tone="warning" compact>暂停请求中：等待 {{ counts.running }} 个正在处理的片段在安全位置结束，之后不再领取新任务。</UiBanner>
      <UiBanner v-if="batch.state === 'stop_requested'" tone="warning" compact>正在停止：编码中的片段已终止；正在校验或提交的片段需在安全位置结束（{{ counts.running }} 个）。</UiBanner>
      <UiBanner v-if="batch.state === 'interrupted'" tone="warning" compact>
        批次因应用意外退出而中断。需要先进行恢复检查，由你确认后才会继续编码。
        <template #actions><UiButton size="sm" @click="continueRemaining">查看恢复摘要</UiButton></template>
      </UiBanner>
      <UiBanner v-if="editedSince" tone="info" compact>{{ editedSince }} 个片段在此批次创建后被修改。运行中的任务继续使用快照 v{{ batch.snapshot.edit_version }}；这些片段显示为「待更新」，下次导出将使用新版本。</UiBanner>
    </section>

    <div class="queue__filter">
      <UiSegmented
        v-model="filter"
        aria-label="按状态筛选"
        size="sm"
        :options="[
          { value: 'all', label: '全部', count: counts.total },
          { value: 'running', label: '处理中', count: counts.running },
          { value: 'failed', label: '失败', count: counts.failed },
          { value: 'succeeded', label: '成功', count: counts.succeeded },
          { value: 'other', label: '其他', count: counts.queued + counts.skipped + counts.interrupted + counts.commitUnknown },
        ]"
      />
      <span v-if="adapter.mode === 'demo'" class="small muted num">事件重同步 {{ tasks.state.resyncs }} 次 · 丢弃重复 {{ tasks.state.dropped }} 条</span>
    </div>
    <VirtualList :items="jobs" :row-height="64" :key-of="(j: Job) => j.job_id" aria-label="导出任务" role="list" class="queue__list">
      <template #default="{ item }">
        <JobRow
          :job="item"
          :ui="ja.uiOf(item, batch)"
          :project-id="batch.project_id"
          :cover-frame="coverOf(item)"
          :busy-cancel="tasks.busy(`cancel:${item.job_id}`)"
          :busy-retry="tasks.busy(`retry:${batch.batch_id}:${item.job_id}`)"
          @open="emit('open', batch.batch_id, item.job_id)"
          @cancel="ja.cancel(item)"
          @retry="ja.retry(batch, item)"
        />
      </template>
    </VirtualList>
  </div>
</template>

<style scoped>
.queue {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.queue__summary {
  display: grid;
  gap: 10px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--line-subtle);
  background: var(--bg-panel);
}
.queue__row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.queue__progress {
  display: grid;
  grid-template-columns: auto minmax(160px, 1fr) auto;
  align-items: center;
  gap: 14px;
}
.queue__count strong {
  font-size: var(--fs-18);
}
.queue__chips {
  display: flex;
  gap: 12px;
}
.queue__chips .danger {
  color: var(--danger);
}
.queue__chips .warn {
  color: var(--warning);
}
.queue__now {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
}
.queue__filter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 20px;
  border-bottom: 1px solid var(--line-subtle);
}
.queue__list {
  flex: 1;
}
</style>
