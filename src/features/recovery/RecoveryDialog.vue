<script setup lang="ts">
import { CircleCheck, RotateCcw, Recycle, FolderSearch, TriangleAlert } from 'lucide-vue-next'
import { ref, watch } from 'vue'
import { useApp } from '@/app/context'
import type { RecoveryProgress, RecoverySummary } from '@/adapters/contract'
import ErrorPanel from '@/components/ErrorPanel.vue'
import UiButton from '@/components/UiButton.vue'
import UiDialog from '@/components/UiDialog.vue'
import UiProgress from '@/components/UiProgress.vue'
import { isAbort, toAppError } from '@/domain/errors'
import { padIndex } from '@/domain/naming'
import type { AppError } from '@/domain/types'

/** Recovery: inspect (with progress) → summary → encoding resumes only after the user clicks continue. */
const { ui, adapter, tasks, session } = useApp()
const d = ui.dialogs.recovery
const progress = ref<RecoveryProgress | null>(null)
const summary = ref<RecoverySummary | null>(null)
const error = ref<AppError | null>(null)
const continuing = ref(false)
let ctrl: AbortController | null = null

async function inspect() {
  const pid = d.value?.project_id
  if (!pid) return
  ctrl?.abort()
  const c = (ctrl = new AbortController())
  progress.value = null
  summary.value = null
  error.value = null
  try {
    const res = await adapter.recovery.inspect(pid, (p) => c === ctrl && (progress.value = p), c.signal)
    if (c === ctrl) summary.value = res
  } catch (e) {
    if (c === ctrl && !isAbort(e)) error.value = toAppError(e, { scope: { project_id: pid, stage: 'recovery_inspect' } })
  }
}
watch(d, (v) => (v ? void inspect() : ctrl?.abort()))

async function continueRemaining() {
  const pid = d.value?.project_id
  if (!pid) return
  continuing.value = true
  try {
    const res = await tasks.once(`continue:${pid}`, (rid) => adapter.recovery.continueRemaining(pid, rid))
    if (!res) return
    const b = await adapter.tasks.getBatch(res.batch_id)
    tasks._handle({ type: 'batch_snapshot', project_id: pid, batch: b })
    session.setRecoveryPending(false)
    d.value = null
    ui.state.tasksTab = 'queue'
    ui.state.route = 'tasks'
    ui.toast('已确认恢复，剩余片段开始处理。已核实成功的文件不会重新生成。', { tone: 'success' })
  } catch (e) {
    ui.toast(toAppError(e).message, { tone: 'danger' })
  } finally {
    continuing.value = false
  }
}
</script>

<template>
  <UiDialog :open="!!d" title="恢复上次中断的导出" description="应用上次意外退出。正在核对记录与文件，确认前不会开始任何编码。" size="lg" :dismiss-on-scrim="false" @close="d = null">
    <div class="rec">
      <div v-if="!summary && !error" class="rec__check">
        <p class="small secondary">正在检查：{{ progress?.current ?? '读取恢复记录…' }}</p>
        <UiProgress :value="progress ? progress.checked : null" :max="progress?.total ?? 1" label="恢复检查进度" />
        <p v-if="progress" class="small muted num">{{ progress.checked }} / {{ progress.total }} 个片段</p>
      </div>
      <ErrorPanel v-if="error" :error="error" context="恢复检查" @action="(a) => a === 'retry' && inspect()" />
      <template v-if="summary">
        <section class="rec__sec">
          <h3 class="rec__h"><CircleCheck :size="15" class="ok" /> 已核实成功 {{ summary.verified_success.length }} 个</h3>
          <p class="small muted">{{ summary.verified_success.map((c) => padIndex(c.display_index)).join('、') || '无' }} · 文件完整，保留不动。</p>
        </section>
        <section class="rec__sec">
          <h3 class="rec__h"><RotateCcw :size="15" class="warn" /> 需要重做 {{ summary.needs_redo.length }} 个</h3>
          <ul class="small rec__list">
            <li v-for="c in summary.needs_redo.slice(0, 8)" :key="c.clip_id"><span class="mono">{{ padIndex(c.display_index) }}</span> {{ c.reason }}</li>
            <li v-if="summary.needs_redo.length > 8" class="muted">… 另 {{ summary.needs_redo.length - 8 }} 个</li>
          </ul>
        </section>
        <section v-if="summary.commit_unknown.length" class="rec__sec">
          <h3 class="rec__h"><TriangleAlert :size="15" class="warn" /> 提交阶段中断 {{ summary.commit_unknown.length }} 个</h3>
          <ul class="small rec__list">
            <li v-for="c in summary.commit_unknown" :key="c.clip_id"><span class="mono">{{ padIndex(c.display_index) }}</span> {{ c.detail }}</li>
          </ul>
        </section>
        <section class="rec__sec">
          <h3 class="rec__h"><Recycle :size="15" /> 可复用的中间结果 {{ summary.reusable_intermediate.length }} 个</h3>
          <p class="small muted">{{ summary.reusable_intermediate.map((c) => `${padIndex(c.display_index)}：${c.what}`).join('；') || '无' }}</p>
        </section>
        <section class="rec__sec">
          <h3 class="rec__h"><FolderSearch :size="15" /> 需要重新定位的文件</h3>
          <p class="small muted">{{ summary.needs_relocate.map((r) => `${r.label}：${r.path_display}`).join('；') || '无需重新定位' }}</p>
        </section>
        <section class="rec__sec">
          <h3 class="rec__h">待你确认的动作</h3>
          <ul class="small rec__list"><li v-for="a in summary.pending_actions" :key="a">{{ a }}</li></ul>
        </section>
      </template>
    </div>
    <template #footer>
      <span class="small muted grow">稍后处理会保留恢复记录，编辑页顶部会持续提示。</span>
      <UiButton variant="ghost" @click="d = null">稍后处理</UiButton>
      <UiButton variant="primary" :disabled="!summary?.batch_id" disabled-reason="检查完成后可继续" :loading="continuing" loading-label="正在提交…" @click="continueRemaining">继续剩余任务</UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.rec {
  display: grid;
  gap: 4px;
}
.rec__check {
  display: grid;
  gap: 8px;
  padding: 8px 0;
}
.rec__sec {
  padding: 10px 0;
  border-bottom: 1px solid var(--line-subtle);
  display: grid;
  gap: 4px;
}
.rec__h {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-13);
  font-weight: var(--fw-semibold);
}
.rec__list {
  display: grid;
  gap: 2px;
  color: var(--text-2);
}
.ok {
  color: var(--success);
}
.warn {
  color: var(--warning);
}
</style>
