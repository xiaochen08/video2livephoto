<script setup lang="ts">
import { ref, watch } from 'vue'
import { useApp } from '@/app/context'
import UiButton from '@/components/UiButton.vue'
import UiDialog from '@/components/UiDialog.vue'
import { colorSummary, streamSummary } from '@/features/editor/mediaText'
import { formatDuration } from '@/domain/time'

const { ui } = useApp()
const d = ui.dialogs.streamSelect
const chosen = ref<number | null>(null)
watch(d, () => (chosen.value = null))
</script>

<template>
  <UiDialog :open="!!d" title="选择要分段的视频流" description="文件包含多条视频流，无法自动判断哪一条是成片。请明确选择。" size="md" @close="d?.resolve(null)">
    <div v-if="d" class="streams" role="radiogroup" aria-label="视频流">
      <button
        v-for="s in d.probe.media.video_streams"
        :key="s.stream_index"
        type="button"
        role="radio"
        class="stream"
        :aria-checked="chosen === s.stream_index"
        @click="chosen = s.stream_index"
      >
        <span class="stream__radio" aria-hidden="true"></span>
        <span class="stream__body">
          <span class="stream__title">流 #{{ s.stream_index }}<template v-if="s.title"> · {{ s.title }}</template><span v-if="s.is_default" class="stream__default small">容器标记为默认</span></span>
          <span class="small muted num">{{ streamSummary(s) }} · {{ colorSummary(s.color) }} · {{ formatDuration(s.duration_us) }} · {{ s.frame_count.toLocaleString() }} 帧</span>
        </span>
      </button>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="d?.resolve(null)">取消导入</UiButton>
      <UiButton variant="primary" :disabled="chosen === null" disabled-reason="请先选择一条视频流" @click="d && chosen !== null && d.resolve(chosen)">使用所选视频流</UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.streams {
  display: grid;
  gap: 8px;
}
.stream {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-2);
  text-align: left;
  background: var(--bg-raised);
}
.stream:hover {
  border-color: var(--line-strong);
}
.stream[aria-checked='true'] {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.stream__radio {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1.5px solid var(--line-strong);
  margin-top: 3px;
  flex: none;
}
.stream[aria-checked='true'] .stream__radio {
  border: 4px solid var(--accent);
}
.stream__body {
  display: grid;
  gap: 2px;
}
.stream__title {
  font-weight: var(--fw-medium);
}
.stream__default {
  margin-left: 8px;
  color: var(--text-3);
}
</style>
