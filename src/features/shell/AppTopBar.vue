<script setup lang="ts">
import { ArrowLeft, Check, Keyboard, ListChecks, Redo2, Settings, Undo2, Upload, FlaskConical, Film } from 'lucide-vue-next'
import { computed, nextTick, ref } from 'vue'
import { useActions, useApp } from '@/app/context'
import IconButton from '@/components/IconButton.vue'
import UiButton from '@/components/UiButton.vue'
import UiSpinner from '@/components/UiSpinner.vue'
import { countBatch } from '@/domain/jobStates'
import SaveIndicator from './SaveIndicator.vue'

const ctx = useApp()
const actions = useActions()
const { ui, session, tasks, adapter } = ctx
const project = session.project
const editing = ref(false)
const draft = ref('')
const nameInput = ref<HTMLInputElement>()
const composing = ref(false)

const exportable = computed(() => session.timeline.value?.clips.filter((c) => c.export_selected).length ?? 0)
const pendingCount = computed(() => session.pendingCuts.value.length)

const taskSummary = computed(() => {
  const b = tasks.activeBatch.value ?? tasks.latestBatch.value
  if (!b) return null
  const c = countBatch(b)
  const active = b.state === 'running' || b.state === 'pause_requested' || b.state === 'stop_requested'
  return { active, done: c.succeeded, total: c.total, failed: c.failed, state: b.state, interrupted: b.state === 'interrupted' || c.commitUnknown > 0 }
})

/** Workflow stepper (direction C): the main navigation of a project. */
const steps = computed(() => {
  const r = ui.state.route
  const review = r === 'editor' && ui.state.editorMode === 'review'
  const t = taskSummary.value
  return [
    { id: 'import', n: 1, label: '导入分析', done: true, active: false, badge: null as number | null, hint: '已完成镜头分析' },
    { id: 'review', n: 2, label: '检查切点', done: pendingCount.value === 0, active: review, badge: pendingCount.value || null, hint: pendingCount.value ? `${pendingCount.value} 处切点待检查` : '切点已全部检查' },
    { id: 'edit', n: 3, label: '片段与封面', done: false, active: r === 'editor' && !review, badge: null, hint: '设置片段、封面与音频' },
    { id: 'export', n: 4, label: '导出', done: !!t && !t.active && t.failed === 0 && t.done === t.total, active: r === 'tasks', badge: null, hint: t ? `已完成 ${t.done}/${t.total}` : '确认导出 MP4 + LIVP' },
  ]
})
function goStep(id: string) {
  if (id === 'review') {
    ui.state.route = 'editor'
    actions.startReview()
  } else if (id === 'edit') {
    ui.state.route = 'editor'
    ui.state.editorMode = 'edit'
  } else if (id === 'export') {
    if (tasks.batches.value.length) ui.state.route = 'tasks'
    else actions.openExport()
  }
}

async function startRename() {
  if (!project.value) return
  draft.value = project.value.name
  editing.value = true
  await nextTick()
  nameInput.value?.select()
}
async function commitRename() {
  if (!editing.value) return
  editing.value = false
  const v = draft.value.trim()
  if (!v || v === project.value?.name) return
  try {
    await session.rename(v)
    ui.toast('已重命名项目。源视频与已导出文件的名称不变。', { timeout: 3000 })
  } catch (e) {
    ui.toast((e as Error).message, { tone: 'danger' })
  }
}
function onNameKey(e: KeyboardEvent) {
  if (composing.value || e.isComposing) return
  if (e.key === 'Enter') commitRename()
  if (e.key === 'Escape') {
    e.stopPropagation()
    editing.value = false
  }
}
</script>

<template>
  <header class="topbar">
    <div class="topbar__left">
      <template v-if="project && ui.state.route !== 'home'">
        <IconButton :icon="ArrowLeft" label="返回首页（项目与最近记录）" @click="actions.goHome()" />
        <span class="topbar__mark" aria-hidden="true"><Film :size="16" :stroke-width="2.2" /></span>
        <div class="topbar__project">
          <input
            v-if="editing"
            ref="nameInput"
            v-model="draft"
            class="topbar__name-input"
            aria-label="项目名称"
            maxlength="80"
            @keydown="onNameKey"
            @blur="commitRename"
            @compositionstart="composing = true"
            @compositionend="composing = false"
          />
          <button v-else type="button" class="topbar__name truncate" v-tip="'点击重命名项目（只修改显示名称，源视频和已导出文件不变）'" @click="startRename">
            {{ project.name }}
          </button>
          <SaveIndicator />
        </div>
      </template>
      <div v-else class="topbar__brand">
        <span class="topbar__mark" aria-hidden="true"><Film :size="16" :stroke-width="2.2" /></span>
        <span class="topbar__brand-name">Video2LivePhoto</span>
      </div>
      <span v-if="adapter.mode === 'demo'" class="demo-badge" v-tip="'所有项目、分析、保存、导出与校验结果均为模拟'"><FlaskConical :size="12" /> 演示</span>
    </div>

    <nav v-if="project && ui.state.route !== 'home'" class="steps" aria-label="制作流程">
      <ol>
        <li v-for="(st, i) in steps" :key="st.id" :class="{ done: st.done, active: st.active }">
          <button type="button" class="step" :disabled="st.id === 'import'" :aria-current="st.active ? 'step' : undefined" v-tip="st.hint" @click="goStep(st.id)">
            <span class="step__dot">
              <Transition name="step-flip" mode="out-in">
                <Check v-if="st.done && !st.active" key="d" :size="13" :stroke-width="3" />
                <span v-else key="n">{{ st.n }}</span>
              </Transition>
            </span>
            <span class="step__label">{{ st.label }}</span>
            <Transition name="step-flip" mode="out-in"><b v-if="st.badge" :key="st.badge" class="step__badge num">{{ st.badge }}</b></Transition>
          </button>
          <span v-if="i < steps.length - 1" class="step__line" aria-hidden="true"><i :style="{ transform: `scaleX(${st.done ? 1 : 0})` }"></i></span>
        </li>
      </ol>
      <span v-if="session.state.pending" class="topbar__pending small" role="status">
        <UiSpinner :size="10" />{{ session.state.pending.phase === 'requested' ? '已请求' : '正在应用' }}：{{ session.state.pending.label }}
      </span>
    </nav>

    <div class="topbar__right">
      <template v-if="project && ui.state.route !== 'home'">
        <IconButton
          :icon="Undo2"
          :label="project.history.can_undo ? `撤销：${project.history.undo_label}` : '撤销'"
          kbd="Ctrl+Z"
          :disabled="!project.history.can_undo || ui.state.route !== 'editor'"
          :disabled-reason="ui.state.route !== 'editor' ? '在编辑页可用' : '没有可撤销的操作'"
          @click="session.undo()"
        />
        <IconButton
          :icon="Redo2"
          :label="project.history.can_redo ? `重做：${project.history.redo_label}` : '重做'"
          kbd="Ctrl+Shift+Z"
          :disabled="!project.history.can_redo || ui.state.route !== 'editor'"
          :disabled-reason="ui.state.route !== 'editor' ? '在编辑页可用' : '没有可重做的操作'"
          @click="session.redo()"
        />
        <button
          type="button"
          class="tasks-btn"
          :class="{ 'is-active': ui.state.route === 'tasks' }"
          :aria-label="taskSummary ? `任务与结果：已完成 ${taskSummary.done}/${taskSummary.total}${taskSummary.failed ? `，失败 ${taskSummary.failed}` : ''}` : '任务与结果'"
          @click="ui.state.route = ui.state.route === 'tasks' ? 'editor' : 'tasks'"
        >
          <UiSpinner v-if="taskSummary?.active" :size="12" />
          <ListChecks v-else :size="15" :stroke-width="1.75" aria-hidden="true" />
          <span>任务</span>
          <span v-if="taskSummary" class="tasks-btn__count num">{{ taskSummary.done }}/{{ taskSummary.total }}</span>
          <span v-if="taskSummary?.failed" class="tasks-btn__fail num">{{ taskSummary.failed }} 失败</span>
          <span v-else-if="taskSummary?.interrupted" class="tasks-btn__warn">待恢复</span>
        </button>
      </template>
      <IconButton :icon="Keyboard" label="快捷键说明" kbd="?" @click="ui.dialogs.shortcuts.value = true" />
      <IconButton :icon="Settings" label="设置与诊断" :pressed="ui.state.route === 'settings'" @click="ui.state.route = ui.state.route === 'settings' ? (project ? 'editor' : 'home') : 'settings'" />
      <UiButton
        v-if="project && ui.state.route !== 'home'"
        variant="primary"
        size="lg"
        :icon="Upload"
        :disabled="exportable === 0"
        disabled-reason="没有参与导出的片段"
        @click="actions.openExport()"
      >
        导出 <span class="num topbar__export-count">{{ exportable }}</span>
      </UiButton>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 16px;
  padding: 0 14px 0 10px;
  background: var(--bg-app);
  min-width: 0;
}
.topbar__left,
.topbar__right {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.topbar__right {
  justify-content: flex-end;
  grid-column: 3;
}
.topbar__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-left: 4px;
}
.topbar__mark {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--brand);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.topbar__brand-name {
  font-weight: var(--fw-bold);
  letter-spacing: 0.01em;
}
.topbar__project {
  display: flex;
  flex-direction: column;
  min-width: 0;
  margin-left: 4px;
}
.topbar__name {
  font-weight: var(--fw-bold);
  font-size: var(--fs-14);
  padding: 1px 6px;
  margin-left: -6px;
  border-radius: var(--r-1);
  max-width: 260px;
  text-align: left;
}
.topbar__name:hover {
  background: var(--bg-control);
}
.topbar__project :deep(.save) {
  font-size: var(--fs-11);
}
.topbar__name-input {
  height: 26px;
  width: 240px;
  padding: 0 6px;
  border: 0;
  border-radius: var(--r-1);
  background: var(--bg-control);
  box-shadow: 0 0 0 2px var(--accent);
  font-weight: var(--fw-bold);
}
.steps {
  position: relative;
}
.steps ol {
  display: flex;
  align-items: center;
  padding: 5px 8px;
  border-radius: var(--r-3);
  background: var(--bg-panel);
  box-shadow: var(--panel-edge);
}
.steps li {
  display: flex;
  align-items: center;
}
.step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: var(--r-2);
  color: var(--text-3);
  font-weight: var(--fw-medium);
  font-size: var(--fs-13);
  transition: background-color var(--dur-press) var(--ease-standard), color var(--dur-select) var(--ease-standard);
}
.step:hover:not(:disabled) {
  background: var(--bg-control);
  color: var(--text-1);
}
.step:disabled {
  cursor: default;
}
.done .step {
  color: var(--text-2);
}
.active .step {
  color: var(--text-1);
}
.step__dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: var(--fs-12);
  font-weight: var(--fw-bold);
  box-shadow: inset 0 0 0 1.5px var(--text-3);
  transition:
    background-color var(--dur-select) var(--ease-standard),
    box-shadow var(--dur-select) var(--ease-standard),
    transform var(--dur-spring) var(--ease-spring);
}
.done .step__dot {
  background: var(--success);
  color: #04200a;
  box-shadow: none;
}
.active .step__dot {
  background: var(--primary);
  color: var(--primary-text);
  box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.12);
}
.step:active:not(:disabled) .step__dot {
  transform: scale(0.85);
}
.step__badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--warning);
  color: #1f1a00;
  font-size: var(--fs-11);
  display: inline-grid;
  place-items: center;
}
.step__line {
  width: 28px;
  height: 2px;
  margin: 0 2px;
  border-radius: 1px;
  background: rgba(255, 255, 255, 0.12);
  overflow: hidden;
}
.step__line i {
  display: block;
  height: 100%;
  background: var(--success);
  transform-origin: left;
  transition: transform 600ms var(--ease-out);
}
.step-flip-enter-active,
.step-flip-leave-active {
  transition:
    transform var(--dur-select) var(--ease-spring),
    opacity var(--dur-press);
}
.step-flip-enter-from {
  transform: translateY(6px) scale(0.6);
  opacity: 0;
}
.step-flip-leave-to {
  transform: translateY(-6px);
  opacity: 0;
}
.topbar__pending {
  position: absolute;
  top: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-2);
  background: var(--bg-overlay);
  padding: 4px 10px;
  border-radius: var(--r-2);
  box-shadow: var(--shadow-pop);
  white-space: nowrap;
  z-index: var(--z-popover);
}
.demo-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 20px;
  padding: 0 7px;
  border: 1px dashed rgba(201, 154, 90, 0.55);
  color: var(--demo);
  border-radius: var(--r-1);
  font-size: var(--fs-11);
  font-weight: var(--fw-medium);
  white-space: nowrap;
  flex: none;
  margin-left: 4px;
}
.tasks-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: var(--h-md);
  padding: 0 10px;
  border-radius: var(--r-2);
  color: var(--text-2);
  font-size: var(--fs-13);
  white-space: nowrap;
  transition: background-color var(--dur-press) var(--ease-standard), transform var(--dur-spring) var(--ease-spring);
}
.tasks-btn:hover {
  background: var(--bg-control);
  color: var(--text-1);
}
.tasks-btn:active {
  transform: scale(0.94);
}
.tasks-btn.is-active {
  background: var(--accent-soft);
  color: var(--text-1);
}
.tasks-btn__count {
  color: var(--text-3);
  font-size: var(--fs-12);
}
.tasks-btn__fail {
  color: var(--danger);
  font-size: var(--fs-12);
}
.tasks-btn__warn {
  color: var(--warning);
  font-size: var(--fs-12);
}
.topbar__export-count {
  opacity: 0.6;
  margin-left: 2px;
}
@media (max-width: 1320px) {
  .step__label {
    display: none;
  }
  .active .step__label {
    display: inline;
  }
  .topbar__name {
    max-width: 160px;
  }
  .tasks-btn__count {
    display: none;
  }
}
</style>
