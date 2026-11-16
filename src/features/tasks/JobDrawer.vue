<script setup lang="ts">
import { ExternalLink, FileSearch, FolderOpen, X } from 'lucide-vue-next'
import { computed } from 'vue'
import { useApp } from '@/app/context'
import ErrorPanel from '@/components/ErrorPanel.vue'
import ParamRow from '@/components/ParamRow.vue'
import StatusTag from '@/components/StatusTag.vue'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import UiDialog from '@/components/UiDialog.vue'
import UiProgress from '@/components/UiProgress.vue'
import { JOB_UI_META, STAGE_LABEL } from '@/domain/jobStates'
import { formatBytes, formatClock } from '@/domain/time'
import type { Batch, Job } from '@/domain/types'
import { ARTIFACT_STATUS, progressRatio, progressText } from './jobText'
import { useJobActions } from './useJobActions'

const props = defineProps<{ job: Job | null; batch: Batch | null }>()
defineEmits<{ close: [] }>()
const { tasks } = useApp()
const ja = useJobActions()
const uiState = computed(() => (props.job && props.batch ? ja.uiOf(props.job, props.batch) : null))
const DEVICE = { iphone: 'iPhone 相册', wechat_moments: '微信朋友圈', xiaohongshu: '小红书', douyin: '抖音' } as const
const committed = computed(() => props.job?.artifacts.every((a) => a.status === 'committed') ?? false)
const hasSingleFileLivePhoto = computed(() => props.job?.artifacts.some((a) => a.kind === 'livp') ?? false)
</script>

<template>
  <UiDialog :open="!!job" :title="job ? job.file_stem : ''" :description="job ? `片段 ${job.display_index} · 稳定 ID ${job.clip_id} · 任务 ${job.job_id}` : undefined" placement="right" @close="$emit('close')">
    <div v-if="job && batch && uiState" class="jd">
      <section class="jd__sec">
        <div class="row">
          <StatusTag :tone="JOB_UI_META[uiState].tone" :icon="JOB_UI_META[uiState].icon" :label="JOB_UI_META[uiState].label" />
          <span class="small secondary">{{ progressText(job) }}</span>
        </div>
        <UiProgress v-if="['encoding', 'verifying', 'committing'].includes(job.stage)" :value="progressRatio(job)" :label="`${job.file_stem} 进度`" />
        <p class="small muted">后端状态：<span class="mono">{{ job.stage }}</span>（{{ STAGE_LABEL[job.stage] }}）· 批次快照 v{{ batch.snapshot.edit_version }}</p>
        <UiBanner v-if="job.cancel_requested && job.cancel_wait_reason" tone="warning" compact>取消已请求：{{ job.cancel_wait_reason }}</UiBanner>
        <UiBanner v-if="job.stage === 'committing'" tone="info" compact>正在安全提交：新版全部产物校验通过后才替换旧版。此阶段不能立即取消。</UiBanner>
        <UiBanner v-if="job.stage === 'commit_unknown'" tone="warning" compact>提交过程中断，结果待核查。等待后端恢复检查确认，不会被计为成功。</UiBanner>
        <UiBanner v-if="job.previous_protected && job.stage !== 'succeeded'" tone="info" compact>上次成功导出的旧版文件受保护，新版提交完成前保持不变。</UiBanner>
        <div class="row">
          <UiButton
            v-if="['queued', 'encoding', 'verifying'].includes(job.stage)"
            size="sm"
            variant="danger-ghost"
            :icon="X"
            :disabled="job.cancel_requested"
            disabled-reason="已请求取消"
            :loading="tasks.busy(`cancel:${job.job_id}`)"
            @click="ja.cancel(job)"
          >
            取消当前片段
          </UiButton>
          <UiButton v-if="job.stage === 'failed'" size="sm" :loading="tasks.busy(`retry:${batch.batch_id}:${job.job_id}`)" @click="ja.retry(batch, job)">重试此片段</UiButton>
        </div>
      </section>

      <section v-if="job.error" class="jd__sec">
        <ErrorPanel :error="job.error" context="导出片段" :where="`片段 ${job.display_index} · ${job.file_stem}`" @action="(k) => ja.onErrorAction(k, batch!, job!)" />
      </section>

      <section class="jd__sec">
        <h3 class="section-title">产物</h3>
        <div v-for="a in job.artifacts" :key="a.kind" class="jd__art">
          <span class="mono small jd__art-name truncate">{{ a.rel_dir }}/{{ a.file_name }}</span>
          <StatusTag size="sm" :tone="ARTIFACT_STATUS[a.status].tone" :label="ARTIFACT_STATUS[a.status].label" />
          <span class="small muted num">{{ formatBytes(a.size_bytes) }}</span>
          <UiButton size="sm" variant="ghost" :icon="ExternalLink" :disabled="a.status !== 'committed'" disabled-reason="文件尚未提交" @click="ja.open(job, a.kind)">打开</UiButton>
        </div>
        <div class="row">
          <UiButton size="sm" :icon="FolderOpen" @click="ja.reveal(job)">定位目录</UiButton>
          <UiButton size="sm" :icon="FileSearch" :disabled="!job.verification.local_report_id" disabled-reason="尚未生成校验报告" @click="ja.report(job)">配对校验报告</UiButton>
        </div>
        <UiBanner v-if="committed && hasSingleFileLivePhoto" tone="warning" compact>
          这两件产物通过的是本地 LIVP 封装校验，不是 iPhone 相册实机验收。请把 <span class="mono">LivePhoto/*.livp</span> 按“文件”发送到手机；按图片/视频发送可能压缩或转码。不要发送 <span class="mono">视频片段/*.mp4</span>。
        </UiBanner>
        <UiBanner v-else-if="committed" tone="warning" compact>
          这是旧版 JPG/MOV 配对输出，只代表文件本地校验通过。新导出会生成单个 <span class="mono">.livp</span>；不要按图片/视频发送旧资源。
        </UiBanner>
      </section>

      <section class="jd__sec">
        <h3 class="section-title">校验</h3>
        <dl class="jd__dl">
          <ParamRow label="基础配对校验">
            <StatusTag size="sm" :tone="job.verification.local === 'passed' ? 'success' : job.verification.local === 'failed' ? 'danger' : 'muted'" :label="job.verification.local === 'passed' ? '通过' : job.verification.local === 'failed' ? '未通过' : '未完成'" />
          </ParamRow>
          <ParamRow v-for="(label, key) in DEVICE" :key="key" :label="label">
            <StatusTag size="sm" :tone="job.verification.devices[key] === 'passed' ? 'success' : job.verification.devices[key] === 'failed' ? 'danger' : 'muted'" :label="job.verification.devices[key] === 'unverified' ? '待验证' : job.verification.devices[key] === 'passed' ? '实机通过' : '实机失败'" />
          </ParamRow>
        </dl>
        <p class="small muted">基础校验检查文件可解码、帧范围与快照一致、LIVP 内部资源及配对标识一致；它不等于 iPhone 相册已创建 Live Photo。平台实机播放需在真实设备上测试后单独记录。</p>
        <p v-if="committed" class="small muted">两件产物均已提交。</p>
      </section>

      <section class="jd__sec">
        <h3 class="section-title">尝试记录 <span class="muted num">{{ job.attempts.length }}</span></h3>
        <ol class="jd__att">
          <li v-for="a in job.attempts" :key="a.attempt_id" :data-result="a.result">
            <span class="num">#{{ a.n }}</span>
            <span>{{ a.encoder.toUpperCase() }}</span>
            <span class="small">{{ { running: '进行中', failed: '失败', succeeded: '成功', cancelled: '已取消', interrupted: '中断' }[a.result] }}</span>
            <span class="small muted num">{{ formatClock(a.started_at) }}</span>
            <p v-if="a.error" class="small jd__att-err">{{ a.error.code }} · {{ a.error.message }}</p>
          </li>
          <li v-if="!job.attempts.length" class="small muted">尚未开始</li>
        </ol>
        <p class="small muted">失败尝试保留在记录中；成功数量按片段结果统计，不按尝试次数。</p>
      </section>
    </div>
  </UiDialog>
</template>

<style scoped>
.jd {
  display: flex;
  flex-direction: column;
}
.jd__sec {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 0;
  border-bottom: 1px solid var(--line-subtle);
}
.jd__sec:first-child {
  padding-top: 0;
}
.jd__art {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 64px auto;
  gap: 8px;
  align-items: center;
}
.jd__art-name {
  user-select: text;
}
.jd__dl {
  display: grid;
  gap: 2px;
}
.jd__att {
  display: grid;
  gap: 6px;
}
.jd__att li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
  padding: 6px 8px;
  background: var(--bg-raised);
  border-radius: var(--r-1);
  font-size: var(--fs-13);
}
.jd__att li[data-result='failed'] {
  box-shadow: inset 2px 0 0 var(--danger);
}
.jd__att li[data-result='succeeded'] {
  box-shadow: inset 2px 0 0 var(--success);
}
.jd__att-err {
  width: 100%;
  color: var(--danger);
}
</style>
