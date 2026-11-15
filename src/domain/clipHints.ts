import { clipDurationUs } from './time'
import type { Capabilities, Clip, Cut, Timeline, VideoStreamInfo } from './types'

export type ClipHint = 'short' | 'long' | 'cover' | 'review' | 'muted'

export function clipHints(clip: Clip, index: number, t: Timeline, stream: VideoStreamInfo, caps: Capabilities): ClipHint[] {
  const hints: ClipHint[] = []
  const ms = clipDurationUs(clip, stream) / 1000
  if (ms < caps.livephoto_hint.short_below_ms) hints.push('short')
  if (ms > caps.livephoto_hint.long_above_ms) hints.push('long')
  if (clip.cover.status === 'out_of_range') hints.push('cover')
  const leftCut: Cut | undefined = t.cuts[index - 1]
  const rightCut: Cut | undefined = t.cuts[index]
  if (leftCut?.review === 'pending' || rightCut?.review === 'pending') hints.push('review')
  return hints
}

export const CUT_KIND_LABEL: Record<Cut['kind'], string> = {
  hard: '硬切',
  dissolve: '叠化',
  flash_candidate: '闪光候选',
  fast_motion_candidate: '快速运动候选',
  manual: '手动切点',
}

export const CUT_KIND_EXPLAIN: Record<Cut['kind'], string> = {
  hard: '画面在相邻两帧之间直接切换。',
  dissolve: '两个镜头交叠过渡。切点放在过渡的真实时间中点并吸附到合法帧边界（等距时取较早边界）；过渡内的全部画面都会保留在两侧片段中，已合成的叠化画面保持原样。',
  flash_candidate: '检测到短时亮度突变，可能是闪光灯或强光，而不是镜头切换。若属于同一镜头，请删除该切点（合并两侧片段）。',
  fast_motion_candidate: '检测到快速运动或甩镜，画面变化大但可能仍是同一镜头。请逐帧确认。',
  manual: '由你手动添加的切点。',
}
