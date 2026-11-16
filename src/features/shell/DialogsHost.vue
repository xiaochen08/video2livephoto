<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useApp } from '@/app/context'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import UiDialog from '@/components/UiDialog.vue'
import UiTextField from '@/components/UiTextField.vue'
import { SHORTCUTS } from '@/app/shortcuts'
import AnalysisDialog from '@/features/analysis/AnalysisDialog.vue'
import CoverDialog from '@/features/cover/CoverDialog.vue'
import ExportDialog from '@/features/export/ExportDialog.vue'
import MultiFileDialog from '@/features/home/MultiFileDialog.vue'
import RelocateDialog from '@/features/home/RelocateDialog.vue'
import StreamSelectDialog from '@/features/home/StreamSelectDialog.vue'
import ColorSelectDialog from '@/features/home/ColorSelectDialog.vue'
import RecoveryDialog from '@/features/recovery/RecoveryDialog.vue'

const { ui, session, tasks, adapter } = useApp()

const d = ui.dialogs

const promptValue = ref('')
watch(d.prompt, (p) => (promptValue.value = p?.value ?? ''))
const promptError = computed(() => d.prompt.value?.validate?.(promptValue.value) ?? null)

const scopes = computed(() => [...new Set(SHORTCUTS.map((s) => s.scope))])
const quitting = ref(false)
const quitNote = ref<string | null>(null)

async function quit(save: boolean) {
  quitting.value = true
  try {
    if (save && session.dirty.value) await session.save()
    await adapter.app.quit()
    if (adapter.mode === 'demo') quitNote.value = '演示模式：已模拟退出流程，浏览器不会关闭桌面进程。'
    else d.closeApp.value = false
  } catch (e) {
    ui.toast((e as Error).message, { tone: 'danger' })
  } finally {
    quitting.value = false
  }
}
watch(d.closeApp, () => (quitNote.value = null))
</script>

<template>
  <AnalysisDialog />
  <StreamSelectDialog />
  <ColorSelectDialog />
  <MultiFileDialog />
  <RelocateDialog />
  <ExportDialog />
  <CoverDialog />
  <RecoveryDialog />

  <UiDialog :open="!!d.confirm.value" :title="d.confirm.value?.title ?? ''" size="sm" @close="d.confirm.value?.resolve(false)">
    <p>{{ d.confirm.value?.message }}</p>
    <p v-if="d.confirm.value?.detail" class="small muted host__detail">{{ d.confirm.value.detail }}</p>
    <template #footer>
      <UiButton variant="ghost" @click="d.confirm.value?.resolve(false)">{{ d.confirm.value?.cancelLabel ?? '取消' }}</UiButton>
      <UiButton :variant="d.confirm.value?.tone === 'danger' ? 'danger' : 'primary'" data-autofocus @click="d.confirm.value?.resolve(true)">{{ d.confirm.value?.confirmLabel }}</UiButton>
    </template>
  </UiDialog>

  <UiDialog :open="!!d.prompt.value" :title="d.prompt.value?.title ?? ''" size="sm" @close="d.prompt.value?.resolve(null)">
    <UiTextField v-model="promptValue" :label="d.prompt.value?.label" :hint="d.prompt.value?.hint" :error="promptError" data-autofocus @commit="!promptError && d.prompt.value?.resolve(promptValue)" />
    <template #footer>
      <UiButton variant="ghost" @click="d.prompt.value?.resolve(null)">取消</UiButton>
      <UiButton variant="primary" :disabled="!!promptError" :disabled-reason="promptError" @click="d.prompt.value?.resolve(promptValue)">{{ d.prompt.value?.confirmLabel }}</UiButton>
    </template>
  </UiDialog>

  <UiDialog :open="!!d.leaveGuard.value" title="有未保存的修改" :description="d.leaveGuard.value ? `即将${d.leaveGuard.value.target}` : undefined" size="sm" @close="d.leaveGuard.value?.resolve('cancel')">
    <p>当前项目有尚未确认保存的编辑（编辑 v{{ session.project.value?.edit_version }}，已保存 v{{ session.project.value?.saved_edit_version }}）。</p>
    <UiBanner v-if="session.state.saveError" tone="danger" compact class="host__detail">上次保存失败：{{ session.state.saveError.message }}</UiBanner>
    <p v-if="tasks.activeBatch.value" class="small muted host__detail">正在运行的导出任务由后端管理，离开编辑页不会中断它，回到项目后可继续查看。</p>
    <template #footer>
      <UiButton variant="danger-ghost" @click="d.leaveGuard.value?.resolve('discard')">不保存离开</UiButton>
      <UiButton variant="ghost" @click="d.leaveGuard.value?.resolve('cancel')">取消</UiButton>
      <UiButton variant="primary" data-autofocus @click="d.leaveGuard.value?.resolve('save')">保存并离开</UiButton>
    </template>
  </UiDialog>

  <UiDialog :open="!!d.mergeConflict.value" title="合并后的音频设置" size="sm" :dismiss-on-scrim="false" @close="d.mergeConflict.value?.resolve(null)">
    <p>
      {{ d.mergeConflict.value?.kind === 'remove_cut' ? '删除这个切点会合并相邻两个片段' : `将合并 ${d.mergeConflict.value?.clip_ids.length} 个片段` }}，它们的音频设置不同：
      {{ d.mergeConflict.value?.source }} 个保留原声，{{ d.mergeConflict.value?.muted }} 个静音。请选择合并后的设置。
    </p>
    <template #footer>
      <UiButton variant="ghost" @click="d.mergeConflict.value?.resolve(null)">取消合并</UiButton>
      <UiButton @click="d.mergeConflict.value?.resolve('muted')">合并后静音</UiButton>
      <UiButton variant="primary" data-autofocus @click="d.mergeConflict.value?.resolve('source')">保留原声</UiButton>
    </template>
  </UiDialog>

  <UiDialog :open="d.shortcuts.value" title="快捷键" description="快捷键只在对应区域生效；输入文字、中文输入法组字或弹窗打开时，优先交给当前控件。" size="lg" @close="d.shortcuts.value = false">
    <div class="keys">
      <section v-for="sc in scopes" :key="sc">
        <h3 class="section-title">{{ sc }}</h3>
        <dl>
          <div v-for="k in SHORTCUTS.filter((x) => x.scope === sc)" :key="k.id" class="keys__row">
            <dt><span v-for="part in k.keys.split(' / ')" :key="part" class="kbd">{{ part }}</span></dt>
            <dd>{{ k.label }}<span v-if="k.note" class="small muted"> · {{ k.note }}</span></dd>
          </div>
        </dl>
      </section>
    </div>
  </UiDialog>

  <UiDialog :open="!!d.report.value" :title="d.report.value?.title ?? ''" size="lg" @close="d.report.value = null">
    <pre class="host__pre mono small">{{ d.report.value?.body }}</pre>
  </UiDialog>

  <UiDialog :open="d.closeApp.value" title="退出 Video2LivePhoto？" size="sm" :blocked-reason="quitting ? '正在处理' : null" @close="d.closeApp.value = false">
    <ul class="host__list small">
      <li v-if="session.dirty.value">当前项目有未保存的修改。</li>
      <li v-if="tasks.activeBatch.value">有导出任务正在运行。退出后正在处理的片段会中断，已成功的文件保留，下次打开时显示恢复摘要并由你确认是否继续。</li>
      <li v-if="!session.dirty.value && !tasks.activeBatch.value">没有未保存修改或运行中的任务。</li>
    </ul>
    <UiBanner v-if="quitNote" tone="demo" compact class="host__detail">{{ quitNote }}</UiBanner>
    <template #footer>
      <UiButton variant="ghost" @click="d.closeApp.value = false">取消</UiButton>
      <UiButton v-if="session.dirty.value" variant="danger-ghost" :disabled="quitting" @click="quit(false)">不保存退出</UiButton>
      <UiButton variant="primary" :loading="quitting" loading-label="正在退出…" @click="quit(true)">{{ session.dirty.value ? '保存并退出' : '退出' }}</UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.host__detail {
  margin-top: 10px;
}
.host__pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: var(--bg-well);
  padding: 12px;
  border-radius: var(--r-2);
  user-select: text;
}
.host__list {
  list-style: disc;
  padding-left: 18px;
  display: grid;
  gap: 6px;
  color: var(--text-2);
}
.keys {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px 28px;
}
.keys section {
  display: grid;
  gap: 6px;
  align-content: start;
}
.keys__row {
  display: grid;
  grid-template-columns: 150px 1fr;
  gap: 10px;
  align-items: baseline;
  font-size: var(--fs-13);
  padding: 3px 0;
}
.keys__row dt {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
