<script setup lang="ts">
import { FlaskConical, X, RotateCcw } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { useActions, useApp } from '@/app/context'
import type { DemoControl } from '@/adapters/demo/DemoAdapter'
import { DEMO_SCENARIOS, type DemoScenarioId } from '@/adapters/demo/meta'
import { FAULT_META, type BoolFault } from '@/adapters/demo/faults'
import UiButton from '@/components/UiButton.vue'
import UiCheckbox from '@/components/UiCheckbox.vue'
import UiSelect from '@/components/UiSelect.vue'

/** DEV ONLY – demo scenario switcher and fault injection. Never rendered in desktop mode. */
const { adapter, ui, session, tasks } = useApp()
const actions = useActions()
const demo = (adapter as unknown as { demo: DemoControl }).demo
const faults = ref({ ...demo.faults })
const tick = ref(0)
const groups = computed(() => [...new Set(FAULT_META.map((f) => f.group))])
const targets = computed(() => (tick.value, demo.jumpTargets()))
const stats = computed(() => (tick.value, demo.frameStats()))

function setFault(k: BoolFault, v: boolean) {
  demo.setFault(k, v)
  faults.value = { ...demo.faults }
}
function setSpeed(v: string) {
  demo.setFault('speed', Number(v))
  faults.value = { ...demo.faults }
}
function crash() {
  const p = session.project.value
  if (!p) return
  const hit = demo.simulateCrash(p.project_id)
  if (!hit) {
    ui.toast('当前项目没有运行中的导出任务，无法模拟导出中断。', { tone: 'warning' })
    return
  }
  session.close()
  tasks.detach()
  ui.state.route = 'home'
  ui.state.devPanelOpen = false
  ui.toast('已模拟意外退出并重新启动（演示）。重新打开该项目会显示恢复摘要。', { timeout: 6000 })
}
function injectOutOfOrder() {
  const b = tasks.activeBatch.value ?? tasks.latestBatch.value
  if (!b) return ui.toast('没有批次可注入事件', { tone: 'warning' })
  const j = b.jobs[0]
  // stale (older seq) + far-future (gap) events: the store must drop the first and resync on the second
  tasks._handle({ type: 'job_patch', project_id: b.project_id, batch_id: b.batch_id, seq: Math.max(1, b.seq - 3), job_id: j.job_id, attempt_id: null, patch: { stage: 'failed' } })
  tasks._handle({ type: 'job_patch', project_id: b.project_id, batch_id: b.batch_id, seq: b.seq + 50, job_id: j.job_id, attempt_id: null, patch: {} })
  ui.toast(`已注入旧事件与跳号事件：旧事件丢弃（累计 ${tasks.state.dropped}），跳号触发快照重同步`, { timeout: 5000 })
}
</script>

<template>
  <aside v-if="ui.state.devPanelOpen" class="dev" aria-label="演示场景面板">
    <header class="dev__head">
      <FlaskConical :size="14" />
      <strong>演示场景 · 仅开发可见</strong>
      <span class="grow"></span>
      <button type="button" class="dev__x" aria-label="关闭演示面板" @click="ui.state.devPanelOpen = false"><X :size="14" /></button>
    </header>
    <div class="dev__body">
      <section>
        <h4>场景预设</h4>
        <div class="dev__row">
          <UiSelect :model-value="demo.scenario" :options="DEMO_SCENARIOS.map((s) => ({ value: s.id, label: s.label }))" aria-label="场景" size="sm" @update:model-value="(v) => demo.reset(v as DemoScenarioId)" />
          <UiButton size="sm" :icon="RotateCcw" @click="demo.reset()">重置全部</UiButton>
        </div>
        <p class="dev__hint">重置会重新载入固定示例数据与默认故障开关，可重复。</p>
      </section>
      <section>
        <h4>直接打开项目</h4>
        <ul class="dev__targets">
          <li v-for="t in targets" :key="t.project_id">
            <button type="button" @click="actions.openProject(t.project_id)"><strong>{{ t.name }}</strong><span>{{ t.note }}</span></button>
          </li>
        </ul>
      </section>
      <section v-for="g in groups" :key="g">
        <h4>故障注入 · {{ g }}</h4>
        <div v-for="f in FAULT_META.filter((x) => x.group === g)" :key="f.key" class="dev__fault">
          <UiCheckbox small :checked="faults[f.key]" :label="f.label" @change="(v) => setFault(f.key, v)" />
          <span v-if="f.hint" class="dev__hint">{{ f.hint }}</span>
        </div>
      </section>
      <section>
        <h4>模拟动作</h4>
        <div class="dev__row">
          <UiSelect :model-value="String(faults.speed)" :options="['0.5', '1', '2', '4'].map((v) => ({ value: v, label: `速度 ×${v}` }))" aria-label="模拟速度" size="sm" @update:model-value="setSpeed" />
          <UiButton size="sm" :disabled="!session.project.value" @click="crash">模拟意外退出</UiButton>
        </div>
        <div class="dev__row">
          <UiButton size="sm" @click="demo.simulateCloseRequest()">模拟关闭窗口</UiButton>
          <UiButton size="sm" :disabled="!session.project.value" @click="injectOutOfOrder">注入乱序事件</UiButton>
        </div>
        <p class="dev__hint num">帧缓存：缩略图 {{ stats.thumb }}/{{ stats.capacity.thumb }} · 大图 {{ stats.full }}/{{ stats.capacity.full }} · 事件丢弃 {{ tasks.state.dropped }} · 重同步 {{ tasks.state.resyncs }} <button type="button" class="dev__link" @click="tick++">刷新</button></p>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.dev {
  position: fixed;
  right: 12px;
  bottom: calc(var(--statusbar-h) + 10px);
  top: calc(var(--topbar-h) + 10px);
  width: 340px;
  z-index: var(--z-devtools);
  display: flex;
  flex-direction: column;
  background: #1a1916;
  border: 1px dashed rgba(201, 154, 90, 0.55);
  border-radius: var(--r-3);
  box-shadow: var(--shadow-dialog);
  animation: v2-slide-in-right var(--dur-panel) var(--ease-out);
}
.dev__head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  color: var(--demo);
  font-size: var(--fs-13);
  border-bottom: 1px dashed rgba(201, 154, 90, 0.3);
}
.dev__x {
  color: var(--text-3);
  padding: 2px;
}
.dev__body {
  flex: 1;
  overflow-y: auto;
  padding: 6px 12px 12px;
  display: grid;
  gap: 12px;
  align-content: start;
}
.dev h4 {
  font-size: var(--fs-12);
  color: var(--text-3);
  margin: 6px 0;
  font-weight: var(--fw-semibold);
}
.dev__row {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-bottom: 6px;
}
.dev__hint {
  font-size: var(--fs-11);
  color: var(--text-3);
  line-height: 1.4;
}
.dev__fault {
  display: grid;
  gap: 0;
  margin-bottom: 4px;
}
.dev__fault .dev__hint {
  padding-left: 23px;
}
.dev__targets {
  display: grid;
  gap: 2px;
}
.dev__targets button {
  display: grid;
  gap: 1px;
  width: 100%;
  text-align: left;
  padding: 5px 8px;
  border-radius: var(--r-1);
  font-size: var(--fs-12);
}
.dev__targets button:hover {
  background: rgba(255, 255, 255, 0.05);
}
.dev__targets span {
  color: var(--text-3);
  font-size: var(--fs-11);
}
.dev__link {
  color: var(--demo);
  text-decoration: underline;
}
</style>
