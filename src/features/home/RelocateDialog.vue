<script setup lang="ts">
import { FileSearch, ShieldCheck } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useActions, useApp } from '@/app/context'
import type { FileRef } from '@/adapters/contract'
import type { DemoControl } from '@/adapters/demo/DemoAdapter'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import UiDialog from '@/components/UiDialog.vue'
import { toAppError } from '@/domain/errors'

/**
 * Source relocation. A same-named file is only a candidate: the backend identity check
 * (size + fingerprint + stream signature) must accept it before processing resumes.
 */
const { ui, adapter, home } = useApp()
const actions = useActions()
const d = ui.dialogs.relocate
const demo = (adapter as unknown as { demo?: DemoControl }).demo ?? null
const candidate = ref<{ ref: FileRef; path: string } | null>(null)
const checking = ref(false)
const result = ref<{ accepted: boolean; mismatch: string[] } | null>(null)
const fileInput = ref<HTMLInputElement>()
const candidates = computed(() => (d.value && demo ? demo.relocationCandidates(d.value.project_id) : []))

watch(d, () => {
  candidate.value = null
  result.value = null
})

async function choose() {
  if (adapter.mode === 'desktop') {
    const r = await adapter.media.pickVideo()
    if (r) pick({ ref: r, path: r.kind === 'desktop' ? r.display_path : r.name })
    return
  }
  fileInput.value?.click()
}
function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  ;(e.target as HTMLInputElement).value = ''
  if (f) pick({ ref: adapter.media.fromBrowserFile(f), path: f.name })
}
function pick(c: { ref: FileRef; path: string }) {
  candidate.value = c
  result.value = null
}
async function verify() {
  if (!d.value || !candidate.value) return
  checking.value = true
  try {
    const res = await adapter.projects.relocateSource(d.value.project_id, candidate.value.ref)
    result.value = { accepted: res.accepted, mismatch: res.mismatch }
    if (res.accepted) {
      const id = d.value.project_id
      d.value = null
      home.state.openError = null
      await home.loadRecents()
      ui.toast('身份核对通过，已恢复源视频关联。', { tone: 'success' })
      await actions.openProject(id)
    }
  } catch (e) {
    ui.toast(toAppError(e).message, { tone: 'danger' })
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <UiDialog :open="!!d" :title="d?.reason === 'changed' ? '原视频身份不一致' : '重新定位原视频'" :description="d?.name" size="md" @close="d = null">
    <div class="rel">
      <p class="secondary small">
        {{ d?.reason === 'changed' ? '原位置的文件与项目记录不一致，可能已被替换或重新导出。' : '项目记录的原视频位置已找不到文件。' }}
        请选择正确的原视频。切点、片段设置与审核记录都完整保留。
      </p>
      <UiBanner tone="info" compact>同名文件只是候选。后端会核对文件大小、内容指纹与视频流特征，全部一致才会恢复处理。源视频始终只读。</UiBanner>

      <div v-if="candidates.length" class="rel__cands">
        <p class="section-title">演示候选文件</p>
        <button v-for="c in candidates" :key="c.ref.ref_id" type="button" class="rel__cand" :aria-pressed="candidate?.ref.ref_id === c.ref.ref_id" @click="pick(c)">
          <FileSearch :size="14" aria-hidden="true" />
          <span class="truncate grow mono small">{{ c.path }}</span>
          <span class="small muted">{{ c.hint }}</span>
        </button>
      </div>
      <div class="row">
        <UiButton size="sm" @click="choose">浏览文件…</UiButton>
        <span v-if="candidate" class="small truncate">已选择：<span class="mono">{{ candidate.path }}</span></span>
        <input ref="fileInput" type="file" accept="video/mp4,video/quicktime,.mp4,.mov" class="sr-only" tabindex="-1" aria-hidden="true" @change="onFile" />
      </div>
      <div v-if="result && !result.accepted" class="rel__fail" role="alert">
        <p><strong>身份核对未通过，未关联此文件。</strong></p>
        <ul class="small">
          <li v-for="m in result.mismatch" :key="m">{{ m }}</li>
        </ul>
      </div>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="d = null">取消</UiButton>
      <UiButton variant="primary" :icon="ShieldCheck" :disabled="!candidate" disabled-reason="请先选择候选文件" :loading="checking" loading-label="正在核对身份…" @click="verify">核对并关联</UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.rel {
  display: grid;
  gap: 12px;
}
.rel__cands {
  display: grid;
  gap: 4px;
}
.rel__cand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: var(--r-2);
  border: 1px solid var(--line);
  text-align: left;
}
.rel__cand:hover {
  background: var(--bg-raised);
}
.rel__cand[aria-pressed='true'] {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.rel__fail {
  padding: 10px 12px;
  border-radius: var(--r-2);
  border: 1px solid rgba(226, 99, 91, 0.35);
  background: var(--danger-soft);
  display: grid;
  gap: 4px;
}
.rel__fail ul {
  list-style: disc;
  padding-left: 18px;
  color: var(--text-2);
}
</style>
