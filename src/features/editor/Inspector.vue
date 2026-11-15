<script setup lang="ts">
import { MousePointerClick } from 'lucide-vue-next'
import { computed } from 'vue'
import { useApp } from '@/app/context'
import EmptyState from '@/components/EmptyState.vue'
import BatchInspector from './BatchInspector.vue'
import ClipInspector from './ClipInspector.vue'
import CutInspector from './CutInspector.vue'

/** Right panel: selected cut > multi-selection > focused clip. */
const { session, selection } = useApp()
const cut = computed(() => session.timeline.value?.cuts.find((c) => c.cut_id === selection.state.selectedCutId) ?? null)
const focused = computed(() => session.clip(selection.state.focusedId))
const multi = computed(() => selection.state.selected.length > 1)
</script>

<template>
  <aside class="insp" aria-label="参数面板">
    <div class="insp__scroll">
      <Transition name="swap" mode="out-in">
        <CutInspector v-if="cut" :key="'cut-' + cut.cut_id" :cut="cut" />
        <BatchInspector v-else-if="multi" key="batch" />
        <ClipInspector v-else-if="focused" :key="focused.clip_id" :clip="focused" />
        <EmptyState v-else :icon="MousePointerClick" title="未选择片段" compact>在列表或时间线上点击片段查看参数。</EmptyState>
      </Transition>
    </div>
  </aside>
</template>

<style scoped>
.insp {
  height: 100%;
  min-height: 0;
  background: var(--bg-panel);
  display: flex;
  flex-direction: column;
}
.insp__scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.swap-enter-active,
.swap-leave-active {
  transition: opacity var(--dur-select) var(--ease-out);
}
.swap-enter-from,
.swap-leave-to {
  opacity: 0;
}
</style>
