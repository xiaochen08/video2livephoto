/**
 * Reference implementation of timeline edit semantics.
 *
 * Used by the DemoAdapter and by unit tests. In production the backend timeline core is the
 * authority: the UI only sends EditCommand and renders the returned Timeline. This file must not
 * be imported by page components.
 */
import type { EditCommand } from './commands'
import type { AudioMode, Clip, ClipId, CoverInfo, Cut, Timeline } from './types'

export class TimelineError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

export interface CoreContext {
  newClipId(): ClipId
  newCutId(): string
  /** backend "clear frame" selection – demo picks a deterministic frame */
  autoCover(start: number, end: number): number
  ptsOf(frame: number): string | null
}

export interface CoreResult {
  timeline: Timeline
  affected_clip_ids: ClipId[]
  removed_clip_ids: ClipId[]
  notes: string[]
}

function cloneTimeline(t: Timeline): Timeline {
  return {
    frame_count: t.frame_count,
    cuts: t.cuts.map((c) => ({ ...c, transition: c.transition ? { ...c.transition } : null })),
    clips: t.clips.map((c) => ({ ...c, cover: { ...c.cover } })),
  }
}

function reindex(t: Timeline, ctx: CoreContext): void {
  t.clips.sort((a, b) => a.start_frame - b.start_frame)
  t.cuts.sort((a, b) => a.frame - b.frame)
  t.clips.forEach((c, i) => {
    c.display_index = i + 1
    c.start_pts = ctx.ptsOf(c.start_frame)
    c.end_pts = ctx.ptsOf(c.end_frame)
  })
}

function fixCover(clip: Clip, ctx: CoreContext, notes: string[]): void {
  const inside = clip.cover.frame >= clip.start_frame && clip.cover.frame < clip.end_frame
  if (inside) {
    if (clip.cover.status === 'out_of_range') clip.cover.status = 'valid'
    return
  }
  if (clip.cover.origin === 'auto') {
    clip.cover = { frame: ctx.autoCover(clip.start_frame, clip.end_frame), origin: 'auto', status: 'valid' }
  } else {
    clip.cover = { ...clip.cover, status: 'out_of_range' }
    notes.push(`片段 ${clip.display_index} 的封面已不在片段范围内，需要重新选择。`)
  }
}

/** Validates contiguity and half-open ranges. Throws on invariant violation. */
export function assertTimeline(t: Timeline): void {
  if (t.clips.length !== t.cuts.length + 1) throw new TimelineError('INVARIANT', '片段与切点数量不一致')
  let cursor = 0
  t.clips.forEach((c, i) => {
    if (c.start_frame !== cursor) throw new TimelineError('INVARIANT', `片段 ${c.clip_id} 不连续`)
    if (c.end_frame <= c.start_frame) throw new TimelineError('INVARIANT', `片段 ${c.clip_id} 长度为 0`)
    if (i < t.cuts.length && t.cuts[i].frame !== c.end_frame) throw new TimelineError('INVARIANT', '切点与片段边界不一致')
    cursor = c.end_frame
  })
  if (cursor !== t.frame_count) throw new TimelineError('INVARIANT', '片段未覆盖全部帧')
}

export function buildClips(
  frameCount: number,
  cuts: Cut[],
  ctx: CoreContext,
  attrs: (index: number, start: number, end: number) => Partial<Clip> = () => ({}),
): Clip[] {
  const bounds = [0, ...cuts.map((c) => c.frame), frameCount]
  const clips: Clip[] = []
  for (let i = 0; i < bounds.length - 1; i++) {
    const start = bounds[i]
    const end = bounds[i + 1]
    const extra = attrs(i, start, end)
    clips.push({
      clip_id: ctx.newClipId(),
      start_frame: start,
      end_frame: end,
      start_pts: ctx.ptsOf(start),
      end_pts: ctx.ptsOf(end),
      display_index: i + 1,
      name: null,
      name_origin: 'default',
      export_selected: true,
      audio: 'source',
      cover: { frame: ctx.autoCover(start, end), origin: 'auto', status: 'valid' },
      ...extra,
    })
  }
  return clips
}

function mergeRun(t: Timeline, fromIdx: number, toIdx: number, audio: AudioMode | undefined, ctx: CoreContext, notes: string[]) {
  const run = t.clips.slice(fromIdx, toIdx + 1)
  const audios = new Set(run.map((c) => c.audio))
  if (audios.size > 1 && !audio) {
    throw new TimelineError('AUDIO_CONFLICT', '合并的片段音频设置不同，需要选择合并后的音频设置。')
  }
  const keep = run[0]
  const userCover = run.find((c) => c.cover.origin === 'user' && c.cover.status !== 'out_of_range')
  const merged: Clip = {
    ...keep,
    end_frame: run[run.length - 1].end_frame,
    audio: audio ?? keep.audio,
    export_selected: run.some((c) => c.export_selected),
    cover: userCover ? { ...userCover.cover } : ({ frame: 0, origin: 'auto', status: 'valid' } as CoverInfo),
  }
  if (!userCover) merged.cover.frame = ctx.autoCover(merged.start_frame, merged.end_frame)
  const removed = run.slice(1).map((c) => c.clip_id)
  t.clips.splice(fromIdx, run.length, merged)
  // remove cuts strictly inside merged range
  t.cuts = t.cuts.filter((c) => c.frame <= merged.start_frame || c.frame >= merged.end_frame)
  fixCover(merged, ctx, notes)
  return { merged, removed }
}

export function applyCommand(input: Timeline, cmd: EditCommand, ctx: CoreContext): CoreResult {
  const t = cloneTimeline(input)
  const notes: string[] = []
  let affected: ClipId[] = []
  let removed: ClipId[] = []

  switch (cmd.type) {
    case 'add_cut': {
      const idx = t.clips.findIndex((c) => cmd.frame > c.start_frame && cmd.frame < c.end_frame)
      if (idx < 0) {
        const onBoundary = t.cuts.some((c) => c.frame === cmd.frame)
        throw new TimelineError(
          onBoundary ? 'CUT_EXISTS' : 'CUT_OUT_OF_RANGE',
          onBoundary ? '此位置已经有切点。' : '切点需要位于片段内部，并且两侧至少保留 1 帧。',
        )
      }
      const left = t.clips[idx]
      const right: Clip = {
        ...left,
        clip_id: ctx.newClipId(),
        start_frame: cmd.frame,
        name: null,
        name_origin: 'default',
        cover: { ...left.cover },
      }
      left.end_frame = cmd.frame
      t.clips.splice(idx + 1, 0, right)
      t.cuts.push({
        cut_id: ctx.newCutId(),
        frame: cmd.frame,
        pts: ctx.ptsOf(cmd.frame),
        kind: 'manual',
        transition: null,
        review: 'confirmed',
        confirmed_by: 'user',
        skipped: false,
        origin: 'user',
        reason: null,
        confidence: null,
      })
      reindex(t, ctx)
      // right side: keep an inherited user cover only if it falls inside it
      if (right.cover.origin === 'user' && right.cover.frame < right.start_frame) {
        right.cover = { frame: ctx.autoCover(right.start_frame, right.end_frame), origin: 'auto', status: 'valid' }
      }
      if (left.cover.origin === 'user' && left.cover.frame >= left.end_frame) {
        // the user cover now belongs to the right clip; left falls back to auto
        left.cover = { frame: ctx.autoCover(left.start_frame, left.end_frame), origin: 'auto', status: 'valid' }
      }
      fixCover(left, ctx, notes)
      fixCover(right, ctx, notes)
      affected = [left.clip_id, right.clip_id]
      break
    }
    case 'move_cut': {
      const ci = t.cuts.findIndex((c) => c.cut_id === cmd.cut_id)
      if (ci < 0) throw new TimelineError('CUT_NOT_FOUND', '切点已不存在，可能已被其他操作修改。')
      const left = t.clips[ci]
      const right = t.clips[ci + 1]
      if (cmd.frame <= left.start_frame || cmd.frame >= right.end_frame) {
        throw new TimelineError('CUT_OUT_OF_RANGE', '切点不能越过相邻切点，两侧片段至少保留 1 帧。')
      }
      t.cuts[ci].frame = cmd.frame
      t.cuts[ci].pts = ctx.ptsOf(cmd.frame)
      left.end_frame = cmd.frame
      right.start_frame = cmd.frame
      reindex(t, ctx)
      fixCover(left, ctx, notes)
      fixCover(right, ctx, notes)
      affected = [left.clip_id, right.clip_id]
      break
    }
    case 'remove_cut': {
      const ci = t.cuts.findIndex((c) => c.cut_id === cmd.cut_id)
      if (ci < 0) throw new TimelineError('CUT_NOT_FOUND', '切点已不存在。')
      const r = mergeRun(t, ci, ci + 1, cmd.audio_resolution, ctx, notes)
      reindex(t, ctx)
      affected = [r.merged.clip_id]
      removed = r.removed
      break
    }
    case 'merge_clips': {
      const idxs = cmd.clip_ids.map((id) => t.clips.findIndex((c) => c.clip_id === id)).sort((a, b) => a - b)
      if (idxs.length < 2 || idxs.some((i) => i < 0)) throw new TimelineError('MERGE_INVALID', '至少需要选择 2 个存在的片段。')
      for (let i = 1; i < idxs.length; i++) {
        if (idxs[i] !== idxs[i - 1] + 1) throw new TimelineError('MERGE_NOT_CONTIGUOUS', '只能合并时间上相邻的片段。')
      }
      const r = mergeRun(t, idxs[0], idxs[idxs.length - 1], cmd.audio_resolution, ctx, notes)
      reindex(t, ctx)
      affected = [r.merged.clip_id]
      removed = r.removed
      break
    }
    case 'set_clip_props': {
      for (const id of cmd.clip_ids) {
        const c = t.clips.find((x) => x.clip_id === id)
        if (!c) throw new TimelineError('CLIP_NOT_FOUND', '片段已不存在。')
        if (cmd.patch.audio) c.audio = cmd.patch.audio
        if (cmd.patch.export_selected !== undefined) c.export_selected = cmd.patch.export_selected
        if (cmd.patch.name !== undefined) {
          const name = cmd.patch.name?.trim() || null
          c.name = name
          c.name_origin = name ? 'user' : 'default'
        }
      }
      affected = [...cmd.clip_ids]
      break
    }
    case 'set_cover': {
      const c = t.clips.find((x) => x.clip_id === cmd.clip_id)
      if (!c) throw new TimelineError('CLIP_NOT_FOUND', '片段已不存在。')
      if (cmd.frame === null) {
        c.cover = { frame: ctx.autoCover(c.start_frame, c.end_frame), origin: 'auto', status: 'valid' }
      } else {
        if (cmd.frame < c.start_frame || cmd.frame >= c.end_frame) {
          throw new TimelineError('COVER_OUT_OF_RANGE', '封面必须位于当前片段的有效帧范围内。')
        }
        c.cover = { frame: cmd.frame, origin: 'user', status: 'valid' }
      }
      affected = [c.clip_id]
      break
    }
    case 'regenerate_cover': {
      const c = t.clips.find((x) => x.clip_id === cmd.clip_id)
      if (!c) throw new TimelineError('CLIP_NOT_FOUND', '片段已不存在。')
      c.cover = { frame: ctx.autoCover(c.start_frame, c.end_frame), origin: 'auto', status: 'valid' }
      affected = [c.clip_id]
      break
    }
    case 'review_cut': {
      const cut = t.cuts.find((c) => c.cut_id === cmd.cut_id)
      if (!cut) throw new TimelineError('CUT_NOT_FOUND', '切点已不存在。')
      if (cmd.action === 'confirm') {
        cut.review = 'confirmed'
        cut.confirmed_by = 'user'
        cut.skipped = false
      } else {
        cut.skipped = true
      }
      const ci = t.cuts.indexOf(cut)
      affected = [t.clips[ci].clip_id, t.clips[ci + 1].clip_id]
      break
    }
  }

  assertTimeline(t)
  return { timeline: t, affected_clip_ids: affected, removed_clip_ids: removed, notes }
}

/**
 * Dissolve cut placement rule: true time midpoint snapped to a legal frame boundary;
 * on a tie the earlier boundary wins. Times in µs; boundaries are frame start times.
 */
export function dissolveCutFrame(startUs: number, endUs: number, frameStartsUs: number[]): number {
  const mid = (startUs + endUs) / 2
  let best = 0
  let bestDist = Infinity
  frameStartsUs.forEach((t, i) => {
    const d = Math.abs(t - mid)
    if (d < bestDist - 1e-9) {
      best = i
      bestDist = d
    }
  })
  return best
}

export function pendingCuts(t: Timeline): Cut[] {
  return t.cuts.filter((c) => c.review === 'pending')
}

export function audioConflict(clips: Clip[]): boolean {
  return new Set(clips.map((c) => c.audio)).size > 1
}
