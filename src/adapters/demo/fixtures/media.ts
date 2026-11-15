/**
 * DEMO FIXTURES — 演示数据，仅供 DemoAdapter 使用。
 * Frame ranges mirror scripts/make-demo-media.sh exactly (landscape 1650 frames @25fps,
 * portrait 420 frames @30000/1001). Source-file metadata (4K HEVC etc.) is a fictional
 * description of the "original" file; the bundled MP4 acts as a low-resolution preview proxy.
 */
import landscapeUrl from '@/assets/media/demo-landscape.mp4'
import portraitUrl from '@/assets/media/demo-portrait.mp4'
import type { ColorInfo, Cut, MediaInfo, VideoStreamInfo } from '@/domain/types'

export interface DemoMediaDef {
  key: string
  previewUrl: string | null
  previewWidth: number
  previewHeight: number
  media: MediaInfo
}

const SDR: ColorInfo = { transfer: 'bt709', primaries: 'bt709', dolby_vision: false, log_profile: null, bit_depth: 8 }

function stream(partial: Partial<VideoStreamInfo> & Pick<VideoStreamInfo, 'width' | 'height' | 'frame_rate' | 'frame_count'>): VideoStreamInfo {
  const duration_us = Math.round((partial.frame_count * 1_000_000 * partial.frame_rate.den) / partial.frame_rate.num)
  return {
    stream_index: 0,
    codec: 'hevc',
    display_aspect: { num: partial.width, den: partial.height },
    rotation_deg: 0,
    vfr: false,
    time_base: { num: 1, den: 90000 },
    duration_us,
    color: SDR,
    is_default: true,
    title: null,
    ...partial,
  }
}

export const LANDSCAPE: DemoMediaDef = {
  key: 'landscape',
  previewUrl: landscapeUrl,
  previewWidth: 640,
  previewHeight: 360,
  media: {
    container: 'mp4',
    size_bytes: '2184339456',
    duration_us: 66_000_000,
    video_streams: [stream({ width: 3840, height: 2160, frame_rate: { num: 25, den: 1 }, frame_count: 1650, display_aspect: { num: 16, den: 9 } })],
    audio_streams: [{ stream_index: 1, codec: 'aac', channels: 2, sample_rate: 48000, is_mixed_main: true }],
    selected_video_stream: 0,
  },
}

export const PORTRAIT: DemoMediaDef = {
  key: 'portrait',
  previewUrl: portraitUrl,
  previewWidth: 360,
  previewHeight: 640,
  media: {
    container: 'mov',
    size_bytes: '612368384',
    duration_us: 14_014_000,
    video_streams: [
      stream({
        codec: 'h264',
        width: 1080,
        height: 1920,
        frame_rate: { num: 30000, den: 1001 },
        frame_count: 420,
        display_aspect: { num: 9, den: 16 },
        time_base: { num: 1, den: 30000 },
      }),
    ],
    audio_streams: [],
    selected_video_stream: 0,
  },
}

export const HDR_LANDSCAPE: DemoMediaDef = {
  ...LANDSCAPE,
  key: 'landscape-hdr',
  media: {
    ...LANDSCAPE.media,
    video_streams: [
      {
        ...LANDSCAPE.media.video_streams[0],
        color: { transfer: 'hlg', primaries: 'bt2020', dolby_vision: false, log_profile: null, bit_depth: 10 },
      },
    ],
  },
}

export const MULTI_STREAM: DemoMediaDef = {
  ...LANDSCAPE,
  key: 'landscape-multistream',
  media: {
    ...LANDSCAPE.media,
    container: 'mov',
    video_streams: [
      { ...LANDSCAPE.media.video_streams[0], stream_index: 0, is_default: false, title: '主画面 4K' },
      {
        ...LANDSCAPE.media.video_streams[0],
        stream_index: 2,
        width: 1920,
        height: 1080,
        codec: 'h264',
        is_default: true,
        title: '低码率预览流（相机生成）',
        color: { ...SDR, transfer: 'unknown', primaries: 'unknown', bit_depth: null },
      },
    ],
    selected_video_stream: null,
  },
}

/** Deterministic PRNG so large fixtures are identical on every reset. */
export function seeded(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 2 ** 32
  }
}

export function syntheticMedia(frameCount: number): DemoMediaDef {
  return {
    key: 'synthetic-150',
    previewUrl: null,
    previewWidth: 640,
    previewHeight: 360,
    media: {
      container: 'mp4',
      size_bytes: '18874368000',
      duration_us: Math.round((frameCount * 1_000_000 * 1001) / 30000),
      video_streams: [
        stream({
          codec: 'h264',
          width: 3840,
          height: 2160,
          frame_rate: { num: 30000, den: 1001 },
          frame_count: frameCount,
          display_aspect: { num: 16, den: 9 },
          time_base: { num: 1, den: 30000 },
        }),
      ],
      audio_streams: [{ stream_index: 1, codec: 'aac', channels: 2, sample_rate: 48000, is_mixed_main: true }],
      selected_video_stream: 0,
    },
  }
}

type CutSeed = Pick<Cut, 'frame' | 'kind'> & Partial<Cut>

/** Analysis output of the landscape demo video (see make-demo-media.sh) */
export const LANDSCAPE_CUTS: CutSeed[] = [
  { frame: 100, kind: 'hard', confidence: 0.98 },
  { frame: 225, kind: 'hard', confidence: 0.95 },
  { frame: 230, kind: 'hard', confidence: 0.91 },
  {
    frame: 355,
    kind: 'dissolve',
    transition: { start_frame: 349, end_frame: 361 },
    review: 'pending',
    reason: '检测到 12 帧渐变过渡（0.48 秒）。切点取真实时间中点 14.20 秒并吸附到第 355 帧。',
    confidence: null,
  },
  { frame: 480, kind: 'hard', confidence: 0.97 },
  { frame: 500, kind: 'hard', confidence: 0.93 },
  {
    frame: 561,
    kind: 'flash_candidate',
    review: 'pending',
    reason: '第 559–562 帧亮度骤升后恢复，前后构图一致，可能是闪光灯。',
    confidence: 0.41,
  },
  { frame: 625, kind: 'hard', confidence: 0.96 },
  {
    frame: 700,
    kind: 'fast_motion_candidate',
    review: 'pending',
    reason: '运动幅度在第 700 帧附近突变，可能是甩镜而非镜头切换。',
    confidence: 0.52,
  },
  { frame: 750, kind: 'hard', confidence: 0.99 },
  { frame: 1525, kind: 'hard', confidence: 0.97 },
]

export const PORTRAIT_CUTS: CutSeed[] = [
  { frame: 120, kind: 'hard', confidence: 0.96 },
  { frame: 132, kind: 'hard', confidence: 0.88 },
  { frame: 300, kind: 'hard', confidence: null, review: 'pending', reason: '画面亮度相近，分析未提供置信分数，建议检查。' },
]

/** Hand-picked "clear frames" standing in for the backend's auto cover choice. */
export const LANDSCAPE_AUTO_COVERS: Record<number, number> = {
  0: 40,
  1: 160,
  2: 227,
  3: 290,
  4: 420,
  5: 490,
  6: 530,
  7: 595,
  8: 660,
  9: 725,
  10: 1100,
  11: 1560,
}
