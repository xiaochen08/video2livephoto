<script setup lang="ts">
import { ChevronDown, ListFilter } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useActions, useApp } from '@/app/context'
import EmptyState from '@/components/EmptyState.vue'
import UiCheckbox from '@/components/UiCheckbox.vue'
import UiMenu from '@/components/UiMenu.vue'
import UiSelect from '@/components/UiSelect.vue'
import VirtualList from '@/components/VirtualList.vue'
import type { MenuItem } from '@/components/menu'
import { clipDurationUs } from '@/domain/time'
import type { Clip } from '@/domain/types'
import type { ClipFilter, ClipSort } from '@/stores/editorView'
import ClipRow from './ClipRow.vue'

const { session, selection, view } = useApp()
const actions = useActions()
const list = ref<{ scrollToIndex: (i: number) => void } | null>(null)
const project = session.project
const portrait = computed(() => {
  const s = session.stream.value
  return !!s && s.height > s.width
})

const filterOptions = computed(() => {
  const c = view.counts.value
  return [
    { value: 'all' as ClipFilter, label: `全部片段（${c.all}）` },
    { value: 'review' as ClipFilter, label: `相邻切点待检查（${c.review}）` },
    { value: 'hints' as ClipFilter, label: `有提醒：超短/超长/封面（${c.hints}）` },
    { value: 'muted' as ClipFilter, label: `已静音（${c.muted}）`, disabled: !session.hasAudio.value },
    { value: 'excluded' as ClipFilter, label: `不参与导出（${c.excluded}）` },
    { value: 'outdated' as ClipFilter, label: `待更新（${c.outdated}）` },
  ]
})
const sortOptions: { value: ClipSort; label: string }[] = [
  { value: 'timeline', label: '时间顺序' },
  { value: 'duration_desc', label: '时长：长→短' },
  { value: 'duration_asc', label: '时长：短→长' },
]

const visibleIds = view.visibleIds
const visibleSet = computed(() => new Set(visibleIds.value))
const selectedVisible = computed(() => selection.state.selected.filter((id) => visibleSet.value.has(id)).length)
const hiddenSelected = computed(() => selection.state.selected.length - selectedVisible.value)
const headState = computed<boolean | 'mixed'>(() => (selectedVisible.value === 0 ? false : selectedVisible.value === visibleIds.value.length ? true : 'mixed'))
const filtered = computed(() => view.state.filter !== 'all')

const scopeItems = computed<MenuItem[]>(() => [
  { id: 'visible', label: `全选当前结果（${visibleIds.value.length}）`, hint: filtered.value ? '只选择当前筛选显示的片段' : '与全选全部相同', run: () => selection.selectAll(visibleIds.value) },
  { id: 'all', label: `全选全部片段（${view.counts.value.all}）`, hint: '包括被筛选隐藏的片段', run: () => selection.selectAll(session.timeline.value!.clips.map((c) => c.clip_id)) },
  { id: 'none', label: '取消多选', hint: '保留当前查看的片段', disabled: selection.state.selected.length <= 1, run: () => selection.clear() },
])

function onHead(v: boolean) {
  if (v) selection.selectAll(visibleIds.value)
  else selection.clear()
}

function onSelect(c: Clip, e: MouseEvent) {
  const mods = { ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey }
  selection.click(c.clip_id, mods, visibleIds.value)
  if (!mods.ctrl && !mods.shift) actions.focusClip(c.clip_id)
}

watch(
  () => view.state.scrollToClip,
  () => {
    const id = selection.state.focusedId
    if (id) list.value?.scrollToIndex(visibleIds.value.indexOf(id))
  },
)
watch(
  () => selection.state.focusedId,
  (id) => id && list.value?.scrollToIndex(visibleIds.value.indexOf(id)),
)
</script>

<template>
  <section class="clist" aria-label="片段列表">
    <header class="clist__head">
      <div class="clist__row">
        <h2 class="clist__title">媒体 <span class="muted num">{{ view.counts.value.all }} 个片段</span></h2>
        <span class="grow"></span>
        <UiSelect v-model="view.state.sort" :options="sortOptions" aria-label="排序" size="sm" />
      </div>
      <div class="clist__row">
        <ListFilter :size="14" class="muted" aria-hidden="true" />
        <UiSelect v-model="view.state.filter" :options="filterOptions" aria-label="筛选片段" size="sm" class="grow" />
      </div>
      <div class="clist__row clist__sel">
        <UiCheckbox :checked="headState" small aria-label="全选当前筛选结果" @change="onHead" />
        <span class="small secondary num">
          已选 {{ selection.state.selected.length }}
          <template v-if="filtered"> · 当前结果 {{ visibleIds.length }}</template>
        </span>
        <UiMenu :items="scopeItems" label="选择范围" align="right">
          <template #trigger="{ toggle, open, id }">
            <button type="button" class="clist__scope small" aria-haspopup="menu" :aria-expanded="open" :aria-controls="id" @click="toggle">选择范围 <ChevronDown :size="12" /></button>
          </template>
        </UiMenu>
      </div>
      <p v-if="hiddenSelected > 0" class="clist__hidden small" role="status">
        其中 {{ hiddenSelected }} 个已选片段不在当前筛选结果中，批量操作仍会影响它们。
        <button type="button" @click="selection.keepOnly(visibleIds)">只保留可见</button>
      </p>
    </header>
    <VirtualList v-if="project && view.visible.value.length" ref="list" :items="view.visible.value" :row-height="64" :key-of="(c: Clip) => c.clip_id" :indicator-index="view.visibleIds.value.indexOf(selection.state.focusedId ?? '')" aria-label="片段，Ctrl 多选，Shift 范围选择" class="clist__body">
      <template #indicator><span class="clist__ind"></span></template>
      <template #default="{ item }">
        <ClipRow
          :clip="item"
          :project-id="project.project_id"
          :duration-us="clipDurationUs(item, session.stream.value!)"
          :hints="session.hints.value.get(item.clip_id) ?? []"
          :focused="selection.state.focusedId === item.clip_id"
          :selected="selection.selectedSet.value.has(item.clip_id)"
          :outdated="session.outdated.value.has(item.clip_id)"
          :has-audio="session.hasAudio.value"
          :portrait="portrait"
          @select="(e) => onSelect(item, e)"
          @toggle-export="(v) => actions.setExport([item.clip_id], v)"
        />
      </template>
    </VirtualList>
    <EmptyState v-else compact title="没有符合筛选的片段">
      <button type="button" class="link" @click="view.state.filter = 'all'">显示全部片段</button>
    </EmptyState>
  </section>
</template>

<style scoped>
.clist {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}
.clist__head {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 12px 10px 14px;
  flex: none;
}
.clist__row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.clist__title {
  font-size: var(--fs-14);
  font-weight: var(--fw-bold);
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.clist__title span {
  font-size: var(--fs-12);
  font-weight: var(--fw-regular);
}
.clist__sel {
  justify-content: space-between;
}
.clist__sel .secondary {
  flex: 1;
}
.clist__scope {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--text-2);
  padding: 2px 6px;
  border-radius: var(--r-1);
}
.clist__scope:hover {
  background: var(--bg-control);
  color: var(--text-1);
}
.clist__hidden {
  color: var(--warning);
  line-height: 1.45;
}
.clist__hidden button,
.link {
  color: var(--accent-hover);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.clist__body {
  flex: 1;
}
.clist__body :deep(.vlist__spacer) {
  margin: 0 8px;
  width: calc(100% - 16px);
}
.clist__ind {
  position: absolute;
  inset: 2px 0;
  border-radius: var(--r-3);
  background: var(--accent-soft);
  box-shadow: inset 0 0 0 1.5px var(--accent);
}
</style>
