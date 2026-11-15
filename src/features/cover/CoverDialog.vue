<script setup lang="ts">
import { ChevronLeft, ChevronRight, Play, RotateCcw, Square } from 'lucide-vue-next'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useApp } from '@/app/context'
import FrameImage from '@/components/FrameImage.vue'
import IconButton from '@/components/IconButton.vue'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import UiDialog from '@/components/UiDialog.vue'
import { clipDisplayName, padIndex } from '@/domain/naming'
import { formatTime, frameToUs } from '@/domain/time'

const { ui, session } = useApp()
const clipId = ui.dialogs.cover
const clip = computed(() => session.clip(clipId.value))
const s = session.stream
const project = session.project
const candidate = ref(0)
const saving = ref(false)
const comboVideo = ref<HTMLVideoElement>()
const combo = ref<'idle' | 'still' | 'motion'>('idle')
let comboTimer: ReturnType<typeof setTimeout> | null = null

watch(
  clip,
  (c, old) => {
    if (c && c.clip_id !== old?.clip_id) candidate.value = clampFrame(c.cover.status === 'out_of_range' ? c.start_frame + Math.floor((c.end_frame - c.start_frame) / 2) : c.cover.frame)
    if (!c) stopCombo()
  },
  { immediate: true },
)

function clampFrame(f: number) {
  const c = clip.value
  if (!c) return f
  return Math.max(c.start_frame, Math.min(c.end_frame - 1, Math.round(f)))
}
const strip = computed(() => {
  const c = clip.value
  if (!c) return []
  const n = Math.min(12, c.end_frame - c.start_frame)
  const out: number[] = []
  for (let i = 0; i < n; i++) out.push(c.start_frame + Math.floor(((c.end_frame - c.start_frame - 1) * i) / Math.max(1, n - 1)))
  return [...new Set(out)]
})
const isCurrent = computed(() => clip.value?.cover.frame === candidate.value && clip.value.cover.status !== 'out_of_range')

async function apply(frame: number | null) {
  const c = clip.value
  if (!c) return
  saving.value = true
  try {
    await session.edit({ type: 'set_cover', clip_id: c.clip_id, frame })
    ui.toast(frame === null ? '已恢复自动选择的封面' : `已将第 ${frame} 帧设为封面`, { tone: 'success', timeout: 2400, action: { label: '撤销', run: () => void session.undo() } })
    clipId.value = null
  } catch (e) {
    ui.toast((e as Error).message, { tone: 'danger' })
  } finally {
    saving.value = false
  }
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault()
    candidate.value = clampFrame(candidate.value + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 10 : 1))
  }
}

/** In-app combined preview: cover still, then the motion part of the clip. Not a phone-album test. */
function playCombo() {
  const c = clip.value
  const v = comboVideo.value
  if (!c || !s.value) return
  stopCombo()
  combo.value = 'still'
  comboTimer = setTimeout(() => {
    combo.value = 'motion'
    if (!v) return
    v.currentTime = ((c.start_frame + 0.5) * s.value!.frame_rate.den) / s.value!.frame_rate.num
    void v.play().catch(() => (combo.value = 'idle'))
  }, 900)
}
function onComboTime() {
  const c = clip.value
  const v = comboVideo.value
  if (!c || !v || !s.value) return
  const endSec = (c.end_frame * s.value.frame_rate.den) / s.value.frame_rate.num
  if (v.currentTime >= endSec) {
    v.pause()
    combo.value = 'still'
    comboTimer = setTimeout(() => (combo.value = 'idle'), 700)
  }
}
function stopCombo() {
  if (comboTimer) clearTimeout(comboTimer)
  comboTimer = null
  comboVideo.value?.pause()
  combo.value = 'idle'
}
onBeforeUnmount(stopCombo)
</script>

<template>
  <UiDialog
    :open="!!clip"
    :title="clip ? `选择封面 · 片段 ${padIndex(clip.display_index)}` : '选择封面'"
    :description="clip ? `${clipDisplayName(clip)} · 有效范围 #${clip.start_frame} – #${clip.end_frame - 1}` : undefined"
    size="xl"
    @close="clipId = null"
  >
    <div v-if="clip && project && s" class="cover" @keydown="onKey">
      <div class="cover__main">
        <div class="cover__view" :class="{ 'is-portrait': s.height > s.width }">
          <FrameImage :project-id="project.project_id" :frame="candidate" size="full" fit="contain" :lazy="false" :alt="`候选封面 #${candidate}`" />
          <span class="cover__badge small">{{ isCurrent ? '当前封面' : '候选帧' }} · <span class="mono">#{{ candidate }}</span> · {{ formatTime(frameToUs(candidate, s)) }}</span>
        </div>
        <div class="cover__nav" role="group" aria-label="候选帧定位">
          <IconButton :icon="ChevronLeft" label="前一帧" kbd="←" :disabled="candidate <= clip.start_frame" disabled-reason="已是片段第一帧" @click="candidate = clampFrame(candidate - 1)" />
          <input
            type="range"
            class="cover__range"
            :min="clip.start_frame"
            :max="clip.end_frame - 1"
            :value="candidate"
            aria-label="在片段内选择帧"
            @input="candidate = clampFrame(Number(($event.target as HTMLInputElement).value))"
          />
          <IconButton :icon="ChevronRight" label="后一帧" kbd="→" :disabled="candidate >= clip.end_frame - 1" disabled-reason="已是片段最后一帧" @click="candidate = clampFrame(candidate + 1)" />
        </div>
        <div class="cover__strip" role="listbox" aria-label="片段内部帧条">
          <button
            v-for="f in strip"
            :key="f"
            type="button"
            role="option"
            class="cover__sf"
            :aria-selected="f === candidate"
            :class="{ 'is-cover': f === clip.cover.frame && clip.cover.status !== 'out_of_range' }"
            :aria-label="`第 ${f} 帧${f === clip.cover.frame ? '（当前封面）' : ''}`"
            @click="candidate = f"
          >
            <FrameImage :project-id="project.project_id" :frame="f" size="thumb" alt="" />
          </button>
        </div>
      </div>

      <aside class="cover__side">
        <div class="cover__cur">
          <p class="section-title">当前封面</p>
          <p class="small">{{ clip.cover.origin === 'auto' ? '自动选择（后端清晰帧）' : '手动选择' }} · <span class="mono">#{{ clip.cover.frame }}</span></p>
          <UiBanner v-if="clip.cover.status === 'out_of_range'" tone="warning" compact>原封面已不在片段范围内，请重新选择。</UiBanner>
        </div>
        <div class="cover__combo">
          <p class="section-title">封面与动态片段组合预览</p>
          <div class="cover__combo-view" :class="{ 'is-portrait': s.height > s.width }">
            <FrameImage v-show="combo !== 'motion'" :project-id="project.project_id" :frame="candidate" size="thumb" fit="contain" :lazy="false" alt="" />
            <video
              v-if="session.state.preview?.url"
              v-show="combo === 'motion'"
              ref="comboVideo"
              :src="session.state.preview.url"
              muted
              playsinline
              preload="auto"
              @timeupdate="onComboTime"
            ></video>
            <span class="cover__combo-tag small">{{ combo === 'motion' ? '动态部分' : combo === 'still' ? '封面静帧' : '未播放' }}</span>
          </div>
          <UiButton size="sm" :icon="combo === 'idle' ? Play : Square" :disabled="!session.state.preview?.url" disabled-reason="没有可播放的预览" @click="combo === 'idle' ? playCombo() : stopCombo()">
            {{ combo === 'idle' ? '播放组合预览' : '停止' }}
          </UiButton>
          <p class="small muted">这是软件内的预览，用于判断封面与动态衔接。手机相册能否识别为实况，需要另行实机验证（当前：待验证）。</p>
        </div>
      </aside>
    </div>
    <template #footer>
      <UiButton v-if="clip?.cover.origin === 'user'" variant="ghost" :icon="RotateCcw" :disabled="saving" @click="apply(null)">恢复自动选择</UiButton>
      <span class="grow"></span>
      <UiButton variant="ghost" @click="clipId = null">取消</UiButton>
      <UiButton variant="primary" :loading="saving" loading-label="正在设置封面…" :disabled="isCurrent" disabled-reason="这已经是当前封面" @click="apply(candidate)">将 #{{ candidate }} 设为封面</UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.cover {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 20px;
}
.cover__main {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.cover__view {
  position: relative;
  aspect-ratio: 16 / 9;
  border-radius: var(--r-2);
  overflow: hidden;
  background: #000;
}
.cover__view.is-portrait {
  aspect-ratio: 4 / 3;
}
.cover__view :deep(.frame) {
  width: 100%;
  height: 100%;
}
.cover__badge {
  position: absolute;
  left: 8px;
  top: 8px;
  padding: 2px 8px;
  border-radius: var(--r-1);
  background: rgba(0, 0, 0, 0.72);
  color: #e8e8e8;
}
.cover__nav {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cover__range {
  flex: 1;
  accent-color: var(--accent);
}
.cover__strip {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 4px;
}
.cover__sf {
  aspect-ratio: 16 / 9;
  border-radius: 2px;
  overflow: hidden;
  border: 2px solid transparent;
  padding: 0;
}
.cover__sf :deep(.frame) {
  width: 100%;
  height: 100%;
}
.cover__sf[aria-selected='true'] {
  border-color: var(--accent);
}
.cover__sf.is-cover {
  box-shadow: 0 -3px 0 var(--success) inset;
}
.cover__side {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.cover__cur,
.cover__combo {
  display: grid;
  gap: 8px;
}
.cover__combo-view {
  position: relative;
  aspect-ratio: 16 / 9;
  background: #000;
  border-radius: var(--r-1);
  overflow: hidden;
}
.cover__combo-view.is-portrait {
  aspect-ratio: 3 / 4;
}
.cover__combo-view :deep(.frame),
.cover__combo-view video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.cover__combo-tag {
  position: absolute;
  right: 6px;
  bottom: 6px;
  background: rgba(0, 0, 0, 0.7);
  padding: 0 6px;
  border-radius: 2px;
  color: #ddd;
}
</style>
