<script setup lang="ts">
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useApp } from '@/app/context'
import IconButton from '@/components/IconButton.vue'
import PaneResizer from '@/components/PaneResizer.vue'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import { clipDisplayName, padIndex } from '@/domain/naming'
import { clipDurationUs, formatDuration } from '@/domain/time'
import { PREF_LIMITS } from '@/stores/prefs'
import ReviewList from '@/features/review/ReviewList.vue'
import ReviewStage from '@/features/review/ReviewStage.vue'
import BottomDock from './BottomDock.vue'
import ClipList from './ClipList.vue'
import CutInspector from './CutInspector.vue'
import Inspector from './Inspector.vue'
import Player from './Player.vue'

/**
 * Editor workspace (direction C): floating panels on deep black.
 * [media list] [stage] [inspector] / bottom dock (clip cards ⇄ trim track).
 */
const { session, prefs, ui, selection, view, tasks } = useApp()
const review = computed(() => ui.state.editorMode === 'review')
const reviewCut = computed(() => session.timeline.value?.cuts.find((c) => c.cut_id === view.state.reviewCutId) ?? null)
const focused = computed(() => session.clip(selection.state.focusedId))
const winW = ref(window.innerWidth)
const winH = ref(window.innerHeight)
const onResize = () => {
  winW.value = window.innerWidth
  winH.value = window.innerHeight
}
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

// compact layout for narrow / high-scaling viewports: panels shrink, saved preferences stay untouched
const compact = computed(() => winW.value < 1280)
const leftW = computed(() => (compact.value ? Math.min(prefs.leftWidth, 252) : prefs.leftWidth))
const rightW = computed(() => (compact.value ? Math.min(prefs.rightWidth, 288) : prefs.rightWidth))
const dockH = computed(() => {
  const want = view.state.dock === 'trim' ? 300 : 232
  return Math.max(176, Math.min(want, Math.round(winH.value * (view.state.dock === 'trim' ? 0.4 : 0.32))))
})
const dismissedWarnings = ref(new Set<string>())
const warnings = computed(() => session.state.warnings.filter((w) => !dismissedWarnings.value.has(w.code)))
const interrupted = computed(() => session.project.value?.recovery_pending || !!tasks.attentionBatch.value?.jobs.some((j) => j.stage === 'commit_unknown'))
</script>

<template>
  <div v-if="session.project.value" class="editor" :style="{ gridTemplateRows: `minmax(0, 1fr) ${dockH}px` }">
    <div class="editor__work">
      <aside v-if="!prefs.leftCollapsed" class="panel editor__left" :style="{ width: leftW + 'px' }">
        <ReviewList v-if="review" />
        <ClipList v-else />
      </aside>
      <PaneResizer
        v-if="!prefs.leftCollapsed"
        orientation="vertical"
        label="调整媒体列表宽度"
        :value="prefs.leftWidth"
        :min="PREF_LIMITS.left[0]"
        :max="PREF_LIMITS.left[1]"
        data-sign="1"
        class="editor__resizer"
        @resize="(v) => (prefs.leftWidth = v)"
        @reset="prefs.leftWidth = 296"
      />

      <section class="editor__center">
        <div v-if="interrupted || warnings.length" class="center__banners">
          <UiBanner v-if="interrupted" tone="warning" compact>
            上次导出意外中断，有片段等待恢复确认。已核实成功的文件会保留。
            <template #actions>
              <UiButton size="sm" @click="ui.dialogs.recovery.value = { project_id: session.project.value.project_id }">查看恢复摘要</UiButton>
            </template>
          </UiBanner>
          <UiBanner v-for="w in warnings" :key="w.code" tone="info" compact dismissible @dismiss="dismissedWarnings.add(w.code)">{{ w.message }}</UiBanner>
        </div>
        <div class="panel stage">
          <header class="stage__bar">
            <IconButton
              :icon="prefs.leftCollapsed ? PanelLeftOpen : PanelLeftClose"
              :label="prefs.leftCollapsed ? '展开媒体列表' : '收起媒体列表'"
              size="sm"
              @click="prefs.leftCollapsed = !prefs.leftCollapsed"
            />
            <p v-if="review" class="stage__title">检查切点 <span class="muted small">· 前一段最后一帧与后一段第一帧对照</span></p>
            <p v-else-if="selection.state.selected.length > 1" class="stage__title">已选 {{ selection.state.selected.length }} 个片段 <span class="muted small">· 预览显示当前查看的片段</span></p>
            <p v-else-if="focused" class="stage__title truncate">
              <span class="stage__live">LIVE</span>
              <span class="num muted">{{ padIndex(focused.display_index) }}</span> {{ clipDisplayName(focused) }}
              <span class="muted small num">· {{ formatDuration(clipDurationUs(focused, session.stream.value!)) }}</span>
            </p>
            <span class="grow"></span>
            <IconButton
              :icon="prefs.rightCollapsed ? PanelRightOpen : PanelRightClose"
              :label="prefs.rightCollapsed ? '展开参数面板' : '收起参数面板'"
              size="sm"
              @click="prefs.rightCollapsed = !prefs.rightCollapsed"
            />
          </header>
          <div class="stage__body">
            <ReviewStage v-if="review" />
            <Player v-else />
          </div>
        </div>
      </section>

      <PaneResizer
        v-if="!prefs.rightCollapsed"
        orientation="vertical"
        label="调整参数面板宽度"
        :value="prefs.rightWidth"
        :min="PREF_LIMITS.right[0]"
        :max="PREF_LIMITS.right[1]"
        data-sign="-1"
        class="editor__resizer"
        @resize="(v) => (prefs.rightWidth = v)"
        @reset="prefs.rightWidth = 320"
      />
      <aside v-if="!prefs.rightCollapsed" class="panel editor__right" :style="{ width: rightW + 'px' }">
        <div v-if="review" class="editor__right-scroll">
          <CutInspector v-if="reviewCut" :key="reviewCut.cut_id" :cut="reviewCut" review-mode />
        </div>
        <Inspector v-else />
      </aside>
    </div>

    <BottomDock class="panel editor__dock" />
  </div>
</template>

<style scoped>
.editor {
  height: 100%;
  display: grid;
  gap: var(--gap);
  padding: 0 var(--gap) var(--gap);
  min-height: 0;
  transition: grid-template-rows var(--dur-spring) var(--ease-out);
}
.panel {
  background: var(--bg-panel);
  border-radius: var(--r-4);
  box-shadow: var(--panel-edge);
  overflow: hidden;
  min-height: 0;
}
.editor__work {
  min-height: 0;
  display: flex;
}
.editor__left,
.editor__right {
  flex: none;
}
.editor__resizer {
  margin: 0 3px;
  border-radius: 3px;
}
.editor__right-scroll {
  height: 100%;
  overflow-y: auto;
}
.editor__center {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.center__banners {
  display: grid;
  gap: 6px;
  flex: none;
}
.stage {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.stage__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  padding: 0 8px;
  flex: none;
}
.stage__title {
  font-size: var(--fs-13);
  font-weight: var(--fw-semibold);
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}
.stage__live {
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--brand);
  color: #fff;
  font-size: 10px;
  font-weight: var(--fw-bold);
  letter-spacing: 0.06em;
}
.stage__body {
  flex: 1;
  min-height: 0;
}
.editor__dock {
  min-width: 0;
}
</style>
