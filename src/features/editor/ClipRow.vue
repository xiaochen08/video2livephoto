<script setup lang="ts">
import { ImageOff, VolumeX, RefreshCw } from 'lucide-vue-next'
import { computed } from 'vue'
import FrameImage from '@/components/FrameImage.vue'
import UiCheckbox from '@/components/UiCheckbox.vue'
import type { ClipHint } from '@/domain/clipHints'
import { clipDisplayName, padIndex } from '@/domain/naming'
import { formatDurationShort } from '@/domain/time'
import type { Clip } from '@/domain/types'

const props = defineProps<{
  clip: Clip
  projectId: string
  durationUs: number
  hints: ClipHint[]
  focused: boolean
  selected: boolean
  outdated: boolean
  hasAudio: boolean
  portrait: boolean
}>()
const emit = defineEmits<{ select: [MouseEvent]; toggleExport: [boolean] }>()
const name = computed(() => clipDisplayName(props.clip))
const label = computed(
  () =>
    `${padIndex(props.clip.display_index)} ${name.value}，${formatDurationShort(props.durationUs)}${props.clip.export_selected ? '' : '，不参与导出'}${props.clip.audio === 'muted' ? '，已静音' : ''}${props.hints.includes('review') ? '，相邻切点待检查' : ''}${props.hints.includes('short') ? '，超短' : ''}${props.hints.includes('long') ? '，超长' : ''}`,
)
</script>

<template>
  <div
    class="crow"
    :class="{ 'is-focused': focused, 'is-selected': selected, 'is-excluded': !clip.export_selected }"
    role="option"
    :aria-selected="selected"
    :aria-current="focused || undefined"
    :aria-label="label"
    @click="emit('select', $event)"
  >
    <UiCheckbox
      :checked="clip.export_selected"
      small
      :aria-label="`${name} 参与导出`"
      @change="(v) => emit('toggleExport', v)"
    />
    <div class="crow__thumb" :class="{ 'is-portrait': portrait }">
      <FrameImage :project-id="projectId" :frame="clip.cover.frame" size="thumb" alt="" :fit="portrait ? 'contain' : 'cover'" />
      <span class="crow__dur num">{{ formatDurationShort(durationUs) }}</span>
    </div>
    <div class="crow__text">
      <div class="crow__line">
        <span class="crow__idx num">{{ padIndex(clip.display_index) }}</span>
        <span class="crow__name truncate">{{ name }}</span>
        <span v-if="clip.name_origin === 'example'" class="crow__example" title="演示素材的示例命名">示例</span>
      </div>
      <div class="crow__meta">
        <span v-if="hints.includes('review')" class="chip chip--review" title="相邻切点待检查">待检查</span>
        <span v-if="hints.includes('short')" class="chip chip--warn" title="超短实况：部分平台可能无法识别，原帧范围保持">超短</span>
        <span v-if="hints.includes('long')" class="chip chip--warn" title="超长实况：部分平台可能截断，原帧范围保持">超长</span>
        <span v-if="hints.includes('cover')" class="chip chip--warn" title="封面已不在片段范围内"><ImageOff :size="11" />封面</span>
        <span v-if="outdated" class="chip chip--warn" title="导出后有修改，下次导出将更新"><RefreshCw :size="10" />待更新</span>
        <span v-if="!clip.export_selected" class="chip chip--muted">不导出</span>
      </div>
    </div>
    <VolumeX v-if="hasAudio && clip.audio === 'muted'" :size="14" :stroke-width="1.75" class="crow__muted" aria-hidden="true" />
  </div>
</template>

<style scoped>
.crow {
  height: calc(100% - 4px);
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border-radius: var(--r-3);
  position: relative;
  cursor: default;
  transition: background-color var(--dur-select) var(--ease-standard);
}
.crow:hover:not(.is-focused) {
  background: rgba(255, 255, 255, 0.04);
}
.crow.is-selected:not(.is-focused) {
  background: var(--accent-soft);
}
.crow__thumb {
  position: relative;
  width: 76px;
  height: 46px;
  flex: none;
  border-radius: 8px;
  overflow: hidden;
  transition: transform var(--dur-spring) var(--ease-spring);
}
.crow.is-focused .crow__thumb {
  transform: scale(1.05);
}
.crow__thumb :deep(.frame) {
  width: 100%;
  height: 100%;
}
.crow__dur {
  position: absolute;
  right: 2px;
  bottom: 2px;
  padding: 0 4px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.75);
  font-weight: var(--fw-semibold);
  font-size: 10px;
  line-height: 14px;
  color: #eee;
}
.crow__text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.crow__line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.crow__idx {
  color: var(--text-3);
  font-size: var(--fs-12);
  flex: none;
}
.crow__name {
  font-size: var(--fs-13);
}
.crow.is-excluded .crow__name,
.crow.is-excluded .crow__thumb {
  opacity: 0.55;
}
.crow__example {
  font-size: 10px;
  color: var(--text-3);
  border: 1px solid var(--line-strong);
  border-radius: 2px;
  padding: 0 3px;
  line-height: 14px;
  flex: none;
}
.crow__meta {
  display: flex;
  gap: 4px;
  min-height: 16px;
  overflow: hidden;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 17px;
  padding: 0 6px;
  border-radius: 6px;
  font-size: 10.5px;
  white-space: nowrap;
}
.chip--review {
  color: #1f1a00;
  background: var(--warning);
  font-weight: var(--fw-semibold);
}
.chip--warn {
  color: var(--warning);
  background: var(--warning-soft);
}
.chip--muted {
  color: var(--text-3);
  box-shadow: inset 0 0 0 1px var(--line-strong);
}
.crow__muted {
  color: var(--text-3);
  flex: none;
}
</style>
