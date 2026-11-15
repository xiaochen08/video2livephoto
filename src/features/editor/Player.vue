<script setup lang="ts">
import { ChevronLeft, ChevronRight, Expand, Pause, Play, Repeat, RotateCcw, Shrink, SkipBack, SkipForward, Volume2, VolumeX, MonitorX } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useApp } from '@/app/context'
import FrameImage from '@/components/FrameImage.vue'
import IconButton from '@/components/IconButton.vue'
import UiButton from '@/components/UiButton.vue'
import UiSpinner from '@/components/UiSpinner.vue'
import { formatTime, framesToUs } from '@/domain/time'
import { vTip } from '@/components/tooltip'

const { session, playhead, prefs, selection, ui } = useApp()
const video = ref<HTMLVideoElement>()
const timeEl = ref<HTMLElement>()
const frameEl = ref<HTMLElement>()
const status = ref<'loading' | 'ready' | 'waiting' | 'error' | 'none'>('loading')
const mediaError = ref<string | null>(null)
const fit = ref<'fit' | 'actual'>('fit')
const overlayState = ref<'loading' | 'ready' | 'error'>('loading')
const reloadKey = ref(0)
const src = computed(() => session.state.preview?.url ?? null)
const stream = session.stream
const project = session.project
const playing = playhead.isPlaying
const frameCount = computed(() => session.timeline.value?.frame_count ?? 0)
const totalUs = computed(() => {
  const s = stream.value
  if (!s) return 0
  return s.duration_us > 0 ? s.duration_us : framesToUs(frameCount.value, s.frame_rate)
})
const portrait = computed(() => !!stream.value && stream.value.height > stream.value.width)
const focusedClip = computed(() => session.clip(selection.state.focusedId))
const hasAudio = session.hasAudio
let raf = 0
let rangeEnd: number | null = null

function frameToSec(f: number) {
  const r = stream.value!.frame_rate
  return ((f + 0.5) * r.den) / r.num
}
function secToFrame(t: number) {
  const r = stream.value!.frame_rate
  return Math.floor((t * r.num) / r.den + 1e-4)
}

function seek(f: number) {
  if (!stream.value) return
  const clamped = Math.max(0, Math.min(frameCount.value - 1, Math.round(f)))
  playhead.set(clamped)
  const v = video.value
  if (v && status.value !== 'error' && Number.isFinite(v.duration)) v.currentTime = frameToSec(clamped)
}

function tick() {
  const v = video.value
  if (!v || v.paused) return
  const f = Math.min(frameCount.value - 1, secToFrame(v.currentTime))
  playhead.set(f)
  if (rangeEnd !== null && f >= rangeEnd) {
    v.pause()
    rangeEnd = null
    return
  }
  raf = requestAnimationFrame(tick)
}

async function play() {
  const v = video.value
  if (!v || !src.value || status.value === 'error') {
    ui.toast(src.value ? '预览媒体当前无法播放。' : '此项目没有可播放的预览，只能逐帧查看。', { tone: 'warning' })
    return
  }
  if (playhead.frame >= frameCount.value - 1) seek(0)
  try {
    await v.play()
  } catch {
    /* autoplay policies / aborted by pause */
  }
}
function pause() {
  video.value?.pause()
  rangeEnd = null
}
function toggle() {
  if (playing.value) pause()
  else void play()
}
function playRange(from: number, to: number) {
  seek(from)
  rangeEnd = to
  void play()
}

const onSeekReq = (f: number) => {
  if (playing.value) pause()
  seek(f)
}
const onPlayReq = (cmd: 'toggle' | 'play' | 'pause' | { from: number; to: number }) => {
  if (cmd === 'toggle') toggle()
  else if (cmd === 'play') void play()
  else if (cmd === 'pause') pause()
  else playRange(cmd.from, cmd.to)
}

function onPlay() {
  playhead.setPlaying(true)
  cancelAnimationFrame(raf)
  raf = requestAnimationFrame(tick)
}
function onPause() {
  cancelAnimationFrame(raf)
  playhead.setPlaying(false)
  if (video.value) playhead.set(Math.min(frameCount.value - 1, secToFrame(video.value.currentTime)))
}
function onError() {
  const code = video.value?.error?.code
  status.value = 'error'
  mediaError.value = code === 4 ? '浏览器不支持此预览媒体或文件已失效' : code === 3 ? '预览媒体解码失败' : code === 2 ? '读取预览媒体时网络/文件错误' : '预览媒体无法加载'
  playhead.setPlaying(false)
}
function reload() {
  status.value = 'loading'
  mediaError.value = null
  reloadKey.value++
}

function applyVolume() {
  const v = video.value
  if (!v) return
  v.volume = prefs.previewVolume
  v.muted = prefs.previewMuted || !hasAudio.value
}
watch(() => [prefs.previewVolume, prefs.previewMuted, hasAudio.value], applyVolume)
watch(src, (s) => {
  status.value = s ? 'loading' : 'none'
  mediaError.value = null
})

let offTime: (() => void) | null = null
onMounted(() => {
  status.value = src.value ? 'loading' : 'none'
  playhead.seekRequests.add(onSeekReq)
  playhead.playRequests.add(onPlayReq)
  offTime = playhead.subscribe((f) => {
    if (!stream.value) return
    if (timeEl.value) timeEl.value.textContent = formatTime(framesToUs(f, stream.value.frame_rate))
    if (frameEl.value) frameEl.value.textContent = `#${f}`
  })
  const c = focusedClip.value
  if (c) seek(c.start_frame)
})
onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  playhead.seekRequests.delete(onSeekReq)
  playhead.playRequests.delete(onPlayReq)
  offTime?.()
  playhead.setPlaying(false)
  const v = video.value
  if (v) {
    v.pause()
    v.removeAttribute('src')
    v.load()
  }
})

function onLoaded() {
  status.value = 'ready'
  applyVolume()
  seek(playhead.frame)
}

const showOverlay = computed(() => !playing.value || !src.value || status.value === 'error')
const stageEl = ref<HTMLElement>()
const stageSize = ref({ w: 0, h: 0 })
let ro: ResizeObserver | null = null
onMounted(() => {
  ro = new ResizeObserver(([e]) => (stageSize.value = { w: e.contentRect.width, h: e.contentRect.height }))
  if (stageEl.value) ro.observe(stageEl.value)
})
onBeforeUnmount(() => ro?.disconnect())
/** Keeps the source display aspect ratio (orientation already applied by the backend/browser). */
const viewStyle = computed(() => {
  const p = session.state.preview
  if (fit.value === 'actual' && p) return { width: p.width + 'px', height: p.height + 'px', flex: 'none' }
  const s = stream.value
  if (!s) return {}
  const ar = s.display_aspect.num / s.display_aspect.den
  const { w: W, h: H } = stageSize.value
  const w = Math.max(0, Math.min(W, H * ar))
  return { width: Math.floor(w) + 'px', height: Math.floor(w / ar) + 'px' }
})
</script>

<template>
  <section class="player" aria-label="视频预览">
    <div ref="stageEl" class="player__stage" :class="{ 'is-actual': fit === 'actual', 'is-portrait': portrait }">
      <div v-if="project && stream" class="player__view" :style="viewStyle">
        <video
          v-if="src && status !== 'error'"
          :key="reloadKey"
          ref="video"
          class="player__video"
          :src="src"
          preload="auto"
          playsinline
          disablepictureinpicture
          @loadedmetadata="onLoaded"
          @waiting="status = 'waiting'"
          @playing="status = 'ready'"
          @canplay="status === 'waiting' && (status = 'ready')"
          @play="onPlay"
          @pause="onPause"
          @ended="onPause"
          @error="onError"
        ></video>
        <FrameImage
          v-show="showOverlay"
          class="player__frame"
          :project-id="project.project_id"
          :frame="playhead.coarse.value"
          size="full"
          :lazy="false"
          fit="contain"
          :alt="`第 ${playhead.coarse.value} 帧`"
          @state="(s) => (overlayState = s)"
        />
      </div>

      <div v-if="status === 'loading' && src" class="player__chip" role="status"><UiSpinner :size="11" /> 正在载入预览…</div>
      <div v-else-if="status === 'waiting'" class="player__chip" role="status"><UiSpinner :size="11" /> 等待解码…</div>
      <div v-else-if="showOverlay && overlayState === 'loading'" class="player__chip player__chip--quiet" role="status"><UiSpinner :size="10" /> 正在定位帧 #{{ playhead.coarse.value }}</div>

      <div v-if="status === 'error'" class="player__error" role="alert">
        <MonitorX :size="20" :stroke-width="1.5" aria-hidden="true" />
        <p>{{ mediaError }}。下方仍显示单帧画面；源视频不受影响。</p>
        <UiButton size="sm" :icon="RotateCcw" @click="reload">重新载入预览</UiButton>
      </div>
    </div>

    <div class="transport" role="toolbar" aria-label="播放控制">
      <div class="transport__group">
        <IconButton :icon="SkipBack" label="跳到当前片段起点" kbd="Home" :disabled="!focusedClip" @click="focusedClip && onSeekReq(focusedClip.start_frame)" />
        <IconButton :icon="ChevronLeft" label="前一帧" kbd="←" @click="onSeekReq(playhead.frame - 1)" />
        <button
          type="button"
          class="transport__play"
          :class="{ 'is-playing': playing }"
          :aria-label="playing ? '暂停' : '播放'"
          :aria-disabled="!src || status === 'error' || undefined"
          v-tip="{ text: !src ? '此项目没有可播放的预览' : playing ? '暂停' : '播放', kbd: 'Space' }"
          @click="toggle"
        >
          <Pause v-if="playing" :size="17" fill="currentColor" :stroke-width="0" />
          <Play v-else :size="17" fill="currentColor" :stroke-width="0" style="margin-left: 2px" />
        </button>
        <IconButton :icon="ChevronRight" label="后一帧" kbd="→" @click="onSeekReq(playhead.frame + 1)" />
        <IconButton :icon="SkipForward" label="跳到当前片段最后一帧" kbd="End" :disabled="!focusedClip" @click="focusedClip && onSeekReq(focusedClip.end_frame - 1)" />
        <IconButton class="transport__repeat" :icon="Repeat" label="播放当前片段" :disabled="!focusedClip || !src" disabled-reason="需要可播放的预览" @click="focusedClip && playRange(focusedClip.start_frame, focusedClip.end_frame - 1)" />
      </div>
      <div class="transport__time num" aria-live="off">
        <span ref="timeEl" class="transport__now">00:00.000</span>
        <span class="muted transport__muted-total"> / {{ formatTime(totalUs) }}</span>
        <span ref="frameEl" class="transport__frame muted">#0</span>
      </div>
      <div class="transport__group transport__right">
        <div class="vol" :class="{ 'is-disabled': !hasAudio }" v-tip="hasAudio ? '预览音量：只影响试听，不改变导出音频' : '源视频无音轨'">
          <IconButton
            :icon="prefs.previewMuted || !hasAudio ? VolumeX : Volume2"
            :label="!hasAudio ? '预览音量（源视频无音轨）' : prefs.previewMuted ? '取消预览静音' : '预览静音'"
            size="sm"
            :disabled="!hasAudio"
            @click="prefs.previewMuted = !prefs.previewMuted"
          />
          <input
            v-model.number="prefs.previewVolume"
            type="range"
            min="0"
            max="1"
            step="0.05"
            class="vol__range"
            aria-label="预览音量（不影响导出）"
            :disabled="!hasAudio"
          />
        </div>
        <IconButton :icon="fit === 'fit' ? Shrink : Expand" :label="fit === 'fit' ? '显示实际像素（100%）' : '适应窗口'" :pressed="fit === 'actual'" @click="fit = fit === 'fit' ? 'actual' : 'fit'" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.player {
  container-type: inline-size;
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}
.player__stage {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 10px;
  overflow: hidden;
}
.player__stage.is-actual {
  overflow: auto;
  align-items: safe center;
  justify-content: safe center;
}
.player__view {
  position: relative;
  flex: none;
  background: #000;
  border-radius: var(--r-3);
  overflow: hidden;
}
.player__video,
.player__frame {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #000;
}
.player__chip {
  position: absolute;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--r-pill);
  background: rgba(0, 0, 0, 0.78);
  font-size: var(--fs-12);
  color: var(--text-2);
}
.player__chip--quiet {
  top: auto;
  bottom: 18px;
  left: auto;
  right: 18px;
  transform: none;
  background: rgba(0, 0, 0, 0.7);
}
.player__error {
  position: absolute;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 8px 12px;
  border-radius: var(--r-2);
  background: rgba(24, 10, 10, 0.94);
  border: 1px solid rgba(255, 69, 58, 0.4);
  font-size: var(--fs-13);
  max-width: calc(100% - 32px);
  color: var(--text-1);
}
.player__error svg {
  color: var(--danger);
  flex: none;
}
.transport {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 12px;
  height: 56px;
  padding: 0 12px;
  flex: none;
}
.transport__group {
  display: flex;
  align-items: center;
  gap: 2px;
}
.transport__right {
  justify-content: flex-end;
  gap: 6px;
}
.transport__play {
  width: 42px;
  height: 42px;
  margin: 0 6px;
  border-radius: 50%;
  background: var(--primary);
  color: var(--primary-text);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    transform var(--dur-spring) var(--ease-spring),
    box-shadow var(--dur-select) var(--ease-standard);
}
.transport__play:hover:not([aria-disabled]) {
  transform: scale(1.06);
}
.transport__play:active:not([aria-disabled]) {
  transform: scale(0.88);
}
.transport__play.is-playing {
  box-shadow: 0 0 0 6px rgba(255, 255, 255, 0.12);
}
.transport__play[aria-disabled] {
  opacity: 0.45;
}
.transport__time {
  font-size: var(--fs-13);
  white-space: nowrap;
}
.transport__now {
  color: var(--text-1);
  display: inline-block;
  min-width: 9ch;
  text-align: right;
}
.transport__frame {
  display: inline-block;
  min-width: 6ch;
  margin-left: 10px;
  font-size: var(--fs-12);
}
.vol {
  display: flex;
  align-items: center;
  gap: 4px;
}
.vol.is-disabled {
  opacity: 0.55;
}
.vol__range {
  width: 76px;
  accent-color: var(--text-2);
}
/* narrow centre column (compact window / high scaling): drop secondary controls, keep core ones */
@container (max-width: 620px) {
  .vol__range {
    width: 48px;
  }
  .transport__frame {
    display: none;
  }
}
@container (max-width: 500px) {
  .vol__range,
  .transport__repeat,
  .transport__muted-total {
    display: none;
  }
  .transport {
    gap: 6px;
  }
}
</style>
