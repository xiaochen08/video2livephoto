<script setup lang="ts">
import { Combine } from 'lucide-vue-next'
import { computed } from 'vue'
import { useActions, useApp } from '@/app/context'
import UiButton from '@/components/UiButton.vue'
import UiCheckbox from '@/components/UiCheckbox.vue'
import UiBanner from '@/components/UiBanner.vue'
import ParamRow from '@/components/ParamRow.vue'
import { audioConflict } from '@/domain/timelineCore'
import { clipDurationUs, formatDuration } from '@/domain/time'
import type { Clip } from '@/domain/types'
import InspectorSection from './InspectorSection.vue'

const { session, selection, view } = useApp()
const actions = useActions()
const clips = computed<Clip[]>(() => selection.state.selected.map((id) => session.clip(id)).filter((c): c is Clip => !!c))
const ids = computed(() => clips.value.map((c) => c.clip_id))
const visibleSet = computed(() => new Set(view.visibleIds.value))
const hidden = computed(() => ids.value.filter((id) => !visibleSet.value.has(id)).length)
const exportOn = computed(() => clips.value.filter((c) => c.export_selected).length)
const muted = computed(() => clips.value.filter((c) => c.audio === 'muted').length)
const n = computed(() => clips.value.length)
const exportState = computed<boolean | 'mixed'>(() => (exportOn.value === 0 ? false : exportOn.value === n.value ? true : 'mixed'))
const audioLabel = computed(() => (muted.value === 0 ? '全部保留原声' : muted.value === n.value ? '全部静音' : `部分静音（${muted.value} / ${n.value}）`))
const totalUs = computed(() => clips.value.reduce((a, c) => a + clipDurationUs(c, session.stream.value!), 0))
const mergeIds = computed(() => actions.mergeableSelection())
const conflict = computed(() => audioConflict(clips.value))
const hintCounts = computed(() => {
  const r = { short: 0, long: 0, review: 0, cover: 0 }
  for (const c of clips.value) for (const h of session.hints.value.get(c.clip_id) ?? []) if (h in r) r[h as keyof typeof r]++
  return r
})
</script>

<template>
  <div class="bi">
    <InspectorSection :title="`已选 ${n} 个片段`">
      <p class="small secondary">
        批量修改只作用于这 {{ n }} 个片段<template v-if="hidden">，<strong class="bi__warn">其中 {{ hidden }} 个不在当前筛选结果中</strong></template>。
      </p>
      <dl class="bi__dl">
        <ParamRow label="合计时长" :value="formatDuration(totalUs)" mono />
        <ParamRow v-if="hintCounts.review" label="待检查" :value="`${hintCounts.review} 个片段相邻切点待检查`" />
        <ParamRow v-if="hintCounts.short || hintCounts.long" label="实况提醒" :value="`超短 ${hintCounts.short} · 超长 ${hintCounts.long}`" />
        <ParamRow v-if="hintCounts.cover" label="封面" :value="`${hintCounts.cover} 个封面越界`" />
      </dl>
    </InspectorSection>

    <InspectorSection title="导出选择">
      <div class="bi__row">
        <UiCheckbox :checked="exportState" :label="`${exportOn} / ${n} 参与导出`" @change="(v) => actions.setExport(ids, v)" />
      </div>
      <div class="bi__btns">
        <UiButton size="sm" :disabled="exportOn === n" disabled-reason="已全部参与" @click="actions.setExport(ids, true)">全部参与（影响 {{ n - exportOn }} 个）</UiButton>
        <UiButton size="sm" :disabled="exportOn === 0" disabled-reason="已全部不参与" @click="actions.setExport(ids, false)">全部不参与（影响 {{ exportOn }} 个）</UiButton>
      </div>
      <p class="small muted">取消导出选择只影响导出范围，时间线内容保持完整。</p>
    </InspectorSection>

    <InspectorSection title="音频">
      <template v-if="session.hasAudio.value">
        <p class="small">当前：{{ audioLabel }}</p>
        <div class="bi__btns">
          <UiButton size="sm" :disabled="muted === 0" disabled-reason="已全部保留原声" @click="actions.setAudio(ids, 'source')">全部保留原声（影响 {{ muted }} 个）</UiButton>
          <UiButton size="sm" :disabled="muted === n" disabled-reason="已全部静音" @click="actions.setAudio(ids, 'muted')">全部静音（影响 {{ n - muted }} 个）</UiButton>
        </div>
      </template>
      <p v-else class="small muted">源视频无音轨，音频设置不可用。</p>
    </InspectorSection>

    <InspectorSection title="合并">
      <UiButton size="sm" :icon="Combine" kbd="M" :disabled="!mergeIds" disabled-reason="只能合并时间上相邻的片段" @click="actions.mergeSelected()">合并为 1 个片段</UiButton>
      <UiBanner v-if="mergeIds && conflict" tone="warning" compact>所选片段的音频设置不同（{{ muted }} 个静音），合并时需要选择合并后的音频设置。</UiBanner>
      <p class="small muted">合并会删除它们之间的切点，帧范围保持连续完整。可撤销。</p>
    </InspectorSection>

    <InspectorSection title="不适用于批量">
      <p class="small muted">名称、封面和起止位置需要逐个片段设置。点击列表中的单个片段即可。</p>
    </InspectorSection>
  </div>
</template>

<style scoped>
.bi__warn {
  color: var(--warning);
  font-weight: var(--fw-medium);
}
.bi__dl {
  display: grid;
  gap: 2px;
}
.bi__row {
  display: flex;
  align-items: center;
}
.bi__btns {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
