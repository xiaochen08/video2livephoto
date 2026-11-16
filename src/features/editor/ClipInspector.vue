<script setup lang="ts">
import { ImagePlus, Play, RotateCcw, SkipBack, SkipForward, TriangleAlert, Wand2 } from 'lucide-vue-next'
import { computed } from 'vue'
import { useActions, useApp } from '@/app/context'
import FrameImage from '@/components/FrameImage.vue'
import ParamRow from '@/components/ParamRow.vue'
import StatusTag from '@/components/StatusTag.vue'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import UiSwitch from '@/components/UiSwitch.vue'
import UiTextField from '@/components/UiTextField.vue'
import { CUT_KIND_LABEL } from '@/domain/clipHints'
import { JOB_UI_META, jobUiState } from '@/domain/jobStates'
import { clipDisplayName, defaultClipName, fileStem, padIndex } from '@/domain/naming'
import { clipDurationUs, formatDuration, formatTime, frameToUs, rateToString } from '@/domain/time'
import type { Clip } from '@/domain/types'
import InspectorSection from './InspectorSection.vue'
import { colorLimitNote, colorSummary } from './mediaText'

const props = defineProps<{ clip: Clip }>()
const { session, playhead, ui, tasks, conn } = useApp()
const actions = useActions()
const s = computed(() => session.stream.value!)
const p = computed(() => session.project.value!)
const idx = computed(() => session.clipIndexById.value.get(props.clip.clip_id) ?? 0)
const hints = computed(() => session.hints.value.get(props.clip.clip_id) ?? [])
const dur = computed(() => clipDurationUs(props.clip, s.value))
const leftCut = computed(() => session.timeline.value!.cuts[idx.value - 1] ?? null)
const rightCut = computed(() => session.timeline.value!.cuts[idx.value] ?? null)
const stem = computed(() => fileStem(p.value.export_settings.name_base, props.clip.display_index))
const caps = computed(() => conn.value?.capabilities)
const lastJob = computed(() => tasks.latestJobByClip.value.get(props.clip.clip_id) ?? null)
const nameModel = computed(() => props.clip.name ?? '')

async function rename(v: string) {
  const name = v.trim() || null
  if (name === props.clip.name) return
  try {
    await session.edit({ type: 'set_clip_props', clip_ids: [props.clip.clip_id], patch: { name } })
  } catch (e) {
    ui.toast((e as Error).message, { tone: 'danger' })
  }
}
async function cover(cmd: 'auto' | 'regen') {
  try {
    await session.edit(cmd === 'auto' ? { type: 'set_cover', clip_id: props.clip.clip_id, frame: null } : { type: 'regenerate_cover', clip_id: props.clip.clip_id })
  } catch (e) {
    ui.toast((e as Error).message, { tone: 'danger' })
  }
}
function seek(f: number) {
  playhead.requestSeek(f)
}
const ms = (us: number) => Math.round(us / 1000)
</script>

<template>
  <div class="ci">
    <InspectorSection :title="`片段 ${padIndex(clip.display_index)}`">
      <template #aside>
        <span class="small muted mono" v-tip="'稳定片段 ID：用于配对与任务定位，与显示编号无关'">{{ clip.clip_id }}</span>
      </template>
      <UiTextField
        :model-value="nameModel"
        label="名称"
        :placeholder="defaultClipName(clip.display_index)"
        commit-on-blur
        :maxlength="60"
        :hint="clip.name_origin === 'example' ? '演示素材中的示例命名。留空则使用中性名称。' : '留空时使用中性名称；名称不影响导出文件名。'"
        @commit="rename"
      />
    </InspectorSection>

    <InspectorSection title="导出">
      <div class="ci__row">
        <UiSwitch :model-value="clip.export_selected" label="参与导出" @update:model-value="(v) => actions.setExport([clip.clip_id], v)" />
      </div>
      <p class="small muted">{{ clip.export_selected ? '生成完整 MP4，以及一个封装好的 LIVP 实况文件。' : '不参与本次导出。时间线画面保持完整，不会被删除。' }}</p>
      <ul v-if="clip.export_selected" class="ci__files small mono">
        <li><span class="muted">视频片段/</span>{{ stem }}.mp4</li>
        <li><span class="muted">LivePhoto/</span>{{ stem }}.livp</li>
      </ul>
      <div v-if="lastJob" class="ci__row small">
        <span class="muted">最近导出</span>
        <StatusTag
          size="sm"
          v-bind="JOB_UI_META[jobUiState(lastJob.job, lastJob.batch, { outdated: session.outdated.value.has(clip.clip_id) })]"
          :label="JOB_UI_META[jobUiState(lastJob.job, lastJob.batch, { outdated: session.outdated.value.has(clip.clip_id) })].label"
        />
        <span class="muted num">快照 v{{ lastJob.batch.snapshot.edit_version }}</span>
      </div>
    </InspectorSection>

    <InspectorSection title="音频">
      <template v-if="session.hasAudio.value">
        <UiSwitch :model-value="clip.audio === 'source'" label="导出原声" @update:model-value="(v) => actions.setAudio([clip.clip_id], v ? 'source' : 'muted')" />
        <p class="small muted">{{ clip.audio === 'source' ? '保留源视频对应时段的混合音频。' : '导出的 MP4 与 LIVP 内部视频不含声音。' }} 播放器中的预览音量只影响试听。</p>
      </template>
      <template v-else>
        <UiSwitch :model-value="false" label="导出原声" disabled />
        <p class="small muted">源视频无音轨，导出文件不包含音频，此选项不可用。</p>
      </template>
    </InspectorSection>

    <InspectorSection title="范围" :aside="`${(clip.end_frame - clip.start_frame).toLocaleString()} 帧`">
      <dl class="ci__dl">
        <ParamRow label="起点" mono>{{ formatTime(frameToUs(clip.start_frame, s, clip.start_pts)) }} <span class="muted">#{{ clip.start_frame }}</span></ParamRow>
        <ParamRow label="终点（不含）" mono>{{ formatTime(frameToUs(clip.end_frame, s, clip.end_pts)) }} <span class="muted">#{{ clip.end_frame }}</span></ParamRow>
        <ParamRow label="时长" mono>{{ formatDuration(dur) }}</ParamRow>
      </dl>
      <div class="ci__btns">
        <UiButton size="sm" variant="ghost" :icon="SkipBack" @click="seek(clip.start_frame)">起点</UiButton>
        <UiButton size="sm" variant="ghost" :icon="SkipForward" @click="seek(clip.end_frame - 1)">最后一帧</UiButton>
        <UiButton size="sm" variant="ghost" :icon="Play" @click="playhead.requestPlay({ from: clip.start_frame, to: clip.end_frame - 1 })">播放片段</UiButton>
      </div>
      <UiBanner v-if="hints.includes('short')" tone="warning" compact>
        超短实况（{{ formatDuration(dur) }}，低于 {{ (caps?.livephoto_hint.short_below_ms ?? 0) / 1000 }} 秒）：部分平台可能不识别为实况。原帧范围保持不变，不会补帧或延长，你可以继续导出。
      </UiBanner>
      <UiBanner v-if="hints.includes('long')" tone="warning" compact>
        超长片段（{{ formatDuration(dur) }}）：导出时完整 MP4 会保留当前范围，LivePhoto/ 会自动取前约 3 秒；如果要用中间时间段，请先在时间线上裁剪。部分平台仍可能有额外限制。
      </UiBanner>
      <p v-if="ms(dur) < 1000 && !hints.includes('short')" class="small muted">短镜头保持原帧范围。</p>
    </InspectorSection>

    <InspectorSection title="相邻切点">
      <div v-for="(c, side) in { 前: leftCut, 后: rightCut }" :key="side" class="ci__cut">
        <span class="muted small">{{ side }}</span>
        <template v-if="c">
          <span class="small">{{ CUT_KIND_LABEL[c.kind] }} <span class="mono muted">#{{ c.frame }}</span></span>
          <StatusTag v-if="c.review === 'pending'" size="sm" tone="warning" icon="dot" :label="c.skipped ? '已跳过·待检查' : '待检查'" />
          <StatusTag v-else size="sm" tone="muted" :label="c.confirmed_by === 'user' ? '已确认' : '清晰切换'" />
          <span class="grow"></span>
          <UiButton size="sm" variant="ghost" @click="actions.startReview(c.cut_id)">检查</UiButton>
        </template>
        <span v-else class="small muted">{{ side === '前' ? '视频开头' : '视频结尾' }}</span>
      </div>
    </InspectorSection>

    <InspectorSection title="封面">
      <button type="button" class="ci__cover" :class="{ 'is-portrait': s.height > s.width }" aria-label="选择封面" @click="ui.dialogs.cover.value = clip.clip_id">
        <FrameImage :project-id="p.project_id" :frame="clip.cover.frame" size="full" fit="contain" :alt="`封面：第 ${clip.cover.frame} 帧`" />
        <span class="ci__cover-tag small">{{ clip.cover.origin === 'auto' ? '自动选择（清晰帧）' : '手动选择' }} · #{{ clip.cover.frame }}</span>
      </button>
      <UiBanner v-if="clip.cover.status === 'out_of_range'" tone="warning" compact>
        切点变化后，手动选择的封面（#{{ clip.cover.frame }}）已不在本片段范围内。
        <template #actions>
          <UiButton size="sm" @click="ui.dialogs.cover.value = clip.clip_id">重新选择</UiButton>
          <UiButton size="sm" variant="ghost" :icon="Wand2" @click="cover('regen')">由后端重新生成</UiButton>
        </template>
      </UiBanner>
      <div class="ci__btns">
        <UiButton size="sm" :icon="ImagePlus" @click="ui.dialogs.cover.value = clip.clip_id">选择封面…</UiButton>
        <UiButton v-if="clip.cover.origin === 'user'" size="sm" variant="ghost" :icon="RotateCcw" @click="cover('auto')">恢复自动选择</UiButton>
      </div>
    </InspectorSection>

    <InspectorSection title="画质与色彩">
      <p class="small">保持源分辨率、方向、显示比例与帧率：<span class="num">{{ s.width }}×{{ s.height }} · {{ rateToString(s.frame_rate) }} fps</span></p>
      <p class="small">色彩：{{ colorSummary(s.color) }} → {{ p.export_settings.color === 'hdr_keep' ? '保留 HDR（后端验证范围内）' : 'Rec.709 SDR' }}</p>
      <p v-if="colorLimitNote(s.color, !!caps?.hdr_output.supported)" class="small ci__limit"><TriangleAlert :size="12" /> {{ colorLimitNote(s.color, !!caps?.hdr_output.supported) }}</p>
      <details class="ci__adv">
        <summary class="small">高级技术参数</summary>
        <dl class="ci__dl">
          <ParamRow label="编码" :value="s.codec.toUpperCase()" />
          <ParamRow label="位深" :value="s.color.bit_depth ? `${s.color.bit_depth}-bit` : '未知'" />
          <ParamRow label="传递函数" :value="s.color.transfer" mono />
          <ParamRow label="色域" :value="s.color.primaries" mono />
          <ParamRow label="显示比例" :value="`${s.display_aspect.num}:${s.display_aspect.den}`" mono />
          <ParamRow label="旋转" :value="`${s.rotation_deg}°`" mono />
          <ParamRow label="帧率（有理数）" :value="`${s.frame_rate.num}/${s.frame_rate.den}${s.vfr ? '（VFR，时间以 PTS 为准）' : ''}`" mono />
          <ParamRow label="time_base" :value="`${s.time_base.num}/${s.time_base.den}`" mono />
          <ParamRow label="PTS 范围" :value="`${clip.start_pts ?? '待后端'} – ${clip.end_pts ?? '待后端'}`" mono />
          <ParamRow label="编码路径" :value="caps?.gpu.available ? `GPU 优先：${caps.gpu.verified_encoder}；失败时本片段从头用 CPU 重试` : 'CPU（未检测到验证过的 GPU 路径）'" />
          <ParamRow label="防爆音处理" :value="caps?.declick_audio ? '可用' : '后端未提供'" />
        </dl>
      </details>
      <p class="small muted">名称：{{ clipDisplayName(clip) }}</p>
    </InspectorSection>
  </div>
</template>

<style scoped>
.ci__row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ci__files {
  display: grid;
  gap: 2px;
  padding: 6px 8px;
  background: var(--bg-well);
  border-radius: var(--r-1);
  color: var(--text-2);
  overflow-wrap: anywhere;
}
.ci__dl {
  display: grid;
  gap: 2px;
}
.ci__btns {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.ci__cut {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 26px;
}
.ci__cover {
  position: relative;
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: var(--r-2);
  overflow: hidden;
  border: 1px solid var(--line);
}
.ci__cover.is-portrait {
  aspect-ratio: 4 / 3;
}
.ci__cover:hover {
  border-color: var(--line-strong);
}
.ci__cover :deep(.frame) {
  width: 100%;
  height: 100%;
}
.ci__cover-tag {
  position: absolute;
  left: 6px;
  bottom: 6px;
  padding: 1px 6px;
  border-radius: 2px;
  background: rgba(0, 0, 0, 0.7);
  color: #ddd;
}
.ci__limit {
  color: var(--warning);
  display: flex;
  gap: 6px;
  align-items: flex-start;
}
.ci__limit svg {
  flex: none;
  margin-top: 3px;
}
.ci__adv summary {
  cursor: pointer;
  color: var(--text-2);
  padding: 2px 0;
}
.ci__adv[open] summary {
  margin-bottom: 6px;
}
</style>
