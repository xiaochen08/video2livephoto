<script setup lang="ts">
import { RotateCcw, X, ChevronRight } from 'lucide-vue-next'
import { computed } from 'vue'
import FrameImage from '@/components/FrameImage.vue'
import IconButton from '@/components/IconButton.vue'
import StatusTag from '@/components/StatusTag.vue'
import UiProgress from '@/components/UiProgress.vue'
import { JOB_UI_META, type JobUiState } from '@/domain/jobStates'
import { padIndex } from '@/domain/naming'
import type { Job } from '@/domain/types'
import ArtifactPills from './ArtifactPills.vue'
import { attemptText, progressRatio, progressText } from './jobText'

const props = defineProps<{ job: Job; ui: JobUiState; projectId: string; coverFrame: number; busyCancel: boolean; busyRetry: boolean }>()
defineEmits<{ open: []; cancel: []; retry: [] }>()
const meta = computed(() => JOB_UI_META[props.ui])
const running = computed(() => ['processing', 'verifying', 'committing', 'pause_wait'].includes(props.ui))
</script>

<template>
  <div class="jrow" :data-ui="ui" @click="$emit('open')">
    <span class="jrow__idx num">{{ padIndex(job.display_index) }}</span>
    <FrameImage class="jrow__thumb" :project-id="projectId" :frame="coverFrame" size="thumb" alt="" />
    <div class="jrow__main">
      <div class="jrow__line">
        <span class="jrow__name truncate mono">{{ job.file_stem }}</span>
        <StatusTag size="sm" :tone="meta.tone" :icon="meta.icon" :label="meta.label" />
      </div>
      <div class="jrow__line small">
        <span class="jrow__prog truncate num">{{ job.error && ui === 'failed' ? job.error.message : progressText(job) }}</span>
        <span v-if="attemptText(job)" class="muted jrow__att">{{ attemptText(job) }}</span>
      </div>
      <UiProgress v-if="running" thin :value="progressRatio(job)" :label="`${job.file_stem} 进度`" />
      <p v-if="job.cancel_requested && job.cancel_wait_reason" class="small jrow__wait">取消已请求：{{ job.cancel_wait_reason }}</p>
    </div>
    <ArtifactPills :artifacts="job.artifacts" />
    <div class="jrow__actions" @click.stop>
      <IconButton
        v-if="running || ui === 'queued'"
        :icon="X"
        size="sm"
        tone="danger"
        label="取消此片段"
        :disabled="job.cancel_requested || (!job.cancellable && job.stage === 'committing')"
        :disabled-reason="job.cancel_requested ? '已请求取消，等待安全位置' : '正在安全提交，不能立即取消'"
        :loading="busyCancel"
        @click="$emit('cancel')"
      />
      <IconButton v-if="ui === 'failed'" :icon="RotateCcw" size="sm" label="重试此片段" :loading="busyRetry" @click="$emit('retry')" />
      <IconButton :icon="ChevronRight" size="sm" label="查看详情" @click="$emit('open')" />
    </div>
  </div>
</template>

<style scoped>
.jrow {
  height: 100%;
  display: grid;
  grid-template-columns: 36px 64px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  padding: 0 12px 0 16px;
  border-bottom: 1px solid var(--line-subtle);
  cursor: default;
}
.jrow:hover {
  background: var(--bg-raised);
}
.jrow__idx {
  color: var(--text-3);
  font-size: var(--fs-12);
}
.jrow__thumb {
  width: 64px;
  height: 36px;
  border-radius: 2px;
}
.jrow__main {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.jrow__line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.jrow__name {
  font-size: var(--fs-13);
}
.jrow__prog {
  color: var(--text-2);
}
.jrow[data-ui='failed'] .jrow__prog {
  color: var(--danger);
}
.jrow__att {
  white-space: nowrap;
}
.jrow__wait {
  color: var(--warning);
}
.jrow__actions {
  display: flex;
  gap: 2px;
}
</style>
