import type { Batch, BatchState, Job, JobStage } from './types'

/**
 * UI display states for export jobs. Every UI state is derived from backend data, so a new
 * display state is always traceable to (job.stage, batch.state, flags). See BACKEND_CONTRACT §任务状态映射.
 */
export type JobUiState =
  | 'queued' // 待执行
  | 'processing' // 处理中（编码）
  | 'verifying' // 校验中
  | 'committing' // 提交中
  | 'succeeded' // 成功
  | 'failed' // 失败
  | 'skipped' // 已跳过 / 已取消
  | 'outdated' // 待更新（成功但编辑已变化）
  | 'interrupted' // 已中断
  | 'pause_wait' // 暂停请求：当前片段完成后停止
  | 'paused' // 已暂停（未领取）
  | 'recovery' // 恢复待确认
  | 'commit_unknown' // 提交中断，待核查

export type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted'

export const JOB_UI_META: Record<JobUiState, { label: string; tone: Tone; icon: string }> = {
  queued: { label: '待执行', tone: 'neutral', icon: 'clock' },
  processing: { label: '处理中', tone: 'accent', icon: 'spinner' },
  verifying: { label: '校验中', tone: 'accent', icon: 'spinner' },
  committing: { label: '提交中', tone: 'accent', icon: 'spinner' },
  succeeded: { label: '成功', tone: 'success', icon: 'check' },
  failed: { label: '失败', tone: 'danger', icon: 'x' },
  skipped: { label: '已跳过', tone: 'muted', icon: 'skip' },
  outdated: { label: '待更新', tone: 'warning', icon: 'refresh' },
  interrupted: { label: '已中断', tone: 'warning', icon: 'pause' },
  pause_wait: { label: '暂停请求', tone: 'warning', icon: 'spinner' },
  paused: { label: '已暂停', tone: 'neutral', icon: 'pause' },
  recovery: { label: '恢复待确认', tone: 'warning', icon: 'alert' },
  commit_unknown: { label: '待核查', tone: 'warning', icon: 'alert' },
}

export function isRunningStage(stage: JobStage): boolean {
  return stage === 'encoding' || stage === 'verifying' || stage === 'committing'
}

export function jobUiState(job: Job, batch: Pick<Batch, 'state'>, opts: { outdated?: boolean; recovery?: boolean } = {}): JobUiState {
  const bs: BatchState = batch.state
  switch (job.stage) {
    case 'queued':
      if (opts.recovery) return 'recovery'
      if (bs === 'paused' || bs === 'pause_requested') return 'paused'
      if (bs === 'stopped' || bs === 'stop_requested') return 'skipped'
      if (bs === 'interrupted') return 'interrupted'
      return 'queued'
    case 'encoding':
      return bs === 'pause_requested' ? 'pause_wait' : 'processing'
    case 'verifying':
      return bs === 'pause_requested' ? 'pause_wait' : 'verifying'
    case 'committing':
      return bs === 'pause_requested' ? 'pause_wait' : 'committing'
    case 'succeeded':
      return opts.outdated ? 'outdated' : 'succeeded'
    case 'failed':
      return 'failed'
    case 'skipped':
    case 'cancelled':
      return 'skipped'
    case 'interrupted':
      return opts.recovery ? 'recovery' : 'interrupted'
    case 'commit_unknown':
      return 'commit_unknown'
  }
}

export const STAGE_LABEL: Record<JobStage, string> = {
  queued: '等待领取',
  encoding: '编码',
  verifying: '本地校验',
  committing: '安全提交',
  succeeded: '已提交',
  failed: '失败',
  skipped: '已跳过',
  cancelled: '已取消',
  interrupted: '已中断',
  commit_unknown: '提交中断',
}

export const BATCH_STATE_LABEL: Record<BatchState, string> = {
  running: '运行中',
  pause_requested: '暂停请求中',
  paused: '已暂停',
  stop_requested: '正在停止',
  stopped: '已停止',
  completed: '已完成',
  interrupted: '已中断',
}

export function batchIsActive(b: Pick<Batch, 'state'>): boolean {
  return b.state === 'running' || b.state === 'pause_requested' || b.state === 'stop_requested'
}

export interface BatchCounts {
  total: number
  succeeded: number
  failed: number
  skipped: number
  running: number
  queued: number
  interrupted: number
  commitUnknown: number
}

/** Counts by clip result (one job per clip). Failed attempts never count as extra items. */
export function countBatch(b: Batch): BatchCounts {
  const c: BatchCounts = { total: b.jobs.length, succeeded: 0, failed: 0, skipped: 0, running: 0, queued: 0, interrupted: 0, commitUnknown: 0 }
  for (const j of b.jobs) {
    if (j.stage === 'succeeded') c.succeeded++
    else if (j.stage === 'failed') c.failed++
    else if (j.stage === 'skipped' || j.stage === 'cancelled') c.skipped++
    else if (isRunningStage(j.stage)) c.running++
    else if (j.stage === 'queued') c.queued++
    else if (j.stage === 'interrupted') c.interrupted++
    else if (j.stage === 'commit_unknown') c.commitUnknown++
  }
  return c
}
