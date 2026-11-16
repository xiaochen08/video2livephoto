<script setup lang="ts">
import { Copy, ExternalLink, FileSearch, FolderOpen, RotateCcw } from 'lucide-vue-next'
import { computed } from 'vue'
import { useApp } from '@/app/context'
import FrameImage from '@/components/FrameImage.vue'
import IconButton from '@/components/IconButton.vue'
import StatusTag from '@/components/StatusTag.vue'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import VirtualList from '@/components/VirtualList.vue'
import { errorToClipboardText } from '@/domain/errors'
import { JOB_UI_META } from '@/domain/jobStates'
import { padIndex } from '@/domain/naming'
import { formatClock } from '@/domain/time'
import type { Batch, Job } from '@/domain/types'
import ArtifactPills from './ArtifactPills.vue'
import { useJobActions } from './useJobActions'

const emit = defineEmits<{ open: [string, string] }>()
const { tasks, session, ui } = useApp()
const ja = useJobActions()
interface Row {
  job: Job
  batch: Batch
}
const rows = computed<Row[]>(() => [...tasks.latestJobByClip.value.values()].sort((a, b) => a.job.display_index - b.job.display_index))
const counts = computed(() => {
  const r = { succeeded: 0, failed: 0, skipped: 0, outdated: 0, other: 0 }
  for (const { job, batch } of rows.value) {
    const u = ja.uiOf(job, batch)
    if (u === 'succeeded') r.succeeded++
    else if (u === 'failed') r.failed++
    else if (u === 'skipped') r.skipped++
    else if (u === 'outdated') r.outdated++
    else r.other++
  }
  return r
})
const p = session.project
function livePhotoKind(job: Job): 'livp' | 'jpg' | 'mov' {
  if (job.artifacts.some((artifact) => artifact.kind === 'livp')) return 'livp'
  if (job.artifacts.some((artifact) => artifact.kind === 'jpg')) return 'jpg'
  return 'mov'
}
async function copyErr(job: Job) {
  if (!job.error) return
  const text = errorToClipboardText(job.error, `${p.value?.name} · ${job.file_stem}`)
  try {
    await navigator.clipboard.writeText(text)
    ui.toast('错误信息已复制', { tone: 'success', timeout: 2000 })
  } catch {
    ui.dialogs.report.value = { title: '错误信息', body: text }
  }
}
</script>

<template>
  <div class="results">
    <section class="results__head">
      <p class="results__counts num">
        <span><strong class="ok">{{ counts.succeeded }}</strong> 成功</span>
        <span><strong :class="{ bad: counts.failed }">{{ counts.failed }}</strong> 失败</span>
        <span><strong>{{ counts.skipped }}</strong> 已跳过</span>
        <span><strong :class="{ warn: counts.outdated }">{{ counts.outdated }}</strong> 待更新</span>
        <span v-if="counts.other"><strong>{{ counts.other }}</strong> 进行中或待核查</span>
      </p>
      <dl class="results__versions small">
        <div><dt>当前编辑版本</dt><dd class="num">v{{ p?.edit_version }}</dd></div>
        <div><dt>最近成功导出</dt><dd class="num">{{ tasks.lastSuccessVersion.value ? `v${tasks.lastSuccessVersion.value.edit_version} · ${formatClock(tasks.lastSuccessVersion.value.created_at)}` : '—' }}</dd></div>
        <div><dt>正在运行</dt><dd class="num">{{ tasks.runningVersion.value ? `v${tasks.runningVersion.value.edit_version}` : '无' }}</dd></div>
      </dl>
      <div class="row">
        <UiButton size="sm" :icon="FolderOpen" @click="ja.reveal()">打开输出目录</UiButton>
      </div>
      <UiBanner tone="warning" compact>
        本地校验通过只代表 LIVP 封装、配对标识和文件结构正确，不代表已经进入 iPhone 相册里的 Live Photo。微信、QQ、聊天窗口仍可能压缩、改名或拦截文件；请按“文件”发送 <span class="mono">.livp</span>，不要按图片/视频发送，也不要发送 视频片段/*.mp4。iPhone、朋友圈、小红书、抖音仍需真机测试。
      </UiBanner>
    </section>
    <div class="results__cols small muted" aria-hidden="true">
      <span>片段</span><span></span><span>文件</span><span>状态</span><span>产物</span><span>配对结构</span><span>实机</span><span></span>
    </div>
    <VirtualList :items="rows" :row-height="56" :key-of="(r: Row) => r.job.clip_id" role="list" aria-label="每个片段的最近导出结果" class="results__list">
      <template #default="{ item }">
        <div class="rrow" @click="emit('open', item.batch.batch_id, item.job.job_id)">
          <span class="num muted">{{ padIndex(item.job.display_index) }}</span>
          <FrameImage class="rrow__thumb" :project-id="item.batch.project_id" :frame="item.batch.snapshot.clips.find((c) => c.clip_id === item.job.clip_id)?.cover_frame ?? 0" size="thumb" alt="" />
          <span class="mono small truncate">{{ item.job.file_stem }} <span class="muted">· v{{ item.batch.snapshot.edit_version }}</span></span>
          <StatusTag size="sm" v-bind="JOB_UI_META[ja.uiOf(item.job, item.batch)]" />
          <ArtifactPills :artifacts="item.job.artifacts" />
          <StatusTag size="sm" :tone="item.job.verification.local === 'passed' ? 'success' : 'muted'" :label="item.job.verification.local === 'passed' ? '已校验' : '未完成'" />
          <StatusTag size="sm" tone="muted" label="待验证" />
          <span class="rrow__actions" @click.stop>
            <IconButton :icon="ExternalLink" size="sm" :label="livePhotoKind(item.job) === 'livp' ? '打开 LIVP' : '打开配对资源'" :disabled="item.job.stage !== 'succeeded'" disabled-reason="尚未成功" @click="ja.open(item.job, livePhotoKind(item.job))" />
            <IconButton :icon="FolderOpen" size="sm" label="定位目录" @click="ja.reveal(item.job)" />
            <IconButton :icon="FileSearch" size="sm" label="查看配对校验报告" :disabled="!item.job.verification.local_report_id" disabled-reason="尚未生成校验报告" @click="ja.report(item.job)" />
            <IconButton v-if="item.job.error" :icon="Copy" size="sm" label="复制错误信息" @click="copyErr(item.job)" />
            <IconButton v-if="item.job.stage === 'failed'" :icon="RotateCcw" size="sm" label="重试相关任务" @click="ja.retry(item.batch, item.job)" />
          </span>
        </div>
      </template>
    </VirtualList>
  </div>
</template>

<style scoped>
.results {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.results__head {
  display: grid;
  gap: 10px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--line-subtle);
  background: var(--bg-panel);
}
.results__counts {
  display: flex;
  gap: 20px;
  color: var(--text-2);
}
.results__counts strong {
  font-size: var(--fs-18);
  color: var(--text-1);
  margin-right: 4px;
}
.results__counts .ok {
  color: var(--success);
}
.results__counts .bad {
  color: var(--danger);
}
.results__counts .warn {
  color: var(--warning);
}
.results__versions {
  display: flex;
  gap: 24px;
}
.results__versions div {
  display: flex;
  gap: 8px;
}
.results__versions dt {
  color: var(--text-3);
}
.rrow,
.results__cols {
  display: grid;
  grid-template-columns: 36px 64px minmax(0, 1fr) 96px 110px 72px 64px 150px;
  align-items: center;
  gap: 12px;
  padding: 0 16px 0 20px;
}
.results__cols {
  padding-top: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--line-subtle);
}
.rrow {
  height: 100%;
  border-bottom: 1px solid var(--line-subtle);
}
.rrow:hover {
  background: var(--bg-raised);
}
.rrow__thumb {
  width: 64px;
  height: 36px;
  border-radius: 2px;
}
.rrow__actions {
  display: flex;
  justify-content: flex-end;
  gap: 2px;
}
.results__list {
  flex: 1;
}
</style>
