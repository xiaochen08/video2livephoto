<script setup lang="ts">
import { Check, CircleDashed, CircleX, Minus, TriangleAlert } from 'lucide-vue-next'
import { computed, watch } from 'vue'
import { useActions, useApp } from '@/app/context'
import type { AnalysisStageId } from '@/adapters/contract'
import ErrorPanel from '@/components/ErrorPanel.vue'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import UiDialog from '@/components/UiDialog.vue'
import UiProgress from '@/components/UiProgress.vue'
import UiSpinner from '@/components/UiSpinner.vue'
import type { ErrorActionKind } from '@/domain/types'
import { formatBytes } from '@/domain/time'
import { streamSummary, colorSummary } from '@/features/editor/mediaText'

const { home, ui, adapter } = useApp()
const actions = useActions()
const a = home.analysis
const open = computed(() => !!a.value && !a.value.minimized)

const STAGE_LABEL: Record<AnalysisStageId, { title: string; desc: string }> = {
  probe: { title: '读取媒体信息', desc: '容器、视频流、音轨与色彩信息' },
  frame_index: { title: '准备帧时间信息', desc: '建立帧序号与 PTS 对照，用于精确定位' },
  proxy: { title: '准备预览', desc: '生成预览代理与缩略图' },
  shot_detect: { title: '分析镜头', desc: '检测硬切、叠化、闪光与快速运动候选' },
}
const UNIT: Record<string, string> = { frames: '帧', thumbnails: '张', bytes: '%' }

const title = computed(() => {
  switch (a.value?.status) {
    case 'done':
      return '分析完成'
    case 'failed':
      return '分析失败'
    case 'cancelled':
      return '分析已取消'
    case 'cancelling':
      return '正在取消分析…'
    default:
      return '正在分析视频'
  }
})

const stream = computed(() => {
  const p = a.value?.probe
  if (!p) return null
  return p.media.video_streams.find((s) => s.stream_index === a.value!.streamIndex) ?? p.media.video_streams[0]
})

async function cancel() {
  const ok = await ui.confirm({
    title: '取消分析？',
    message: '已完成的阶段结果不会保留为项目。源视频不受影响，之后可以重新导入。',
    confirmLabel: '取消分析',
    cancelLabel: '继续分析',
    tone: 'danger',
  })
  if (ok) await home.cancelAnalysis()
}

function minimize() {
  home.patchAnalysis({ minimized: true })
}

async function enterEditor() {
  const s = a.value
  if (!s?.projectId) return
  const id = s.projectId
  const warnings = s.warnings
  home.clearAnalysis()
  await actions.openProject(id)
  warnings.forEach((w) => ui.toast(w.message, { tone: 'warning', timeout: 7000 }))
}

function onErr(k: ErrorActionKind) {
  if (k === 'retry') home.retryAnalysis()
  if (k === 'open_diagnostics') {
    minimize()
    ui.state.settingsSection = 'diagnostics'
    ui.state.route = 'settings'
  }
}

// analysis finished while the dialog is visible → go straight to the editor
watch(
  () => a.value?.status,
  (s) => {
    if (s === 'done' && a.value && !a.value.minimized) void enterEditor()
  },
)
</script>

<template>
  <UiDialog
    :open="open"
    :title="title"
    :description="a ? `${a.file.name} · ${formatBytes(a.file.size_bytes)}` : undefined"
    size="md"
    :dismiss-on-scrim="false"
    @close="a && (a.status === 'running' || a.status === 'cancelling' ? minimize() : home.clearAnalysis())"
  >
    <template v-if="a">
      <div v-if="stream" class="ana__media small">
        <span>{{ streamSummary(stream) }}</span>
        <span>{{ colorSummary(stream.color) }}</span>
        <span>{{ a.probe?.media.audio_streams.length ? '有音轨' : '源视频无音轨' }}</span>
      </div>
      <UiBanner v-for="n in a.probe?.notes ?? []" :key="n.code" :tone="n.code.startsWith('DEMO') ? 'demo' : 'info'" compact class="ana__note">{{ n.message }}</UiBanner>

      <ol class="stages" aria-label="分析阶段">
        <li v-for="s in a.event?.stages ?? []" :key="s.id" class="stage" :data-status="s.status">
          <span class="stage__icon" aria-hidden="true">
            <UiSpinner v-if="s.status === 'running'" :size="13" />
            <Check v-else-if="s.status === 'done'" :size="14" :stroke-width="2.25" />
            <TriangleAlert v-else-if="s.status === 'partial'" :size="14" />
            <CircleX v-else-if="s.status === 'failed'" :size="14" />
            <Minus v-else-if="s.status === 'skipped'" :size="14" />
            <CircleDashed v-else :size="14" />
          </span>
          <div class="stage__body">
            <div class="stage__row">
              <span class="stage__title">{{ STAGE_LABEL[s.id].title }}</span>
              <span v-if="s.progress" class="stage__num small num">
                <template v-if="s.progress.unit === 'bytes'">{{ s.progress.done }}%</template>
                <template v-else>{{ s.progress.done.toLocaleString() }} / {{ s.progress.total.toLocaleString() }} {{ UNIT[s.progress.unit] }}</template>
              </span>
              <span v-else-if="s.status === 'running'" class="stage__num small muted">总量未知</span>
            </div>
            <p class="stage__desc small">{{ s.note ?? STAGE_LABEL[s.id].desc }}</p>
            <UiProgress
              v-if="s.status === 'running'"
              thin
              :value="s.progress ? s.progress.done : null"
              :max="s.progress?.total ?? 1"
              :label="`${STAGE_LABEL[s.id].title}进度`"
            />
          </div>
        </li>
        <li v-if="!a.event" class="stage" data-status="running">
          <span class="stage__icon"><UiSpinner :size="13" /></span>
          <div class="stage__body"><span class="stage__title">正在启动分析…</span></div>
        </li>
      </ol>

      <p v-if="a.event?.shots_found !== null && a.event?.shots_found !== undefined" class="ana__shots">
        已发现 <strong class="num">{{ a.event.shots_found }}</strong> 个镜头
      </p>
      <UiBanner v-if="a.event?.slow_hint" tone="warning" compact>{{ a.event.slow_hint }}</UiBanner>
      <ErrorPanel v-if="a.status === 'failed' && a.error" :error="a.error" context="视频分析" :where="a.file.name" @action="onErr" />
      <p v-if="adapter.mode === 'demo'" class="small muted ana__demo">演示模式：阶段与进度由演示适配器模拟，不代表真实分析耗时。</p>
    </template>

    <template #footer>
      <template v-if="a?.status === 'running' || a?.status === 'cancelling'">
        <span class="small muted grow">关闭此窗口不会中断分析，可在首页查看进度。</span>
        <UiButton variant="danger-ghost" :loading="a.status === 'cancelling'" loading-label="正在取消…" @click="cancel">取消分析</UiButton>
        <UiButton @click="minimize">在后台继续</UiButton>
      </template>
      <template v-else-if="a?.status === 'failed'">
        <UiButton variant="ghost" @click="home.clearAnalysis()">关闭</UiButton>
        <UiButton variant="primary" @click="home.retryAnalysis()">重试分析</UiButton>
      </template>
      <template v-else-if="a?.status === 'cancelled'">
        <UiButton variant="primary" @click="home.clearAnalysis()">关闭</UiButton>
      </template>
      <template v-else-if="a?.status === 'done'">
        <UiButton variant="primary" @click="enterEditor">进入编辑</UiButton>
      </template>
    </template>
  </UiDialog>
</template>

<style scoped>
.ana__media {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  color: var(--text-3);
  margin-bottom: 10px;
}
.ana__note {
  margin-bottom: 8px;
}
.stages {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 4px 0 12px;
}
.stage {
  display: grid;
  grid-template-columns: 22px 1fr;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--line-subtle);
}
.stage__icon {
  color: var(--text-3);
  display: flex;
  justify-content: center;
  padding-top: 3px;
}
.stage[data-status='running'] .stage__icon {
  color: var(--accent);
}
.stage[data-status='done'] .stage__icon {
  color: var(--success);
}
.stage[data-status='partial'] .stage__icon {
  color: var(--warning);
}
.stage[data-status='failed'] .stage__icon {
  color: var(--danger);
}
.stage__body {
  display: grid;
  gap: 4px;
  min-width: 0;
}
.stage__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.stage__title {
  font-weight: var(--fw-medium);
}
.stage[data-status='pending'] .stage__title {
  color: var(--text-3);
}
.stage__num {
  color: var(--text-2);
}
.stage__desc {
  color: var(--text-3);
}
.ana__shots {
  margin-bottom: 10px;
}
.ana__demo {
  margin-top: 10px;
}
</style>
