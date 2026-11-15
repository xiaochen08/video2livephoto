<script setup lang="ts">
import { ListChecks } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { useApp } from '@/app/context'
import EmptyState from '@/components/EmptyState.vue'
import UiButton from '@/components/UiButton.vue'
import UiSegmented from '@/components/UiSegmented.vue'
import QueuePanel from './QueuePanel.vue'
import ResultsPanel from './ResultsPanel.vue'
import JobDrawer from './JobDrawer.vue'
import { useActions } from '@/app/context'

const { ui, tasks } = useApp()
const actions = useActions()
const openJob = ref<{ batchId: string; jobId: string } | null>(null)
const drawerBatch = computed(() => (openJob.value ? (tasks.state.batches[openJob.value.batchId] ?? null) : null))
const drawerJob = computed(() => drawerBatch.value?.jobs.find((j) => j.job_id === openJob.value?.jobId) ?? null)
</script>

<template>
  <div class="tasks">
    <header class="tasks__head">
      <h1 class="tasks__title">任务与结果</h1>
      <UiSegmented
        v-model="ui.state.tasksTab"
        aria-label="任务视图"
        :options="[
          { value: 'queue', label: '导出队列' },
          { value: 'results', label: '导出结果' },
        ]"
      />
      <span class="grow"></span>
      <UiButton variant="ghost" size="sm" @click="ui.state.route = 'editor'">返回编辑</UiButton>
    </header>
    <EmptyState v-if="!tasks.batches.value.length" :icon="ListChecks" title="还没有导出任务">
      在编辑页确认导出后，任务会出现在这里。离开此页不会影响后端正在运行的任务。
      <template #actions><UiButton variant="primary" @click="actions.openExport()">确认导出…</UiButton></template>
    </EmptyState>
    <QueuePanel v-else-if="ui.state.tasksTab === 'queue'" @open="(b, j) => (openJob = { batchId: b, jobId: j })" />
    <ResultsPanel v-else @open="(b, j) => (openJob = { batchId: b, jobId: j })" />
    <JobDrawer :job="drawerJob" :batch="drawerBatch" @close="openJob = null" />
  </div>
</template>

<style scoped>
.tasks {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  min-height: 0;
  padding: 0 var(--gap) var(--gap);
  background: var(--bg-app);
}
.tasks__head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  border-radius: var(--r-4);
  background: var(--bg-panel);
  box-shadow: var(--panel-edge);
  flex: none;
}
.tasks > :deep(.queue),
.tasks > :deep(.results),
.tasks > :deep(.empty) {
  background: var(--bg-panel);
  border-radius: var(--r-4);
  box-shadow: var(--panel-edge);
  overflow: hidden;
}
.tasks__title {
  font-size: var(--fs-16);
  font-weight: var(--fw-semibold);
}
</style>
