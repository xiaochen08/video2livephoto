<script setup lang="ts">
import { FileVideo, FolderOpen, Upload, Clapperboard, ScanLine, ListChecks, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useActions, useApp } from '@/app/context'
import type { FileRef } from '@/adapters/contract'
import type { DemoControl } from '@/adapters/demo/DemoAdapter'
import EmptyState from '@/components/EmptyState.vue'
import ErrorPanel from '@/components/ErrorPanel.vue'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import UiProgress from '@/components/UiProgress.vue'
import UiSpinner from '@/components/UiSpinner.vue'
import type { ErrorActionKind, RecentProject } from '@/domain/types'
import { formatBytes } from '@/domain/time'
import RecentRow from './RecentRow.vue'
import { useImport } from './useImport'

const ctx = useApp()
const actions = useActions()
const { home, ui, adapter, session } = ctx
const demo = (adapter as unknown as { demo?: DemoControl }).demo ?? null
const fileInput = ref<HTMLInputElement>()
const dragging = ref(false)
let dragDepth = 0
const { importRef, analysisBusy } = useImport()

const recents = computed(() => home.state.recents)
const firstUse = computed(() => !home.state.loading && !home.state.loadError && recents.value.length === 0)
const a = home.analysis

watch(
  () => ui.state.pickerRequest,
  () => pickVideo(),
)

async function pickVideo() {
  if (analysisBusy.value) return
  if (adapter.mode === 'desktop') {
    const ref = await adapter.media.pickVideo()
    if (ref) void importRef(ref)
    return
  }
  fileInput.value?.click()
}
function onFileInput(e: Event) {
  const input = e.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  input.value = ''
  handleFiles(files)
}
function handleFiles(files: File[]) {
  if (!files.length) return
  if (files.length > 1) {
    ui.dialogs.multiFile.value = files
    return
  }
  void importRef(adapter.media.fromBrowserFile(files[0]))
}

function onDragEnter(e: DragEvent) {
  if (!e.dataTransfer?.types.includes('Files')) return
  dragDepth++
  dragging.value = true
}
function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (!dragDepth) dragging.value = false
}
function onDrop(e: DragEvent) {
  dragDepth = 0
  dragging.value = false
  if (analysisBusy.value) {
    ui.toast('已有分析任务进行中。一次处理一条成片，请等待完成或取消后再导入。', { tone: 'warning' })
    return
  }
  handleFiles([...(e.dataTransfer?.files ?? [])])
}

async function openProjectFile() {
  const id = await adapter.projects.pickProjectFile()
  if (id) return actions.openProject(id)
  if (adapter.mode === 'demo') ui.toast('演示模式没有系统文件对话框。请从「最近项目」打开，或在「演示场景」面板中选择项目。', { timeout: 5000 })
}

async function rename(p: RecentProject) {
  const name = await ui.prompt({
    title: '重命名项目',
    label: '项目名称',
    value: p.name,
    hint: '只修改项目显示名称。源视频文件名与已导出文件名都不会改变。',
    confirmLabel: '重命名',
    validate: (v) => (v.trim() ? null : '名称不能为空'),
  })
  if (!name || !name.trim() || name === p.name) return
  try {
    await adapter.projects.rename(p.project_id, name.trim())
    await home.loadRecents()
  } catch (e) {
    ui.toast((e as Error).message, { tone: 'danger' })
  }
}
async function removeRecent(p: RecentProject) {
  const ok = await ui.confirm({
    title: '从最近记录移除？',
    message: `“${p.name}”将不再出现在最近项目中。`,
    detail: '只移除入口记录。项目文件、源视频与导出结果全部保留，之后可通过「打开项目」重新加入。',
    confirmLabel: '移除记录',
  })
  if (!ok) return
  await adapter.projects.removeRecent(p.project_id)
  if (home.state.openError?.project_id === p.project_id) home.state.openError = null
  await home.loadRecents()
  ui.toast(`已从最近记录移除“${p.name}”。项目与文件未删除。`)
}

function onOpenErrorAction(kind: ErrorActionKind) {
  const err = home.state.openError
  if (!err) return
  const p = recents.value.find((r) => r.project_id === err.project_id)
  if (kind === 'relocate_source' && p) {
    ui.dialogs.relocate.value = { project_id: p.project_id, name: p.name, reason: err.error.code === 'SOURCE_CHANGED' ? 'changed' : 'missing' }
  } else if (kind === 'retry') void actions.openProject(err.project_id)
  else if (kind === 'open_diagnostics') {
    ui.state.settingsSection = 'diagnostics'
    ui.state.route = 'settings'
  }
}

const openErrorProject = computed(() => recents.value.find((r) => r.project_id === home.state.openError?.project_id) ?? null)

const analysisProgress = computed(() => {
  const e = a.value?.event
  if (!e) return null
  const running = e.stages.find((s) => s.status === 'running')
  return running
})

function sampleImport(ref_id: string) {
  if (!demo) return
  void importRef(demo.sampleRef(ref_id) as FileRef)
}

function startQueued(i: number) {
  const f = home.state.queue[i]
  if (!f || analysisBusy.value) return
  home.state.queue.splice(i, 1)
  void importRef(adapter.media.fromBrowserFile(f))
}

onBeforeUnmount(() => {
  dragDepth = 0
})
</script>

<template>
  <div class="home" @dragenter.prevent="onDragEnter" @dragover.prevent @dragleave="onDragLeave" @drop.prevent="onDrop">
    <section class="home__import" aria-labelledby="import-title">
      <h1 id="import-title" class="home__title">新建项目</h1>
      <p class="home__lead secondary">导入一条已剪辑完成的成片，按镜头自动分段后批量制作 Live Photo。</p>

      <div class="drop" :class="{ 'is-busy': analysisBusy }">
        <Upload :size="22" :stroke-width="1.5" class="drop__icon" aria-hidden="true" />
        <p class="drop__title">拖入视频文件到此窗口</p>
        <p class="drop__hint small">MP4 / MOV · 一次一条成片 · 源视频只读，不会被修改</p>
        <UiButton
          variant="primary"
          size="lg"
          :icon="FileVideo"
          :disabled="analysisBusy"
          disabled-reason="已有分析任务进行中（一次处理一条成片）"
          :loading="!!home.state.probing"
          loading-label="正在读取媒体信息…"
          kbd="Ctrl+O"
          @click="pickVideo"
        >
          选择视频
        </UiButton>
        <input ref="fileInput" type="file" accept="video/mp4,video/quicktime,.mp4,.mov" class="sr-only" tabindex="-1" aria-hidden="true" multiple @change="onFileInput" />
      </div>

      <ErrorPanel v-if="home.state.importError" :error="home.state.importError.error" context="导入视频" :where="home.state.importError.file" compact />

      <div v-if="home.state.queue.length" class="queue">
        <p class="section-title">待导入（分别建立项目）</p>
        <div v-for="(f, i) in home.state.queue" :key="f.name + i" class="queue__item">
          <FileVideo :size="14" aria-hidden="true" />
          <span class="truncate grow">{{ f.name }}</span>
          <span class="small muted num">{{ formatBytes(f.size) }}</span>
          <UiButton size="sm" variant="ghost" :disabled="analysisBusy" disabled-reason="当前分析完成后可开始" @click="startQueued(i)">开始</UiButton>
          <button type="button" class="queue__remove" :aria-label="`从待导入中移除 ${f.name}`" @click="home.state.queue.splice(i, 1)"><X :size="13" /></button>
        </div>
      </div>

      <div v-if="a && a.minimized" class="mini" role="status">
        <ScanLine :size="15" aria-hidden="true" />
        <div class="mini__body">
          <p class="truncate">
            <template v-if="a.status === 'running'">正在分析 {{ a.file.name }}</template>
            <template v-else-if="a.status === 'done'">分析完成：{{ a.file.name }}</template>
            <template v-else-if="a.status === 'failed'">分析失败：{{ a.file.name }}</template>
            <template v-else>分析已取消</template>
          </p>
          <UiProgress
            v-if="a.status === 'running'"
            thin
            :value="analysisProgress?.progress ? analysisProgress.progress.done : null"
            :max="analysisProgress?.progress?.total ?? 1"
            label="分析进度"
          />
        </div>
        <UiButton size="sm" @click="home.patchAnalysis({ minimized: false })">{{ a.status === 'done' ? '进入编辑' : '查看' }}</UiButton>
      </div>

      <div v-if="demo" class="samples">
        <p class="section-title">演示示例视频 <span class="muted">（随工程分发的合成素材，分析为模拟）</span></p>
        <div class="samples__grid">
          <button v-for="s in demo.samples" :key="s.ref_id" type="button" class="sample" :disabled="analysisBusy" @click="sampleImport(s.ref_id)">
            <Clapperboard :size="14" aria-hidden="true" />
            <span class="sample__text"><span class="truncate">{{ s.name }}</span><span class="small muted">{{ s.note }}</span></span>
          </button>
        </div>
      </div>

      <ol class="steps small" aria-label="工作流程">
        <li><span class="steps__n num">1</span>导入并分析镜头</li>
        <li><span class="steps__n num">2</span>检查切点、设置片段与封面</li>
        <li><span class="steps__n num">3</span>确认导出 MP4 + JPG + MOV</li>
      </ol>
    </section>

    <section class="home__recents" aria-labelledby="recents-title">
      <header class="recents__head">
        <h2 id="recents-title" class="recents__title">最近项目 <span v-if="recents.length" class="muted num">{{ recents.length }}</span></h2>
        <UiButton size="sm" :icon="FolderOpen" @click="openProjectFile">打开项目…</UiButton>
      </header>

      <div v-if="home.state.openError" class="recents__error">
        <ErrorPanel
          :error="home.state.openError.error"
          context="打开项目"
          :where="openErrorProject?.name ?? home.state.openError.project_id"
          @action="onOpenErrorAction"
        />
        <UiBanner v-if="home.state.openError.error.code === 'SOURCE_MISSING' || home.state.openError.error.code === 'SOURCE_CHANGED'" tone="info" compact>
          同名文件只作为候选。只有后端核对身份（大小、内容指纹、视频流特征）通过后，项目才会恢复处理。
        </UiBanner>
      </div>

      <div v-if="home.state.loading && !recents.length" class="recents__loading"><UiSpinner /> 正在读取最近项目…</div>
      <ErrorPanel v-else-if="home.state.loadError" :error="home.state.loadError" context="读取最近项目" @action="home.loadRecents()" />
      <EmptyState v-else-if="firstUse" :icon="ListChecks" title="还没有项目">
        从左侧选择或拖入一条成片开始。项目会自动保存在本机，之后可以从这里继续。
      </EmptyState>
      <div v-else class="recents__list" role="list">
        <div class="recents__cols small muted" aria-hidden="true">
          <span></span><span>项目</span><span class="col-stats">内容</span><span>状态</span><span class="col-time">更新时间</span>
        </div>
        <RecentRow
          v-for="p in recents"
          :key="p.project_id"
          role="listitem"
          :project="p"
          :opening="home.state.openingId === p.project_id"
          :current="session.project.value?.project_id === p.project_id"
          @open="actions.openProject(p.project_id)"
          @rename="rename(p)"
          @remove="removeRecent(p)"
        />
      </div>
    </section>

    <Transition name="fade">
      <div v-if="dragging" class="dropmask" aria-hidden="true">
        <div class="dropmask__card">
          <Upload :size="26" :stroke-width="1.5" />
          <p>松开以导入视频</p>
          <p class="small muted">一次一条成片；拖入多个文件时会请你选择</p>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.home {
  height: 100%;
  display: grid;
  grid-template-columns: minmax(340px, 400px) minmax(0, 1fr);
  gap: var(--gap);
  padding: 0 var(--gap) var(--gap);
  min-height: 0;
  position: relative;
}
.home__import {
  padding: 24px 22px 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  background: var(--bg-panel);
  border-radius: var(--r-4);
  box-shadow: var(--panel-edge);
}
.home__title {
  font-size: var(--fs-18);
  font-weight: var(--fw-semibold);
}
.home__lead {
  font-size: var(--fs-13);
  margin-top: -8px;
}
.drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 30px 16px 24px;
  border: 1.5px dashed var(--line-strong);
  border-radius: var(--r-3);
  background: var(--bg-well);
  transition: border-color var(--dur-select) var(--ease-standard);
  text-align: center;
}
.drop__icon {
  color: var(--text-3);
}
.drop__title {
  font-weight: var(--fw-medium);
}
.drop__hint {
  color: var(--text-3);
  margin-bottom: 8px;
}
.queue {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.queue__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px 4px 8px;
  background: var(--bg-raised);
  border-radius: var(--r-2);
  font-size: var(--fs-13);
}
.queue__remove {
  color: var(--text-3);
  padding: 4px;
  border-radius: var(--r-1);
}
.queue__remove:hover {
  color: var(--text-1);
  background: var(--bg-control);
}
.mini {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--bg-raised);
  border: 1px solid var(--line);
  border-radius: var(--r-2);
  font-size: var(--fs-13);
}
.mini__body {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 6px;
}
.samples {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.samples__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}
.sample {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 11px;
  border-radius: var(--r-3);
  transition:
    background-color var(--dur-press),
    color var(--dur-press),
    transform var(--dur-spring) var(--ease-spring);
  background: var(--bg-raised);
  border: 1px solid var(--line-subtle);
  text-align: left;
  font-size: var(--fs-13);
  min-width: 0;
  color: var(--text-2);
}
.sample:hover:not(:disabled) {
  background: var(--bg-control);
  color: var(--text-1);
}
.sample:active:not(:disabled) {
  transform: scale(0.97);
}
.sample:disabled {
  opacity: 0.45;
}
.sample__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.steps {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--text-3);
  padding-top: 8px;
}
.steps li {
  display: flex;
  align-items: center;
  gap: 8px;
}
.steps__n {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1px solid var(--line-strong);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--fs-11);
}
.home__recents {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 22px 22px 14px;
  gap: 12px;
  background: var(--bg-panel);
  border-radius: var(--r-4);
  box-shadow: var(--panel-edge);
}
.recents__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.recents__title {
  font-size: var(--fs-16);
  font-weight: var(--fw-semibold);
}
.recents__error {
  display: grid;
  gap: 8px;
}
.recents__loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-3);
  padding: 16px 8px;
}
.recents__list {
  overflow-y: auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0 -8px;
  padding: 0 8px;
}
.recents__cols {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr) 150px 108px 92px 28px;
  gap: 14px;
  padding: 0 14px 6px 8px;
  border-bottom: 1px solid var(--line-subtle);
  margin-bottom: 4px;
}
.col-time {
  text-align: right;
}
@media (max-width: 1280px) {
  .recents__cols {
    grid-template-columns: 72px minmax(0, 1fr) 108px 80px 28px;
  }
  .col-stats {
    display: none;
  }
  .home {
    grid-template-columns: minmax(300px, 340px) minmax(0, 1fr);
  }
}
.dropmask {
  position: absolute;
  inset: 0 var(--gap) var(--gap);
  z-index: var(--z-drawer);
  border: 2px dashed var(--accent);
  border-radius: var(--r-4);
  background: rgba(10, 10, 10, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.dropmask__card {
  display: grid;
  justify-items: center;
  gap: 6px;
  color: var(--text-1);
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--dur-select) var(--ease-out);
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
