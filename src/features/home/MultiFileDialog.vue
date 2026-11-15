<script setup lang="ts">
import { ref, watch } from 'vue'
import { useApp } from '@/app/context'
import UiButton from '@/components/UiButton.vue'
import UiDialog from '@/components/UiDialog.vue'
import UiBanner from '@/components/UiBanner.vue'
import { formatBytes } from '@/domain/time'
import { useImport } from './useImport'

const { ui, home, adapter } = useApp()
const { importRef } = useImport()
const files = ui.dialogs.multiFile
const chosen = ref(0)
watch(files, () => (chosen.value = 0))

function close() {
  files.value = null
}
function useOne() {
  const f = files.value?.[chosen.value]
  close()
  if (f) void importRef(adapter.media.fromBrowserFile(f))
}
function separate() {
  const list = files.value ?? []
  close()
  const [first, ...rest] = list
  home.state.queue.push(...rest)
  if (first) void importRef(adapter.media.fromBrowserFile(first))
}
</script>

<template>
  <UiDialog :open="!!files" :title="`拖入了 ${files?.length ?? 0} 个文件`" description="每个项目处理一条已剪辑完成的成片。请选择一个视频，或为每个视频分别建立项目。" size="md" @close="close">
    <div class="mf" role="radiogroup" aria-label="选择一个视频">
      <button v-for="(f, i) in files ?? []" :key="f.name + i" type="button" role="radio" class="mf__item" :aria-checked="chosen === i" @click="chosen = i">
        <span class="mf__radio" aria-hidden="true"></span>
        <span class="truncate grow">{{ f.name }}</span>
        <span class="small muted num">{{ formatBytes(f.size) }}</span>
      </button>
    </div>
    <UiBanner tone="info" compact class="mf__note">「分别建立项目」会先分析第一个文件，其余文件放入首页的待导入列表，完成后逐个开始。</UiBanner>
    <template #footer>
      <UiButton variant="ghost" @click="close">取消</UiButton>
      <UiButton @click="separate">分别建立项目</UiButton>
      <UiButton variant="primary" @click="useOne">用所选视频新建项目</UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.mf {
  display: grid;
  gap: 4px;
  max-height: 280px;
  overflow: auto;
}
.mf__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--r-2);
  text-align: left;
  font-size: var(--fs-13);
  border: 1px solid transparent;
}
.mf__item:hover {
  background: var(--bg-raised);
}
.mf__item[aria-checked='true'] {
  border-color: var(--accent-line);
  background: var(--accent-soft);
}
.mf__radio {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1.5px solid var(--line-strong);
  flex: none;
}
.mf__item[aria-checked='true'] .mf__radio {
  border: 4px solid var(--accent);
}
.mf__note {
  margin-top: 12px;
}
</style>
