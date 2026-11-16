<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useApp } from '@/app/context'
import type { ImportColorSelection } from '@/domain/types'
import UiButton from '@/components/UiButton.vue'
import UiDialog from '@/components/UiDialog.vue'
import { colorSummary, streamSummary } from '@/features/editor/mediaText'

const { ui } = useApp()
const d = ui.dialogs.colorSelect
const chosen = ref<ImportColorSelection | null>(null)

watch(d, () => (chosen.value = null))

const stream = computed(() => {
  if (!d.value) return null
  return d.value.probe.media.video_streams.find((item) => item.stream_index === d.value?.streamIndex) ?? null
})

const choices: { value: ImportColorSelection; title: string; detail: string }[] = [
  { value: 'sdr_rec709', title: 'SDR / Rec.709', detail: '普通 SDR 视频，按 Rec.709 解释并在导出时标记为 Rec.709。' },
  { value: 'hdr_pq', title: 'HDR10 / PQ', detail: 'HDR10 常用的 PQ 曲线，按 BT.2020 + PQ 解释。' },
  { value: 'hdr_hlg', title: 'HDR / HLG', detail: '手机和广播常见的 HLG 曲线，按 BT.2020 + HLG 解释。' },
]
</script>

<template>
  <UiDialog
    :open="!!d"
    title="确认源视频色彩"
    description="导入时没有读到完整的色彩元数据。请选择源视频实际类型，之后导出会沿用这个选择。"
    size="md"
    :dismiss-on-scrim="false"
    @close="d?.resolve(null)"
  >
    <div v-if="stream" class="color-select__source small">
      <span>{{ streamSummary(stream) }}</span>
      <span>探测结果：{{ colorSummary(stream.color) }}</span>
    </div>
    <div class="choices" role="radiogroup" aria-label="源视频色彩类型">
      <button
        v-for="item in choices"
        :key="item.value"
        type="button"
        role="radio"
        class="choice"
        :aria-checked="chosen === item.value"
        @click="chosen = item.value"
      >
        <span class="choice__radio" aria-hidden="true"></span>
        <span class="choice__body">
          <strong>{{ item.title }}</strong>
          <span class="small muted">{{ item.detail }}</span>
        </span>
      </button>
    </div>
    <p class="small muted color-select__note">如果不确定，先取消导入并在剪辑软件或相机资料中确认；程序不会替你猜测。</p>
    <template #footer>
      <UiButton variant="ghost" @click="d?.resolve(null)">取消导入</UiButton>
      <UiButton variant="primary" :disabled="chosen === null" disabled-reason="请先选择源视频色彩" @click="d && chosen !== null && d.resolve(chosen)">按此类型导入</UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.color-select__source {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin-bottom: 12px;
  color: var(--text-3);
}
.choices {
  display: grid;
  gap: 8px;
}
.choice {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  width: 100%;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-2);
  text-align: left;
  background: var(--bg-raised);
}
.choice:hover {
  border-color: var(--line-strong);
}
.choice[aria-checked='true'] {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.choice__radio {
  width: 14px;
  height: 14px;
  flex: none;
  margin-top: 3px;
  border: 1.5px solid var(--line-strong);
  border-radius: 50%;
}
.choice[aria-checked='true'] .choice__radio {
  border: 4px solid var(--accent);
}
.choice__body {
  display: grid;
  gap: 3px;
}
.color-select__note {
  margin-top: 12px;
}
</style>
