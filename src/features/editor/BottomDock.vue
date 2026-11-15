<script setup lang="ts">
import { LayoutGrid, Scissors } from 'lucide-vue-next'
import { computed } from 'vue'
import { useApp } from '@/app/context'
import ClipRail from './ClipRail.vue'
import OverviewStrip from './OverviewStrip.vue'
import TrimEditor from './TrimEditor.vue'

/**
 * Bottom dock (direction C): two modes that the user toggles freely.
 *  - 片段: overview strip + clip cards
 *  - 剪辑轨道: trim track of the focused clip (opens from 「拆分」, the tab, or double-clicking a card)
 */
const { view, session } = useApp()
const count = computed(() => session.timeline.value?.clips.length ?? 0)
const exportCount = computed(() => session.timeline.value?.clips.filter((c) => c.export_selected).length ?? 0)
const pending = computed(() => session.pendingCuts.value.length)
function setDock(m: 'cards' | 'trim') {
  view.state.dock = m
}
</script>

<template>
  <section class="dock" :aria-label="view.state.dock === 'cards' ? '片段卡片' : '剪辑轨道'">
    <Transition name="dock" mode="out-in">
      <div v-if="view.state.dock === 'cards'" key="cards" class="dock__body">
        <header class="dock__head">
          <div class="tabs" role="tablist" aria-label="底部区域">
            <span class="tabs__pill tabs__pill--cards" aria-hidden="true"></span>
            <button type="button" role="tab" aria-selected="true" v-tip="`${count} 个片段 · ${exportCount} 个参与导出 · 双击卡片进入剪辑`"><LayoutGrid :size="13" /> 片段 <i class="num">{{ count }}</i></button>
            <button type="button" role="tab" aria-selected="false" @click="setDock('trim')"><Scissors :size="13" /> 剪辑轨道</button>
          </div>
          <button type="button" class="dock__split" v-tip="'进入当前片段的剪辑轨道：调整开头 / 结尾、拆分、合并'" @click="setDock('trim')"><Scissors :size="14" /> 拆分</button>
          <OverviewStrip />
          <span class="dock__hint small">{{ pending ? `${pending} 处待检查 · 点击黄色标记检查` : '切点已全部检查' }}</span>
        </header>
        <ClipRail />
      </div>
      <div v-else key="trim" class="dock__body">
        <TrimEditor @done="setDock('cards')">
          <template #lead>
            <div class="tabs" role="tablist" aria-label="底部区域">
              <span class="tabs__pill tabs__pill--trim" aria-hidden="true"></span>
              <button type="button" role="tab" aria-selected="false" @click="setDock('cards')"><LayoutGrid :size="13" /> 片段 <i class="num">{{ count }}</i></button>
              <button type="button" role="tab" aria-selected="true"><Scissors :size="13" /> 剪辑轨道</button>
            </div>
          </template>
        </TrimEditor>
      </div>
    </Transition>
  </section>
</template>

<style scoped>
.dock {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.dock__body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.dock__head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px 4px;
  flex: none;
  min-width: 0;
}
.dock__hint {
  color: var(--text-3);
  white-space: nowrap;
}
.dock__split {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 11px;
  border-radius: var(--r-2);
  background: var(--bg-control);
  color: var(--text-2);
  font-size: var(--fs-12);
  font-weight: var(--fw-semibold);
  flex: none;
  transition:
    background-color var(--dur-press),
    color var(--dur-press),
    transform var(--dur-spring) var(--ease-spring);
}
.dock__split:hover {
  background: var(--bg-control-hover);
  color: var(--text-1);
}
.dock__split:active {
  transform: scale(0.92);
}
.tabs {
  position: relative;
  display: inline-flex;
  padding: 3px;
  border-radius: var(--r-2);
  background: var(--bg-well);
  box-shadow: inset 0 0 0 1px var(--line);
  flex: none;
}
.tabs button {
  position: relative;
  z-index: 1;
  width: 98px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  font-size: var(--fs-12);
  font-weight: var(--fw-semibold);
  color: var(--text-2);
  transition: color var(--dur-select);
}
.tabs button i {
  font-style: normal;
  font-size: var(--fs-11);
  opacity: 0.6;
}
.tabs button[aria-selected='true'] {
  color: var(--primary-text);
}
.tabs__pill {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: 3px;
  width: 98px;
  border-radius: 7px;
  background: var(--primary);
}
.tabs__pill--cards {
  animation: pill-to-cards var(--dur-spring) var(--ease-spring);
}
.tabs__pill--trim {
  transform: translateX(100%);
  animation: pill-to-trim var(--dur-spring) var(--ease-spring);
}
@keyframes pill-to-trim {
  from {
    transform: translateX(0);
  }
}
@keyframes pill-to-cards {
  from {
    transform: translateX(100%);
  }
}
.dock-enter-active {
  transition:
    opacity var(--dur-panel) var(--ease-out),
    transform var(--dur-spring) var(--ease-spring);
}
.dock-leave-active {
  transition:
    opacity 120ms,
    transform var(--dur-select) var(--ease-out);
}
.dock-enter-from {
  opacity: 0;
  transform: translateY(-18px);
}
.dock-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
@media (max-width: 1280px) {
  .dock__hint {
    display: none;
  }
}
</style>
