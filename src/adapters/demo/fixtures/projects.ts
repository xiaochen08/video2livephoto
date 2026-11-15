/**
 * DEMO FIXTURES — 固定演示项目。Every project, batch and recent entry used by the demo lives here.
 * Time ranges, clip totals, cut counts and job counts are mutually consistent.
 */
import { makeError } from '@/domain/errors'
import { fileStem } from '@/domain/naming'
import { buildClips, type CoreContext } from '@/domain/timelineCore'
import type { Batch, Clip, Cut, ExportSettings, Job, Project, ProjectStatusTag, RecentProject, Timeline } from '@/domain/types'
import { newJob, nextId, type JobPlan } from '../exportSim'
import {
  HDR_LANDSCAPE,
  LANDSCAPE,
  LANDSCAPE_AUTO_COVERS,
  LANDSCAPE_CUTS,
  PORTRAIT,
  PORTRAIT_CUTS,
  seeded,
  syntheticMedia,
  type DemoMediaDef,
} from './media'

export type OpenBehavior = 'ok' | 'source_missing' | 'source_changed' | 'read_failed'

export interface DemoProjectRecord {
  project: Project
  mediaDef: DemoMediaDef
  past: { timeline: Timeline; label: string }[]
  future: { timeline: Timeline; label: string }[]
  openBehavior: OpenBehavior
  status: ProjectStatusTag
  updatedAt: string
  thumbFrame: number
  preflight: { externallyModified: number; locked: number }
  /** object URL created for a browser-picked file (revoked on reset) */
  objectUrl: string | null
  scenarioNote: string
}

export interface DemoBatchFixture {
  batch: Batch
  plans: Map<string, JobPlan>
}

export const DEFAULT_OUTPUT = 'D:\\导出\\Video2LivePhoto'

let clipSeq = 0
let cutSeq = 0
export const newClipId = () => `clip_${(++clipSeq).toString(36).padStart(4, '0')}`
export const newCutId = () => `cut_${(++cutSeq).toString(36).padStart(4, '0')}`

export function coreContextFor(def: DemoMediaDef): CoreContext {
  const s = def.media.video_streams[def.media.selected_video_stream ?? 0] ?? def.media.video_streams[0]
  const clear = def.key.startsWith('landscape') ? Object.values(LANDSCAPE_AUTO_COVERS) : []
  return {
    newClipId,
    newCutId,
    autoCover: (start, end) => clear.find((f) => f >= start && f < end) ?? start + Math.floor((end - start) * 0.4),
    ptsOf: (frame) =>
      ((BigInt(frame) * BigInt(s.time_base.den) * BigInt(s.frame_rate.den)) / (BigInt(s.time_base.num) * BigInt(s.frame_rate.num))).toString(),
  }
}

function cutsFrom(seeds: (Pick<Cut, 'frame' | 'kind'> & Partial<Cut>)[], ctx: CoreContext, allConfirmed = false): Cut[] {
  return seeds.map((s) => {
    const pending = !allConfirmed && s.review === 'pending'
    return {
      cut_id: newCutId(),
      pts: ctx.ptsOf(s.frame),
      transition: null,
      origin: 'analysis',
      reason: null,
      confidence: null,
      skipped: false,
      ...s,
      review: pending ? 'pending' : 'confirmed',
      confirmed_by: pending ? null : allConfirmed && s.review === 'pending' ? 'user' : 'analysis',
    }
  })
}

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString()

function settings(nameBase: string): ExportSettings {
  return { output_dir: DEFAULT_OUTPUT, quality: 'source', color: 'sdr_rec709', name_base: nameBase }
}

export function makeProject(opts: {
  id: string
  name: string
  def: DemoMediaDef
  cuts: Cut[]
  ctx: CoreContext
  sourcePath: string
  attrs?: (i: number, start: number, end: number) => Partial<Clip>
}): Project {
  const stream = opts.def.media.video_streams[opts.def.media.selected_video_stream ?? 0]
  const clips = buildClips(stream.frame_count, opts.cuts, opts.ctx, opts.attrs)
  const fileName = opts.sourcePath.split('\\').pop()!
  return {
    project_id: opts.id,
    schema_version: 3,
    name: opts.name,
    source: {
      path_display: opts.sourcePath,
      file_name: fileName,
      size_bytes: opts.def.media.size_bytes,
      modified_at: ago(60 * 26),
      fingerprint: 'sha256:9f2c…e41a（演示）',
      status: 'ok',
    },
    media: structuredClone(opts.def.media),
    analysis_version: 1,
    edit_version: 1,
    saved_edit_version: 1,
    timeline: { frame_count: stream.frame_count, cuts: opts.cuts, clips },
    history: { can_undo: false, can_redo: false, undo_label: null, redo_label: null },
    export_settings: settings(opts.name.replace(/[·&]/g, '').replace(/\s+/g, '').slice(0, 24) || '导出'),
    recovery_pending: false,
    outdated_clip_ids: [],
  }
}

function record(project: Project, def: DemoMediaDef, extra: Partial<DemoProjectRecord>): DemoProjectRecord {
  return {
    project,
    mediaDef: def,
    past: [],
    future: [],
    openBehavior: 'ok',
    status: 'ready_to_export',
    updatedAt: ago(30),
    thumbFrame: project.timeline.clips[0]?.cover.frame ?? 0,
    preflight: { externallyModified: 0, locked: 0 },
    objectUrl: null,
    scenarioNote: '',
    ...extra,
  }
}

/** Wedding clip attributes: example names, mixed audio, a user cover close to the flash cut. */
export function weddingAttrs(i: number): Partial<Clip> {
  const a: Partial<Clip> = {}
  if (i === 1) Object.assign(a, { name: '入场', name_origin: 'example' })
  if (i === 3) Object.assign(a, { name: '交换戒指', name_origin: 'example' })
  if (i === 5 || i === 6) a.audio = 'muted'
  if (i === 6) a.cover = { frame: 558, origin: 'user', status: 'valid' }
  return a
}

/** Demo-only content identifier (real pairing IDs are generated by the backend). */
export function pseudoUuid(): string {
  const h = () => Math.floor(Math.random() * 0x10000).toString(16).padStart(4, '0').toUpperCase()
  return `${h()}${h()}-${h()}-4${h().slice(1)}-${h()}-${h()}${h()}${h()}`
}

export function snapshotFor(project: Project, clips: Clip[], editVersion = project.edit_version) {
  return {
    snapshot_id: nextId('snap'),
    project_id: project.project_id,
    edit_version: editVersion,
    created_at: new Date().toISOString(),
    settings: structuredClone(project.export_settings),
    clips: clips.map((c) => ({
      clip_id: c.clip_id,
      display_index: c.display_index,
      start_frame: c.start_frame,
      end_frame: c.end_frame,
      audio: c.audio,
      cover_frame: c.cover.frame,
      file_stem: fileStem(project.export_settings.name_base, c.display_index),
      pair_id: pseudoUuid(),
    })),
  }
}

function finishedJob(job: Job, at: number, encoder: 'gpu' | 'cpu' = 'gpu'): Job {
  return {
    ...job,
    stage: 'succeeded',
    attempts: [{ attempt_id: nextId('att'), n: 1, encoder, started_at: ago(at + 2), ended_at: ago(at), result: 'succeeded', error: null }],
    artifacts: job.artifacts.map((a) => ({ ...a, status: 'committed', size_bytes: a.kind === 'jpg' ? '842113' : '18337520' })),
    verification: { ...job.verification, local: 'passed', local_report_id: `rep_${job.job_id}` },
    cancellable: false,
    previous_protected: false,
  }
}

export const ERR = {
  diskFull: (stem: string) =>
    makeError('DISK_FULL', `写入 ${stem}.mp4 时目标盘空间不足。`, {
      scope: { stage: 'encoding' },
      preserved: '已成功片段与旧版文件保持不变；本片段的临时文件已清理。',
      actions: ['choose_output_dir', 'retry_job', 'copy_error'],
      detail: 'ENOSPC: no space left on device, write — 模拟',
      retryable: true,
    }),
  fileLocked: (stem: string) =>
    makeError('FILE_LOCKED', `目标文件 ${stem}.mov 正被其他程序占用，无法替换。`, {
      scope: { stage: 'committing' },
      preserved: '新版已生成并通过校验，旧版文件未被修改，可在解除占用后直接重试提交。',
      actions: ['close_other_program', 'retry_job', 'open_output_dir', 'copy_error'],
      detail: 'EBUSY: resource busy or locked, rename — 模拟',
      retryable: true,
    }),
  workerExited: () =>
    makeError('WORKER_EXITED', '编码工作进程意外退出。', {
      scope: { stage: 'encoding' },
      preserved: '其他片段不受影响；本片段未生成任何成功文件。',
      actions: ['retry_job', 'open_diagnostics', 'copy_error'],
      detail: 'ffmpeg exited with code 3221225477 (0xC0000005) — 模拟',
      retryable: true,
    }),
}

function partialBatch(p: Project): DemoBatchFixture {
  const snap = snapshotFor(p, p.timeline.clips, 1)
  const batch_id = nextId('batch')
  const jobs = snap.clips.map((c) => newJob(batch_id, c, false))
  jobs.forEach((j, i) => {
    if (i === 3) {
      Object.assign(j, {
        stage: 'failed',
        attempts: [{ attempt_id: nextId('att'), n: 1, encoder: 'gpu', started_at: ago(42), ended_at: ago(41), result: 'failed', error: ERR.diskFull(j.file_stem) }],
        error: { ...ERR.diskFull(j.file_stem), scope: { stage: 'encoding', job_id: j.job_id, clip_id: j.clip_id } },
        artifacts: j.artifacts.map((a) => ({ ...a, status: 'failed' })),
      } satisfies Partial<Job>)
    } else if (i === 5) {
      Object.assign(j, {
        stage: 'failed',
        attempts: [{ attempt_id: nextId('att'), n: 1, encoder: 'gpu', started_at: ago(40), ended_at: ago(39), result: 'failed', error: ERR.fileLocked(j.file_stem) }],
        error: { ...ERR.fileLocked(j.file_stem), scope: { stage: 'committing', job_id: j.job_id, clip_id: j.clip_id } },
        artifacts: j.artifacts.map((a) => ({ ...a, status: a.kind === 'mov' ? 'failed' : 'verified' })),
        verification: { ...j.verification, local: 'passed', local_report_id: `rep_${j.job_id}` },
      } satisfies Partial<Job>)
    } else if (i === 9) {
      Object.assign(j, { stage: 'cancelled', cancel_wait_reason: '用户取消，已清理临时文件' } satisfies Partial<Job>)
    } else {
      Object.assign(j, finishedJob(j, 45 - i))
      if (i === 2) {
        j.attempts = [
          {
            attempt_id: nextId('att'),
            n: 1,
            encoder: 'gpu',
            started_at: ago(44),
            ended_at: ago(44),
            result: 'failed',
            error: makeError('GPU_ENCODE_FAILED', 'GPU 编码器在本片段返回错误，改用 CPU 从头重试。', { detail: 'nvenc: InitializeEncoder failed — 模拟' }),
          },
          { attempt_id: nextId('att'), n: 2, encoder: 'cpu', started_at: ago(44), ended_at: ago(43), result: 'succeeded', error: null },
        ]
      }
    }
    j.current_attempt_id = j.attempts[j.attempts.length - 1]?.attempt_id ?? null
  })
  return {
    batch: { batch_id, project_id: p.project_id, snapshot: snap, state: 'completed', created_at: ago(46), seq: 40, jobs, active_slots: 2 },
    plans: new Map(),
  }
}

function recoveryBatch(p: Project): DemoBatchFixture {
  const snap = snapshotFor(p, p.timeline.clips, 1)
  const batch_id = nextId('batch')
  const jobs = snap.clips.map((c) => newJob(batch_id, c, false))
  jobs.forEach((j, i) => {
    if (i < 4) Object.assign(j, finishedJob(j, 20 - i))
    else if (i === 4) {
      Object.assign(j, {
        stage: 'commit_unknown',
        attempts: [{ attempt_id: nextId('att'), n: 1, encoder: 'gpu', started_at: ago(15), ended_at: null, result: 'interrupted', error: null }],
        artifacts: j.artifacts.map((a) => ({ ...a, status: a.kind === 'mov' ? 'writing' : 'committed' })),
      } satisfies Partial<Job>)
    } else if (i === 5) {
      Object.assign(j, {
        stage: 'interrupted',
        attempts: [{ attempt_id: nextId('att'), n: 1, encoder: 'gpu', started_at: ago(15), ended_at: null, result: 'interrupted', error: null }],
        artifacts: j.artifacts.map((a) => ({ ...a, status: a.kind === 'jpg' ? 'verified' : 'pending' })),
      } satisfies Partial<Job>)
    } else Object.assign(j, { stage: 'interrupted' } satisfies Partial<Job>)
    j.current_attempt_id = j.attempts[j.attempts.length - 1]?.attempt_id ?? null
  })
  return {
    batch: { batch_id, project_id: p.project_id, snapshot: snap, state: 'interrupted', created_at: ago(16), seq: 30, jobs, active_slots: 2 },
    plans: new Map(),
  }
}

function largeBatch(p: Project): DemoBatchFixture {
  const clips = p.timeline.clips.slice(0, 100)
  const snap = snapshotFor(p, clips, 1)
  const batch_id = nextId('batch')
  const jobs = snap.clips.map((c) => newJob(batch_id, c, false))
  jobs.forEach((j, i) => {
    if (i < 38) Object.assign(j, finishedJob(j, 60 - i))
    if (i === 17) {
      Object.assign(j, {
        stage: 'failed',
        attempts: [{ attempt_id: nextId('att'), n: 1, encoder: 'gpu', started_at: ago(50), ended_at: ago(50), result: 'failed', error: ERR.workerExited() }],
        error: { ...ERR.workerExited(), scope: { stage: 'encoding', job_id: j.job_id, clip_id: j.clip_id } },
        artifacts: j.artifacts.map((a) => ({ ...a, status: 'failed' })),
        verification: { ...j.verification, local: 'pending', local_report_id: null },
      } satisfies Partial<Job>)
    }
    j.current_attempt_id = j.attempts[j.attempts.length - 1]?.attempt_id ?? null
  })
  return {
    batch: { batch_id, project_id: p.project_id, snapshot: snap, state: 'running', created_at: ago(62), seq: 200, jobs, active_slots: 2 },
    plans: new Map(),
  }
}

function largeProject(): { project: Project; def: DemoMediaDef } {
  const rand = seeded(150)
  const lens: number[] = []
  for (let i = 0; i < 150; i++) {
    let s = 1.5 + rand() * 9
    if (i % 37 === 5) s = 0.2 + rand() * 0.4
    if (i === 42 || i === 118) s = 32 + rand() * 6
    lens.push(Math.max(6, Math.round(s * 29.97)))
  }
  const total = lens.reduce((a, b) => a + b, 0)
  const def = syntheticMedia(total)
  const ctx = coreContextFor(def)
  let acc = 0
  const cutFrames = lens.slice(0, -1).map((l) => (acc += l))
  const cuts = cutsFrom(
    cutFrames.map((frame, i) =>
      i % 23 === 11
        ? { frame, kind: 'dissolve' as const, transition: { start_frame: frame - 6, end_frame: frame + 6 }, review: 'pending' as const, reason: '检测到 12 帧渐变过渡。', confidence: null }
        : { frame, kind: 'hard' as const, confidence: 0.9 },
    ),
    ctx,
  )
  const project = makeProject({
    id: 'p_large',
    name: '全天纪实 · 150 镜头',
    def,
    cuts,
    ctx,
    sourcePath: 'D:\\婚礼素材\\2024-09 全天\\全天纪实_粗剪定版.mp4',
    attrs: (i) => (i % 9 === 4 ? { audio: 'muted' } : {}),
  })
  return { project, def }
}

export interface DemoWorldSeed {
  records: DemoProjectRecord[]
  batches: DemoBatchFixture[]
}

export function buildWorld(preset: 'full' | 'first_run'): DemoWorldSeed {
  if (preset === 'first_run') return { records: [], batches: [] }
  const lctx = coreContextFor(LANDSCAPE)
  const wedding = makeProject({
    id: 'p_wedding',
    name: '林 & 周 婚礼成片',
    def: LANDSCAPE,
    cuts: cutsFrom(LANDSCAPE_CUTS, lctx),
    ctx: lctx,
    sourcePath: 'D:\\婚礼素材\\2024-10 林周\\婚礼成片_终版.mp4',
    attrs: weddingAttrs,
  })
  const pctx = coreContextFor(PORTRAIT)
  const portrait = makeProject({
    id: 'p_portrait',
    name: '外景花絮 · 竖屏',
    def: PORTRAIT,
    cuts: cutsFrom(PORTRAIT_CUTS, pctx),
    ctx: pctx,
    sourcePath: 'D:\\婚礼素材\\2024-10 林周\\花絮_竖屏.mov',
  })
  const single = makeProject({ id: 'p_single', name: '空镜 · 单镜头', def: LANDSCAPE, cuts: [], ctx: lctx, sourcePath: 'D:\\婚礼素材\\空镜\\酒店外景_单镜头.mp4' })
  const hctx = coreContextFor(HDR_LANDSCAPE)
  const hdr = makeProject({ id: 'p_hdr', name: 'HLG 测试片', def: HDR_LANDSCAPE, cuts: cutsFrom(LANDSCAPE_CUTS, hctx, true), ctx: hctx, sourcePath: 'D:\\测试\\HLG_测试片.mov' })
  const partial = makeProject({
    id: 'p_partial',
    name: '陈氏婚礼 MV',
    def: LANDSCAPE,
    cuts: cutsFrom(LANDSCAPE_CUTS, lctx, true),
    ctx: lctx,
    sourcePath: 'D:\\婚礼素材\\2024-08 陈氏\\陈氏婚礼MV_定版.mp4',
  })
  const recovery = makeProject({ id: 'p_recovery', name: '晚宴快剪', def: LANDSCAPE, cuts: cutsFrom(LANDSCAPE_CUTS, lctx, true), ctx: lctx, sourcePath: 'D:\\婚礼素材\\2024-10 林周\\晚宴快剪.mp4' })
  recovery.recovery_pending = true
  const moved = makeProject({ id: 'p_moved', name: '订婚短片', def: LANDSCAPE, cuts: cutsFrom(LANDSCAPE_CUTS, lctx, true), ctx: lctx, sourcePath: 'D:\\婚礼素材\\订婚\\订婚短片.mp4' })
  moved.source.status = 'missing'
  const changed = makeProject({ id: 'p_changed', name: '旅拍预告', def: LANDSCAPE, cuts: cutsFrom(LANDSCAPE_CUTS, lctx, true), ctx: lctx, sourcePath: 'D:\\旅拍\\旅拍预告.mp4' })
  changed.source.status = 'changed'
  const broken = makeProject({ id: 'p_broken', name: '工作室样片', def: LANDSCAPE, cuts: [], ctx: lctx, sourcePath: 'D:\\样片\\工作室样片.mp4' })
  const large = largeProject()

  const records: DemoProjectRecord[] = [
    record(wedding, LANDSCAPE, { status: 'needs_review', updatedAt: ago(12), thumbFrame: 290, scenarioNote: '普通多镜头：0.2/0.8 秒短镜头、31 秒长镜头、叠化、闪光与快速运动候选、混合静音、封面靠近切点' }),
    record(portrait, PORTRAIT, { status: 'needs_review', updatedAt: ago(95), thumbFrame: 200, scenarioNote: '竖屏 29.97fps，源视频无音轨' }),
    record(large.project, large.def, { status: 'exporting', updatedAt: ago(3), thumbFrame: 400, scenarioNote: '150 个镜头 + 100 个任务的队列（演示替代帧）' }),
    record(partial, LANDSCAPE, { status: 'partial_failed', updatedAt: ago(40), thumbFrame: 1560, preflight: { externallyModified: 1, locked: 0 }, scenarioNote: '部分失败：磁盘满、文件占用、GPU 回退成功、旧输出被外部修改' }),
    record(recovery, LANDSCAPE, { status: 'recovery_pending', updatedAt: ago(15), thumbFrame: 1100, scenarioNote: '意外退出：已成功、提交中断、可复用中间结果' }),
    record(hdr, HDR_LANDSCAPE, { status: 'ready_to_export', updatedAt: ago(60 * 24 * 2), thumbFrame: 420, scenarioNote: 'HLG HDR 源：默认转 Rec.709 SDR；HDR 输出取决于后端能力' }),
    record(single, LANDSCAPE, { status: 'ready_to_export', updatedAt: ago(60 * 24 * 3), thumbFrame: 1100, scenarioNote: '无切点：整条视频作为 1 个片段（超长提醒）' }),
    record(moved, LANDSCAPE, { status: 'source_missing', openBehavior: 'source_missing', updatedAt: ago(60 * 24 * 6), thumbFrame: 160, scenarioNote: '原视频已移动：需要后端核对身份后重新定位' }),
    record(changed, LANDSCAPE, { status: 'source_changed', openBehavior: 'source_changed', updatedAt: ago(60 * 24 * 9), thumbFrame: 660, scenarioNote: '原视频身份变化：同名但大小/指纹不同' }),
    record(broken, LANDSCAPE, { status: 'read_failed', openBehavior: 'read_failed', updatedAt: ago(60 * 24 * 14), thumbFrame: 40, scenarioNote: '项目数据库读取失败' }),
  ]
  return { records, batches: [partialBatch(partial), recoveryBatch(recovery), largeBatch(large.project)] }
}

export function recentOf(r: DemoProjectRecord): RecentProject {
  const t = r.project.timeline
  const stream = r.project.media.video_streams[0]
  return {
    project_id: r.project.project_id,
    name: r.project.name,
    updated_at: r.updatedAt,
    status: r.status,
    clip_count: r.openBehavior === 'read_failed' ? null : t.clips.length,
    pending_review: r.openBehavior === 'read_failed' ? null : t.cuts.filter((c) => c.review === 'pending').length,
    source_name: r.project.source.file_name,
    thumb_key: `${r.project.project_id}:${r.thumbFrame}`,
    orientation: stream.height > stream.width ? 'portrait' : 'landscape',
  }
}
