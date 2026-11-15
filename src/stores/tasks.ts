import { computed, reactive } from 'vue'
import type { CreateBatchRequest, TaskEvent, V2LPAdapter } from '@/adapters/contract'
import { toAppError } from '@/domain/errors'
import { requestId } from '@/domain/ids'
import { batchIsActive, countBatch } from '@/domain/jobStates'
import type { AppError, Batch, BatchId, Job, JobId, ProjectId } from '@/domain/types'

const RESYNC_DELAY_MS = 250

/**
 * Task state mirror. Ordering rules (see BACKEND_CONTRACT §事件顺序):
 *  - every patch carries a per-batch `seq`; seq ≤ applied → duplicate, dropped
 *  - seq = applied+1 → applied, buffered successors drained
 *  - seq > applied+1 → buffered; if the gap is not filled quickly, fetch a batch snapshot and
 *    replay buffered events newer than the snapshot
 *  - events for another project / an older subscription token are ignored
 *  - progress for a non-current attempt is ignored (attempt history still arrives via `attempts`)
 */
export function createTasks(adapter: V2LPAdapter) {
  const state = reactive({
    projectId: null as ProjectId | null,
    token: 0,
    batches: {} as Record<BatchId, Batch>,
    order: [] as BatchId[],
    /** in-flight UI actions keyed by intent → prevents duplicate submissions */
    inflight: {} as Record<string, string>,
    lastError: null as AppError | null,
    resyncs: 0,
    dropped: 0,
  })
  const buffers = new Map<BatchId, TaskEvent[]>()
  const resyncTimers = new Map<BatchId, ReturnType<typeof setTimeout>>()
  let unsubscribe: (() => void) | null = null

  function attach(projectId: ProjectId) {
    detach()
    state.projectId = projectId
    const token = ++state.token
    unsubscribe = adapter.tasks.subscribe(projectId, (e) => {
      if (token !== state.token || e.project_id !== state.projectId) return
      handle(e)
    })
  }

  function detach() {
    unsubscribe?.()
    unsubscribe = null
    state.token++
    state.projectId = null
    state.batches = {}
    state.order = []
    buffers.clear()
    resyncTimers.forEach((t) => clearTimeout(t))
    resyncTimers.clear()
  }

  function upsert(b: Batch) {
    const cur = state.batches[b.batch_id]
    if (cur && cur.seq > b.seq) return // older snapshot
    state.batches[b.batch_id] = b
    if (!state.order.includes(b.batch_id)) state.order.unshift(b.batch_id)
  }

  function handle(e: TaskEvent) {
    if (e.type === 'batch_snapshot') {
      upsert(e.batch)
      drain(e.batch.batch_id)
      return
    }
    const b = state.batches[e.batch_id]
    if (!b) {
      bufferAndResync(e)
      return
    }
    if (e.seq <= b.seq) {
      state.dropped++
      return
    }
    if (e.seq > b.seq + 1) {
      bufferAndResync(e)
      return
    }
    applyPatch(b, e)
    drain(b.batch_id)
  }

  function applyPatch(b: Batch, e: Exclude<TaskEvent, { type: 'batch_snapshot' }>) {
    b.seq = e.seq
    if (e.type === 'batch_patch') {
      Object.assign(b, e.patch)
      return
    }
    const job = b.jobs.find((j) => j.job_id === e.job_id)
    if (!job) return
    const patch = { ...e.patch }
    const switchesAttempt = patch.current_attempt_id !== undefined
    if (!switchesAttempt && e.attempt_id && job.current_attempt_id && e.attempt_id !== job.current_attempt_id) {
      delete patch.progress
      delete patch.stage
    }
    Object.assign(job, patch)
  }

  function bufferAndResync(e: Exclude<TaskEvent, { type: 'batch_snapshot' }>) {
    const list = buffers.get(e.batch_id) ?? []
    list.push(e)
    if (list.length > 500) list.splice(0, list.length - 500)
    buffers.set(e.batch_id, list)
    if (resyncTimers.has(e.batch_id)) return
    const token = state.token
    resyncTimers.set(
      e.batch_id,
      setTimeout(async () => {
        resyncTimers.delete(e.batch_id)
        // gap may have been filled meanwhile
        drain(e.batch_id)
        if (!buffers.get(e.batch_id)?.length) return
        try {
          const snap = await adapter.tasks.getBatch(e.batch_id)
          if (token !== state.token) return
          state.resyncs++
          upsert(snap)
          drain(e.batch_id)
        } catch (err) {
          state.lastError = toAppError(err)
        }
      }, RESYNC_DELAY_MS),
    )
  }

  function drain(batchId: BatchId) {
    const b = state.batches[batchId]
    const list = buffers.get(batchId)
    if (!b || !list?.length) return
    list.sort((x, y) => (x as { seq: number }).seq - (y as { seq: number }).seq)
    while (list.length) {
      const next = list[0] as Exclude<TaskEvent, { type: 'batch_snapshot' }>
      if (next.seq <= b.seq) {
        list.shift()
        continue
      }
      if (next.seq !== b.seq + 1) break
      list.shift()
      applyPatch(b, next)
    }
  }

  /** Runs `fn` once per intent key while it is in flight (double-click safe). */
  async function once<T>(key: string, fn: (rid: string) => Promise<T>): Promise<T | null> {
    if (state.inflight[key]) return null
    const rid = requestId(key.split(':')[0])
    state.inflight[key] = rid
    try {
      return await fn(rid)
    } catch (e) {
      state.lastError = toAppError(e)
      throw state.lastError
    } finally {
      delete state.inflight[key]
    }
  }

  const busy = (key: string) => !!state.inflight[key]

  async function createBatch(req: Omit<CreateBatchRequest, 'request_id'>, rid: string) {
    const res = await adapter.export.createBatch({ ...req, request_id: rid })
    if (state.projectId === req.project_id) {
      const b = await adapter.tasks.getBatch(res.batch_id)
      if (state.projectId === req.project_id) upsert(b)
    }
    return res
  }

  const batches = computed(() => state.order.map((id) => state.batches[id]).filter(Boolean))
  const activeBatch = computed(() => batches.value.find((b) => batchIsActive(b) || b.state === 'paused') ?? null)
  const latestBatch = computed(() => batches.value[0] ?? null)
  const attentionBatch = computed(() => batches.value.find((b) => b.state === 'interrupted' || b.state === 'stopped') ?? null)

  /** Most recent job per clip across batches (newest batch wins). */
  const latestJobByClip = computed(() => {
    const map = new Map<string, { job: Job; batch: Batch }>()
    for (const b of batches.value) for (const j of b.jobs) if (!map.has(j.clip_id)) map.set(j.clip_id, { job: j, batch: b })
    return map
  })

  /** Edit version of the newest batch that produced at least one success. */
  const lastSuccessVersion = computed(() => {
    const b = batches.value.find((x) => x.jobs.some((j) => j.stage === 'succeeded'))
    return b ? { edit_version: b.snapshot.edit_version, batch_id: b.batch_id, created_at: b.created_at } : null
  })
  const runningVersion = computed(() => {
    const b = activeBatch.value
    return b ? { edit_version: b.snapshot.edit_version, batch_id: b.batch_id } : null
  })
  const activeCounts = computed(() => (activeBatch.value ? countBatch(activeBatch.value) : null))

  return {
    state,
    attach,
    detach,
    once,
    busy,
    createBatch,
    batches,
    activeBatch,
    latestBatch,
    attentionBatch,
    latestJobByClip,
    lastSuccessVersion,
    runningVersion,
    activeCounts,
    /** test hook */
    _handle: handle,
    pause: (b: BatchId) => once(`pause:${b}`, (rid) => adapter.tasks.pauseQueue(b, rid)),
    resume: (b: BatchId) => once(`resume:${b}`, (rid) => adapter.tasks.resumeQueue(b, rid)),
    stop: (b: BatchId) => once(`stop:${b}`, (rid) => adapter.tasks.stopBatch(b, rid)),
    cancelJob: (j: JobId) => once(`cancel:${j}`, (rid) => adapter.tasks.cancelJob(j, rid)),
    retryFailed: (b: BatchId, jobIds?: JobId[]) => once(`retry:${b}:${jobIds?.join(',') ?? 'all'}`, (rid) => adapter.tasks.retryFailed(b, rid, jobIds)),
  }
}

export type TasksStore = ReturnType<typeof createTasks>
