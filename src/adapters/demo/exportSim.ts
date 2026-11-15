/**
 * DEMO export scheduler (模拟). Mimics the backend resource manager so the UI can be verified:
 * slots start at 1 and grow to max_parallel_jobs after the first success; GPU failure restarts
 * the clip from frame 0 on CPU as a new attempt; success only after verify + commit.
 * All timing and outcomes are simulated and must never be shown as real results.
 */
import type { TaskEvent } from '@/adapters/contract'
import { makeError } from '@/domain/errors'
import { isRunningStage } from '@/domain/jobStates'
import type { AppError, Artifact, Attempt, Batch, BatchId, ExportSnapshot, Job, JobId, ProjectId } from '@/domain/types'

export interface JobPlan {
  gpuFailAt?: number
  fail?: { stage: 'encoding' | 'committing'; at: number; error: AppError }
  commitInterrupt?: boolean
}

interface SimJob {
  job: Job
  plan: JobPlan
  frames: number
  ticksInStage: number
}

interface SimBatch {
  batch: Batch
  jobs: Map<JobId, SimJob>
}

export interface SimHooks {
  maxSlots(): number
  gpuAvailable(): boolean
  onJobSucceeded(projectId: ProjectId, job: Job, batch: Batch): void
  onInterrupted(projectId: ProjectId, batch: Batch): void
  log(line: string): void
}

let idCounter = 0
export const nextId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${(++idCounter).toString(36).padStart(3, '0')}`

const now = () => new Date().toISOString()
const clone = <T>(v: T): T => structuredClone(v)

export function artifactsFor(stem: string): Artifact[] {
  return [
    { kind: 'mp4', file_name: `${stem}.mp4`, rel_dir: '视频片段', status: 'pending', size_bytes: null },
    { kind: 'jpg', file_name: `${stem}.jpg`, rel_dir: 'LivePhoto', status: 'pending', size_bytes: null },
    { kind: 'mov', file_name: `${stem}.mov`, rel_dir: 'LivePhoto', status: 'pending', size_bytes: null },
  ]
}

export function newJob(batchId: BatchId, c: ExportSnapshot['clips'][number], replaces: boolean): Job {
  return {
    job_id: nextId('job'),
    batch_id: batchId,
    clip_id: c.clip_id,
    display_index: c.display_index,
    file_stem: c.file_stem,
    stage: 'queued',
    progress: null,
    attempts: [],
    current_attempt_id: null,
    artifacts: artifactsFor(c.file_stem),
    error: null,
    cancellable: true,
    cancel_wait_reason: null,
    cancel_requested: false,
    verification: { local: 'pending', local_report_id: null, devices: { iphone: 'unverified', wechat_moments: 'unverified', xiaohongshu: 'unverified', douyin: 'unverified' } },
    replaces_previous: replaces,
    previous_protected: replaces,
  }
}

export class ExportSimulator {
  private batches = new Map<BatchId, SimBatch>()
  private listeners = new Map<ProjectId, Set<(e: TaskEvent) => void>>()
  private timer: ReturnType<typeof setInterval> | null = null
  private held: { fn: () => void } | null = null
  speed = 1
  chaos = false

  constructor(private hooks: SimHooks) {}

  dispose() {
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    this.batches.clear()
    this.listeners.clear()
  }

  subscribe(projectId: ProjectId, fn: (e: TaskEvent) => void): () => void {
    let set = this.listeners.get(projectId)
    if (!set) this.listeners.set(projectId, (set = new Set()))
    set.add(fn)
    // snapshot first, then incremental events
    for (const b of this.batchesOf(projectId)) queueMicrotask(() => fn({ type: 'batch_snapshot', project_id: projectId, batch: clone(b) }))
    return () => set!.delete(fn)
  }

  batchesOf(projectId: ProjectId): Batch[] {
    return [...this.batches.values()].filter((b) => b.batch.project_id === projectId).map((b) => b.batch)
  }

  anyActive(): boolean {
    return [...this.batches.values()].some((b) => ['running', 'pause_requested', 'stop_requested'].includes(b.batch.state))
  }

  get(batchId: BatchId): Batch | undefined {
    return this.batches.get(batchId)?.batch
  }

  findJob(jobId: JobId): { sb: SimBatch; sj: SimJob } | null {
    for (const sb of this.batches.values()) {
      const sj = sb.jobs.get(jobId)
      if (sj) return { sb, sj }
    }
    return null
  }

  /** Insert a batch (fixture or new). Fixtures may arrive already in a final state. */
  add(batch: Batch, plans: Map<JobId, JobPlan>, framesOf: (job: Job) => number) {
    const jobs = new Map<JobId, SimJob>()
    for (const j of batch.jobs) jobs.set(j.job_id, { job: j, plan: plans.get(j.job_id) ?? {}, frames: framesOf(j), ticksInStage: 0 })
    this.batches.set(batch.batch_id, { batch, jobs })
    this.ensureTimer()
  }

  private ensureTimer() {
    if (!this.timer) this.timer = setInterval(() => this.tick(), 150)
  }

  /* --------------------------------- control --------------------------------- */

  pause(batchId: BatchId) {
    const sb = this.batches.get(batchId)
    if (!sb || sb.batch.state !== 'running') return
    this.setBatch(sb, { state: this.activeCount(sb) ? 'pause_requested' : 'paused' })
  }

  resume(batchId: BatchId) {
    const sb = this.batches.get(batchId)
    if (!sb || (sb.batch.state !== 'paused' && sb.batch.state !== 'pause_requested')) return
    this.setBatch(sb, { state: 'running' })
  }

  stop(batchId: BatchId) {
    const sb = this.batches.get(batchId)
    if (!sb || !['running', 'paused', 'pause_requested'].includes(sb.batch.state)) return
    for (const sj of sb.jobs.values()) {
      if (sj.job.stage === 'encoding') this.cancelEncoding(sb, sj, '整批停止，已清理临时文件')
      else if (sj.job.stage === 'queued') this.patchJob(sb, sj, { stage: 'skipped', progress: null })
    }
    this.setBatch(sb, { state: this.activeCount(sb) ? 'stop_requested' : 'stopped' })
  }

  cancel(jobId: JobId): { immediate: boolean; wait_reason: string | null } {
    const f = this.findJob(jobId)
    if (!f) return { immediate: false, wait_reason: '任务不存在' }
    const { sb, sj } = f
    if (sj.job.stage === 'queued') {
      this.patchJob(sb, sj, { stage: 'cancelled' })
      return { immediate: true, wait_reason: null }
    }
    if (sj.job.stage === 'encoding') {
      this.cancelEncoding(sb, sj, '用户取消，已清理临时文件')
      return { immediate: true, wait_reason: null }
    }
    if (sj.job.stage === 'verifying') {
      const reason = '正在本地校验，校验步骤结束后取消并清理临时产物。'
      this.patchJob(sb, sj, { cancel_requested: true, cancel_wait_reason: reason })
      return { immediate: false, wait_reason: reason }
    }
    const reason = '正在安全提交文件，必须完成或回滚后才能停止，以免新旧版本混杂。'
    this.patchJob(sb, sj, { cancel_requested: true, cancel_wait_reason: reason })
    return { immediate: false, wait_reason: reason }
  }

  retryFailed(batchId: BatchId, jobIds?: JobId[]): number {
    const sb = this.batches.get(batchId)
    if (!sb) return 0
    let n = 0
    for (const sj of sb.jobs.values()) {
      if (sj.job.stage !== 'failed') continue
      if (jobIds && !jobIds.includes(sj.job.job_id)) continue
      sj.plan = {}
      this.patchJob(sb, sj, { stage: 'queued', error: null, progress: null, artifacts: artifactsFor(sj.job.file_stem), cancel_requested: false, cancel_wait_reason: null })
      n++
    }
    if (n && !['running', 'pause_requested'].includes(sb.batch.state)) this.setBatch(sb, { state: 'running', active_slots: 1 })
    return n
  }

  continueRemaining(batchId: BatchId): number {
    const sb = this.batches.get(batchId)
    if (!sb) return 0
    let n = 0
    for (const sj of sb.jobs.values()) {
      if (['skipped', 'cancelled', 'interrupted', 'failed'].includes(sj.job.stage)) {
        sj.plan = {}
        this.patchJob(sb, sj, { stage: 'queued', error: null, progress: null, artifacts: artifactsFor(sj.job.file_stem), cancel_requested: false, cancel_wait_reason: null })
        n++
      }
    }
    this.setBatch(sb, { state: 'running', active_slots: 1 })
    return n
  }

  /** Recovery check result for commit_unknown jobs */
  /** DEMO: simulate an unexpected app exit while this batch runs. */
  crash(batchId: BatchId): boolean {
    const sb = this.batches.get(batchId)
    if (!sb || !['running', 'pause_requested', 'stop_requested', 'paused'].includes(sb.batch.state)) return false
    for (const sj of sb.jobs.values()) {
      if (sj.job.stage === 'committing') this.patchJob(sb, sj, { stage: 'commit_unknown', attempts: this.endAttempt(sj, 'interrupted', null), progress: null })
      else if (isRunningStage(sj.job.stage)) this.patchJob(sb, sj, { stage: 'interrupted', attempts: this.endAttempt(sj, 'interrupted', null), progress: null })
      else if (sj.job.stage === 'queued') this.patchJob(sb, sj, { stage: 'interrupted' })
    }
    this.setBatch(sb, { state: 'interrupted' })
    return true
  }

  resolveCommitUnknown(batchId: BatchId, verified: boolean) {
    const sb = this.batches.get(batchId)
    if (!sb) return
    for (const sj of sb.jobs.values()) {
      if (sj.job.stage !== 'commit_unknown') continue
      if (verified) {
        this.patchJob(sb, sj, {
          stage: 'succeeded',
          artifacts: sj.job.artifacts.map((a) => ({ ...a, status: 'committed' })),
          verification: { ...sj.job.verification, local: 'passed', local_report_id: `rep_${sj.job.job_id}` },
          previous_protected: false,
        })
      } else {
        this.patchJob(sb, sj, { stage: 'interrupted', error: makeError('COMMIT_INCOMPLETE', '提交未完成，旧版本已恢复，需要重新生成。', { preserved: '旧版文件保持原样' }) })
      }
    }
  }

  /* ---------------------------------- ticking --------------------------------- */

  private activeCount(sb: SimBatch) {
    let n = 0
    for (const sj of sb.jobs.values()) if (isRunningStage(sj.job.stage)) n++
    return n
  }

  private tick() {
    for (const sb of this.batches.values()) this.tickBatch(sb)
  }

  private tickBatch(sb: SimBatch) {
    const b = sb.batch
    if (!['running', 'pause_requested', 'stop_requested'].includes(b.state)) return
    for (const sj of sb.jobs.values()) if (isRunningStage(sj.job.stage)) this.advance(sb, sj)
    if (sb.batch.state === 'interrupted') return

    const active = this.activeCount(sb)
    if (b.state === 'running' && active < b.active_slots) {
      const next = [...sb.jobs.values()].find((sj) => sj.job.stage === 'queued')
      if (next) this.startAttempt(sb, next, this.hooks.gpuAvailable() ? 'gpu' : 'cpu')
    }
    const nowActive = this.activeCount(sb)
    if (b.state === 'pause_requested' && nowActive === 0) this.setBatch(sb, { state: 'paused' })
    else if (b.state === 'stop_requested' && nowActive === 0) this.setBatch(sb, { state: 'stopped' })
    else if (b.state === 'running' && nowActive === 0 && ![...sb.jobs.values()].some((sj) => sj.job.stage === 'queued')) {
      this.setBatch(sb, { state: 'completed' })
    }
  }

  private startAttempt(sb: SimBatch, sj: SimJob, encoder: 'gpu' | 'cpu') {
    const attempt: Attempt = {
      attempt_id: nextId('att'),
      n: sj.job.attempts.length + 1,
      encoder,
      started_at: now(),
      ended_at: null,
      result: 'running',
      error: null,
    }
    sj.ticksInStage = 0
    this.patchJob(sb, sj, {
      stage: 'encoding',
      attempts: [...sj.job.attempts, attempt],
      current_attempt_id: attempt.attempt_id,
      progress: { kind: 'frames', done: 0, total: sj.frames },
      cancellable: true,
      cancel_wait_reason: null,
      artifacts: sj.job.artifacts.map((a) => (a.kind === 'mp4' ? { ...a, status: 'writing' } : a)),
    })
  }

  private endAttempt(sj: SimJob, result: Attempt['result'], error: AppError | null): Attempt[] {
    return sj.job.attempts.map((a) => (a.attempt_id === sj.job.current_attempt_id ? { ...a, result, error, ended_at: now() } : a))
  }

  private cancelEncoding(sb: SimBatch, sj: SimJob, note: string) {
    this.patchJob(sb, sj, {
      stage: 'cancelled',
      attempts: this.endAttempt(sj, 'cancelled', null),
      progress: null,
      artifacts: artifactsFor(sj.job.file_stem),
      cancel_wait_reason: note,
    })
  }

  private advance(sb: SimBatch, sj: SimJob) {
    const job = sj.job
    sj.ticksInStage++
    const attempt = job.attempts.find((a) => a.attempt_id === job.current_attempt_id)
    if (job.stage === 'encoding' && job.progress?.kind === 'frames') {
      const perTick = Math.max(1, Math.round((attempt?.encoder === 'cpu' ? 18 : 36) * this.speed))
      const done = Math.min(job.progress.total, job.progress.done + perTick)
      const frac = done / job.progress.total
      if (attempt?.encoder === 'gpu' && sj.plan.gpuFailAt !== undefined && frac >= sj.plan.gpuFailAt) {
        const err = makeError('GPU_ENCODE_FAILED', 'GPU 编码器在本片段返回错误，改用 CPU 从头重试。', {
          scope: { job_id: job.job_id, clip_id: job.clip_id, stage: 'encoding' },
          detail: 'nvenc: InitializeEncoder failed: out of memory (10) — 模拟',
        })
        this.patchJob(sb, sj, { attempts: this.endAttempt(sj, 'failed', err), artifacts: artifactsFor(job.file_stem) })
        this.hooks.log(`[sim] ${job.file_stem} GPU 失败 → CPU 重试`)
        this.startAttempt(sb, sj, 'cpu')
        return
      }
      if (sj.plan.fail?.stage === 'encoding' && frac >= sj.plan.fail.at) {
        this.failJob(sb, sj, sj.plan.fail.error)
        return
      }
      if (done >= job.progress.total) {
        sj.ticksInStage = 0
        this.patchJob(sb, sj, {
          stage: 'verifying',
          progress: { kind: 'artifacts', done: 0, total: 3 },
          artifacts: job.artifacts.map((a) => ({ ...a, status: 'writing' })),
        })
      } else {
        this.patchJob(sb, sj, { progress: { kind: 'frames', done, total: job.progress.total } })
      }
      return
    }
    if (job.stage === 'verifying') {
      if (sj.ticksInStage % 2 !== 0) return
      const done = Math.min(3, (job.progress?.kind === 'artifacts' ? job.progress.done : 0) + 1)
      const artifacts = job.artifacts.map((a, i) => (i < done ? { ...a, status: 'verified' as const, size_bytes: String(a.kind === 'jpg' ? 820_000 + i : 6_400_000 + sj.frames * 41_000) } : a))
      if (done < 3) {
        this.patchJob(sb, sj, { progress: { kind: 'artifacts', done, total: 3 }, artifacts })
        return
      }
      if (job.cancel_requested) {
        this.patchJob(sb, sj, { stage: 'cancelled', attempts: this.endAttempt(sj, 'cancelled', null), artifacts: artifactsFor(job.file_stem), progress: null, cancel_wait_reason: '校验结束后已取消并清理临时产物' })
        return
      }
      sj.ticksInStage = 0
      this.patchJob(sb, sj, {
        stage: 'committing',
        progress: { kind: 'unknown', note: job.replaces_previous ? '新版校验通过，正在替换旧版（旧版保留为备份直至完成）' : '正在移动到输出目录' },
        artifacts,
        cancellable: false,
        cancel_wait_reason: job.cancel_requested ? job.cancel_wait_reason : null,
        verification: { ...job.verification, local: 'passed', local_report_id: `rep_${job.job_id}` },
      })
      return
    }
    if (job.stage === 'committing') {
      if (sj.plan.commitInterrupt && sj.ticksInStage >= 2) {
        this.patchJob(sb, sj, { stage: 'commit_unknown', attempts: this.endAttempt(sj, 'interrupted', null), progress: null })
        for (const other of sb.jobs.values()) {
          if (other !== sj && isRunningStage(other.job.stage)) this.patchJob(sb, other, { stage: 'interrupted', attempts: this.endAttempt(other, 'interrupted', null), progress: null })
          else if (other.job.stage === 'queued') this.patchJob(sb, other, { stage: 'interrupted' })
        }
        this.setBatch(sb, { state: 'interrupted' })
        this.hooks.onInterrupted(sb.batch.project_id, sb.batch)
        return
      }
      if (sj.plan.fail?.stage === 'committing' && sj.ticksInStage >= 2) {
        this.failJob(sb, sj, sj.plan.fail.error)
        return
      }
      if (sj.ticksInStage < 3) return
      this.patchJob(sb, sj, {
        stage: 'succeeded',
        progress: null,
        attempts: this.endAttempt(sj, 'succeeded', null),
        artifacts: job.artifacts.map((a) => ({ ...a, status: 'committed' })),
        cancel_wait_reason: null,
        previous_protected: false,
      })
      if (sb.batch.active_slots < this.hooks.maxSlots()) this.setBatch(sb, { active_slots: Math.min(this.hooks.maxSlots(), sb.batch.active_slots + 1) })
      this.hooks.onJobSucceeded(sb.batch.project_id, sj.job, sb.batch)
    }
  }

  private failJob(sb: SimBatch, sj: SimJob, error: AppError) {
    this.patchJob(sb, sj, {
      stage: 'failed',
      error: { ...error, scope: { ...error.scope, job_id: sj.job.job_id, clip_id: sj.job.clip_id } },
      attempts: this.endAttempt(sj, 'failed', error),
      progress: null,
      artifacts: sj.job.artifacts.map((a) => (a.status === 'committed' ? a : { ...a, status: 'failed' })),
      previous_protected: sj.job.replaces_previous,
    })
    this.hooks.log(`[sim] ${sj.job.file_stem} 失败 ${error.code}`)
  }

  /* ---------------------------------- events ---------------------------------- */

  private setBatch(sb: SimBatch, patch: Partial<Pick<Batch, 'state' | 'active_slots'>>) {
    Object.assign(sb.batch, patch)
    const seq = ++sb.batch.seq
    this.emit(sb.batch.project_id, { type: 'batch_patch', project_id: sb.batch.project_id, batch_id: sb.batch.batch_id, seq, patch: { ...patch } })
  }

  private patchJob(sb: SimBatch, sj: SimJob, patch: Partial<Job>) {
    Object.assign(sj.job, patch)
    const seq = ++sb.batch.seq
    this.emit(sb.batch.project_id, {
      type: 'job_patch',
      project_id: sb.batch.project_id,
      batch_id: sb.batch.batch_id,
      seq,
      job_id: sj.job.job_id,
      attempt_id: sj.job.current_attempt_id,
      patch: clone(patch),
    })
  }

  private emit(projectId: ProjectId, e: TaskEvent) {
    const set = this.listeners.get(projectId)
    if (!set?.size) return
    const send = () => set.forEach((fn) => fn(e))
    if (!this.chaos) return send()
    const r = Math.random()
    if (r < 0.03) return // dropped → client detects the gap and re-fetches a snapshot
    if (r < 0.15) {
      send()
      setTimeout(send, 40) // duplicate
      return
    }
    if (r < 0.25 && !this.held) {
      this.held = { fn: send } // re-ordered: released after the next event
      return
    }
    send()
    if (this.held) {
      const h = this.held
      this.held = null
      h.fn()
    }
  }
}
