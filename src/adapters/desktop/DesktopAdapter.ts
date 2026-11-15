import type {
  AnalysisEvent,
  AnalysisHandle,
  AppSettings,
  ConnectionInfo,
  FileRef,
  FrameRequest,
  FrameResult,
  OpenProjectResult,
  PreflightResult,
  ProbeResult,
  RecoveryProgress,
  RecoverySummary,
  TaskEvent,
  V2LPAdapter,
} from '@/adapters/contract'
import type { EditCommand } from '@/domain/commands'
import { AdapterError, makeError } from '@/domain/errors'
import type { Project } from '@/domain/types'

type M3Bridge = {
  request(method: string, params?: Record<string, unknown>): Promise<any>
  cancel?(previewRequestId: string): Promise<any>
  pickFile(options?: Record<string, unknown>): Promise<string | null>
  pathForFile?(file: File): string | null
  on?(channel: string, listener: (payload: unknown) => void): () => void
  quit?(): Promise<void>
}

declare global {
  interface Window {
    m3?: M3Bridge
  }
}

function isRecord(value: unknown): value is Record<string, any> {
  return !!value && typeof value === 'object'
}

function asAppError(error: unknown, fallbackCode = 'IPC_ERROR'): AdapterError {
  if (error instanceof AdapterError) return error
  const value = isRecord(error) ? error : {}
  const code = typeof value.code === 'string' ? value.code : fallbackCode
  const message = typeof value.message === 'string' ? value.message : String(error)
  return new AdapterError(makeError(code, message, { detail: value.details ?? value.detail ?? null, retryable: Boolean(value.retryable), actions: value.retryable ? ['retry'] : [] }))
}

function abortError(): DOMException {
  return new DOMException('操作已取消。', 'AbortError')
}

function normalizeFile(path: string): FileRef {
  const name = path.split(/[\\/]/).pop() || path
  return { kind: 'desktop', ref_id: path, display_path: path, name, size_bytes: '0' }
}

function normalizeProject(raw: any): Project {
  if (raw?.timeline && raw?.media && raw?.source) return raw as Project
  const sourcePath = String(raw?.source_path || '')
  const probe = raw?.probe || {}
  const streams = Array.isArray(probe.streams) ? probe.streams : []
  const videos = streams.filter((stream: any) => stream?.codec_type === 'video')
  const audios = streams.filter((stream: any) => stream?.codec_type === 'audio')
  const selected = Number.isInteger(probe.selected_video_stream) ? probe.selected_video_stream : videos[0]?.index ?? null
  const container = probe.container || {}
  const sourceIdentity = raw?.source_identity || {}
  const cuts = (raw?.cuts || []).map((cut: any) => ({
    cut_id: String(cut.cut_id), frame: Number(cut.boundary_index), pts: null, kind: ['hard', 'dissolve', 'flash_candidate', 'fast_motion_candidate', 'manual'].includes(cut.kind) ? cut.kind : 'manual', transition: null,
    review: cut.needs_review && !cut.checked ? 'pending' : 'confirmed', confirmed_by: cut.checked ? (cut.origin === 'detector' ? 'analysis' : 'user') : null, skipped: false,
    origin: cut.origin === 'detector' ? 'analysis' : 'user', reason: cut.reason ?? null, confidence: cut.confidence ?? null,
  }))
  const clips = (raw?.segments || []).map((segment: any) => ({
    clip_id: String(segment.clip_id), start_frame: Number(segment.start_index), end_frame: Number(segment.end_index), start_pts: null, end_pts: null,
    display_index: Number(segment.output_number || 0), name: null, name_origin: 'default', export_selected: segment.selected_for_export !== false,
    audio: segment.audio_enabled === false ? 'muted' : 'source', cover: { frame: Number(segment.cover_frame_index ?? segment.start_index), origin: segment.cover_frame_index == null ? 'auto' : 'user', status: 'valid' },
  }))
  const durationUs = Math.round(Number(container.duration_seconds || 0) * 1_000_000)
  const media = {
    container: String((container.format_names || ['unknown'])[0]), size_bytes: String(sourceIdentity.size || 0), duration_us: durationUs,
    video_streams: videos.map((stream: any) => ({
      stream_index: Number(stream.index), codec: String(stream.codec_name || 'unknown'), width: Number(stream.width || 0), height: Number(stream.height || 0),
      display_aspect: stream.display_aspect_ratio || { num: Number(stream.width || 1), den: Number(stream.height || 1) }, rotation_deg: Number(stream.rotation || 0),
      frame_rate: stream.avg_frame_rate_hint || stream.frame_rate_hint || { num: 0, den: 1 }, vfr: false, frame_count: Number(stream.index) === selected ? Number(raw?.frame_count || 0) : 0,
      time_base: stream.time_base || { num: 1, den: 1 }, duration_us: Math.round(Number(stream.duration_seconds || container.duration_seconds || 0) * 1_000_000),
      color: { transfer: 'unknown', primaries: 'unknown', dolby_vision: false, log_profile: null, bit_depth: null }, is_default: Boolean(stream.disposition?.default), title: stream.tags?.title || null,
    })),
    audio_streams: audios.map((stream: any) => ({ stream_index: Number(stream.index), codec: String(stream.codec_name || 'unknown'), channels: Number(stream.channels || 0), sample_rate: Number(stream.sample_rate || 0), is_mixed_main: null })),
    selected_video_stream: selected,
  }
  const stem = sourcePath.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, '') || 'Video2LivePhoto'
  return {
    project_id: String(raw?.project_id || sourcePath), schema_version: 1, name: stem,
    source: { path_display: sourcePath, file_name: sourcePath.split(/[\\/]/).pop() || sourcePath, size_bytes: String(sourceIdentity.size || 0), modified_at: String(sourceIdentity.mtime_ns || ''), fingerprint: sourceIdentity.full_sha256 || sourceIdentity.sampled_fingerprint || null, status: 'ok' },
    media, analysis_version: 1, edit_version: Number(raw?.saved_revision || 0), saved_edit_version: Number(raw?.saved_revision || 0),
    timeline: { frame_count: Number(raw?.frame_count || 0), cuts, clips }, history: { can_undo: false, can_redo: false, undo_label: null, redo_label: null },
    export_settings: { output_dir: `${sourcePath.split(/[\\/]/).slice(0, -1).join('\\')}\\导出`, quality: 'source', color: 'sdr_rec709', name_base: stem }, recovery_pending: false, outdated_clip_ids: [],
  }
}

function projectFromResponse(response: any): Project {
  return normalizeProject(response?.project ?? response?.result?.project ?? response)
}

type PreviewConsumer = {
  resolve: (value: FrameResult) => void
  reject: (reason: unknown) => void
  signal?: AbortSignal
  abortHandler?: () => void
  aborted: boolean
}

type PreviewEntry = {
  key: string
  requestId: string
  request: FrameRequest
  consumers: Set<PreviewConsumer>
  started: boolean
  settled: boolean
  cancelSent: boolean
}

export class DesktopAdapter implements V2LPAdapter {
  readonly mode = 'desktop' as const
  private readonly bridge: M3Bridge | null = typeof window !== 'undefined' ? window.m3 ?? null : null
  private readonly previewMaxConcurrent = 2
  private previewActive = 0
  private previewSequence = 0
  private readonly previewQueue: PreviewEntry[] = []
  private readonly previewEntries = new Map<string, PreviewEntry>()

  private async call<T>(method: string, params: object = {}, signal?: AbortSignal, timeoutMs = 60_000): Promise<T> {
    if (!this.bridge) throw asAppError({ code: 'BRIDGE_UNAVAILABLE', message: '未检测到桌面桥接，正式模式不会使用演示数据。', retryable: true }, 'BRIDGE_UNAVAILABLE')
    if (signal?.aborted) throw abortError()
    let timer: ReturnType<typeof setTimeout> | undefined
    let onAbort: (() => void) | undefined
    try {
      const operation = this.bridge.request(method, params as Record<string, unknown>)
      const guarded = new Promise<T>((resolve, reject) => {
        timer = setTimeout(() => reject(asAppError({ code: 'BACKEND_TIMEOUT', message: `桌面后端在 ${timeoutMs}ms 内没有响应。`, retryable: true }, 'BACKEND_TIMEOUT')), timeoutMs)
        onAbort = () => reject(abortError())
        signal?.addEventListener('abort', onAbort, { once: true })
        operation.then((result) => {
          if (result?.ok === false) {
            reject(asAppError(result.error ?? result))
            return
          }
          if (result?.ok === true) {
            const { ok: _ok, id: _id, ...payload } = result
            resolve((Object.prototype.hasOwnProperty.call(payload, 'result') && Object.keys(payload).length === 1 ? payload.result : payload) as T)
            return
          }
          resolve(result as T)
        }, (error) => reject(asAppError(error)))
      })
      return await guarded
    } finally {
      if (timer) clearTimeout(timer)
      if (signal && onAbort) signal.removeEventListener('abort', onAbort)
    }
  }

  private nextPreviewRequestId(): string {
    this.previewSequence += 1
    return `preview-${Date.now().toString(36)}-${this.previewSequence.toString(36)}`
  }

  private previewKey(req: FrameRequest): string {
    return JSON.stringify([req.project_id, req.frame, req.size])
  }

  private cancelPreviewEntry(entry: PreviewEntry): void {
    if (entry.cancelSent || entry.settled) return
    entry.cancelSent = true
    const cancellation = this.bridge?.cancel?.(entry.requestId)
    if (cancellation) {
      void cancellation.catch(() => undefined)
      return
    }
    void this.call('preview.cancel', { preview_request_id: entry.requestId }, undefined, 5_000).catch(() => undefined)
  }

  private settlePreview(entry: PreviewEntry, error: unknown, result?: FrameResult): void {
    if (entry.settled) return
    entry.settled = true
    if (this.previewEntries.get(entry.key) === entry) this.previewEntries.delete(entry.key)
    for (const consumer of entry.consumers) {
      if (consumer.signal && consumer.abortHandler) consumer.signal.removeEventListener('abort', consumer.abortHandler)
      if (consumer.aborted) continue
      if (error) consumer.reject(error)
      else if (result) consumer.resolve(result)
    }
    entry.consumers.clear()
  }

  private pumpPreviews(): void {
    while (this.previewActive < this.previewMaxConcurrent && this.previewQueue.length > 0) {
      const entry = this.previewQueue.shift()
      if (!entry || entry.settled || entry.consumers.size === 0) {
        if (entry && this.previewEntries.get(entry.key) === entry) this.previewEntries.delete(entry.key)
        continue
      }
      entry.started = true
      this.previewActive += 1
      void this.call<any>('preview.getFrame', { ...entry.request, preview_request_id: entry.requestId }, undefined, 60_000)
        .then((response) => this.settlePreview(entry, null, (response.frame ?? response) as FrameResult))
        .catch((error: unknown) => {
          if (error instanceof AdapterError && error.error.code === 'BACKEND_TIMEOUT') this.cancelPreviewEntry(entry)
          this.settlePreview(entry, error)
        })
        .finally(() => {
          this.previewActive -= 1
          this.pumpPreviews()
        })
    }
  }

  private requestPreview(req: FrameRequest, signal?: AbortSignal): Promise<FrameResult> {
    if (signal?.aborted) return Promise.reject(abortError())
    const key = this.previewKey(req)
    let entry = this.previewEntries.get(key)
    if (!entry) {
      entry = {
        key,
        requestId: this.nextPreviewRequestId(),
        request: { ...req },
        consumers: new Set<PreviewConsumer>(),
        started: false,
        settled: false,
        cancelSent: false,
      }
      this.previewEntries.set(key, entry)
      this.previewQueue.push(entry)
    }
    const target = entry
    return new Promise<FrameResult>((resolve, reject) => {
      const consumer: PreviewConsumer = { resolve, reject, signal, aborted: false }
      const abort = () => {
        if (consumer.aborted || target.settled) return
        consumer.aborted = true
        target.consumers.delete(consumer)
        reject(abortError())
        if (target.consumers.size !== 0) return
        if (!target.started) {
          target.settled = true
          if (this.previewEntries.get(target.key) === target) this.previewEntries.delete(target.key)
          const index = this.previewQueue.indexOf(target)
          if (index >= 0) this.previewQueue.splice(index, 1)
          return
        }
        if (this.previewEntries.get(target.key) === target) this.previewEntries.delete(target.key)
        this.cancelPreviewEntry(target)
      }
      consumer.abortHandler = abort
      target.consumers.add(consumer)
      signal?.addEventListener('abort', abort, { once: true })
      this.pumpPreviews()
    })
  }

  async connect(): Promise<ConnectionInfo> {
    try {
      const connected = await this.call<any>('connect', {}, undefined, 8_000)
      return connected.connection ?? connected
    } catch (error) {
      const e = error as AdapterError
      if (!(e instanceof AdapterError) || !['IPC_METHOD_UNKNOWN', 'IPC_ERROR'].includes(e.error.code)) throw error
      const ping = await this.call<any>('ping', {}, undefined, 8_000)
      return { mode: 'desktop', app_version: '1.0.0-candidate', backend_version: String(ping.service || 'm3-python'), capabilities: { backend_version: String(ping.service || 'm3-python'), frame_accurate_preview: true, gpu: { available: false, verified_encoder: null, note: '未验证 GPU。' }, hdr_output: { supported: false, note: '当前链路未验证 HDR 输出。' }, declick_audio: false, max_parallel_jobs: 1, livephoto_hint: { short_below_ms: 1000, long_above_ms: 15000 } } }
    }
  }

  projects: V2LPAdapter['projects'] = {
    listRecent: () => this.call<any>('projects.listRecent').then((result) => result.projects ?? result.recent ?? []),
    open: (project_id, signal) => this.call<any>('projects.open', { project_id }, signal).then((result) => ({ project: projectFromResponse(result), warnings: result.warnings ?? [] } as OpenProjectResult)),
    pickProjectFile: () => this.bridge?.pickFile({ title: '打开项目文件', mode: 'open', filters: [{ name: 'SQLite 项目', extensions: ['sqlite3', 'db'] }] }).then((path) => path) ?? Promise.resolve(null),
    rename: (project_id, name) => this.call('projects.rename', { project_id, name }).then(() => undefined),
    removeRecent: (project_id) => this.call('projects.removeRecent', { project_id }).then(() => undefined),
    save: (project_id, edit_version, request_id) => this.call('projects.save', { project_id, edit_version, request_id }),
    relocateSource: (project_id, candidate) => this.call('projects.relocateSource', { project_id, candidate }),
  }

  media: V2LPAdapter['media'] = {
    pickVideo: () => this.bridge?.pickFile({ title: '选择视频文件', mode: 'open', filters: [{ name: '视频文件', extensions: ['mp4', 'mov', 'm4v'] } ] }).then((path) => path ? normalizeFile(path) : null) ?? Promise.resolve(null),
    fromBrowserFile: (file) => {
      const path = this.bridge?.pathForFile?.(file) ?? (file as File & { path?: string }).path
      if (!path) throw asAppError({ code: 'FILE_REF_UNAVAILABLE', message: '桌面拖放未返回受控文件引用。' }, 'FILE_REF_UNAVAILABLE')
      return normalizeFile(path)
    },
    probe: (file, signal) => this.call<any>('media.probe', { file }, signal).then((result) => result.probe ?? result) as Promise<ProbeResult>,
  }

  analysis: V2LPAdapter['analysis'] = {
    start: (params, onEvent): AnalysisHandle => {
      let analysisId = ''
      const off = this.bridge?.on?.('v2lp:analysis:event', (payload) => { const event = payload as AnalysisEvent; const matches = event.analysis_id === analysisId || (!analysisId && event.request_id === params.request_id); if (event.analysis_id && matches) onEvent(event) })
      const filePath = params.file.kind === 'desktop' ? params.file.display_path : ''
      const started = this.call<any>('analysis.start', { source_path: filePath, project_name: params.project_name, video_stream_index: params.video_stream_index, request_id: params.request_id })
      const done = started.then((result) => {
        analysisId = String(result.analysis_id || '')
        if (!analysisId) throw asAppError({ code: 'ANALYSIS_ID_MISSING', message: '后端未返回分析任务 ID。' }, 'ANALYSIS_ID_MISSING')
        return this.call<any>('analysis.result', { analysis_id: analysisId, request_id: params.request_id }, undefined, 3_600_000)
      }).then((result) => ({ project_id: String(result.project_id), warnings: result.warnings ?? [] })).finally(() => off?.())
      return { get analysis_id() { return analysisId }, done, cancel: () => analysisId ? this.call('analysis.cancel', { analysis_id: analysisId, request_id: params.request_id }).then(() => undefined) : started.then((result) => { analysisId = String(result.analysis_id || ''); return this.call('analysis.cancel', { analysis_id: analysisId, request_id: params.request_id }).then(() => undefined) }) }
    },
    reanalyze: (project_id, request_id) => this.call('analysis.reanalyze', { project_id, request_id }),
  }

  preview: V2LPAdapter['preview'] = {
    getSource: (project_id) => this.call<any>('preview.getSource', { project_id }).then((result) => result.source ?? result),
    getFrame: (req: FrameRequest, signal?: AbortSignal) => this.requestPreview(req, signal),
    releaseFrame: (url) => { void this.call('preview.releaseFrame', { url }).catch(() => undefined) },
  }

  timeline: V2LPAdapter['timeline'] = {
    apply: (project_id, base_edit_version, cmd: EditCommand, request_id) => this.call('timeline.apply', { project_id, base_edit_version, cmd, request_id }),
    undo: (project_id, base_edit_version, request_id) => this.call('timeline.undo', { project_id, base_edit_version, request_id }),
    redo: (project_id, base_edit_version, request_id) => this.call('timeline.redo', { project_id, base_edit_version, request_id }),
  }

  export: V2LPAdapter['export'] = {
    preflight: (project_id, edit_version, clip_ids, settings, signal) => this.call<any>('export.preflight', { project_id, edit_version, clip_ids, settings }, signal).then((result) => result.preflight ?? result) as Promise<PreflightResult>,
    createBatch: (req) => this.call('export.createBatch', { ...req }),
  }

  tasks: V2LPAdapter['tasks'] = {
    subscribe: (project_id, handler) => {
      const off = this.bridge?.on?.('v2lp:tasks:event', (payload) => { const event = payload as TaskEvent; if (event.project_id === project_id) handler(event) })
      void this.call('tasks.subscribe', { project_id }).catch((error) => { void error; })
      const timer = off ? undefined : setInterval(() => { void this.call<any>('tasks.listBatches', { project_id }).then((result) => (result.batches ?? []) as Array<import('@/domain/types').Batch>).then((batches) => batches.forEach((batch) => handler({ type: 'batch_snapshot', project_id, batch }))).catch(() => undefined) }, 500)
      return () => { off?.(); if (timer) clearInterval(timer); void this.call('tasks.unsubscribe', { project_id }).catch(() => undefined) }
    },
    getBatch: (batch_id) => this.call<any>('tasks.getBatch', { batch_id }).then((result) => result.batch ?? result),
    listBatches: (project_id) => this.call<any>('tasks.listBatches', { project_id }).then((result) => result.batches ?? []),
    pauseQueue: (batch_id, request_id) => this.call('tasks.pauseQueue', { batch_id, request_id }).then(() => undefined),
    resumeQueue: (batch_id, request_id) => this.call('tasks.resumeQueue', { batch_id, request_id }).then(() => undefined),
    cancelJob: (job_id, request_id) => this.call('tasks.cancelJob', { job_id, request_id }),
    stopBatch: (batch_id, request_id) => this.call('tasks.stopBatch', { batch_id, request_id }).then(() => undefined),
    retryFailed: (batch_id, request_id, job_ids) => this.call('tasks.retryFailed', { batch_id, request_id, job_ids }),
  }

  recovery: V2LPAdapter['recovery'] = {
    inspect: (project_id, onProgress, signal) => {
      const off = this.bridge?.on?.('v2lp:recovery:progress', (payload) => {
        const progress = payload as RecoveryProgress & { project_id?: string }
        if (progress.project_id === project_id) onProgress(progress)
      })
      return this.call<any>('recovery.inspect', { project_id }, signal).then((result) => result.summary ?? result).then((summary: RecoverySummary) => { onProgress({ checked: summary.verified_success.length + summary.needs_redo.length, total: summary.verified_success.length + summary.needs_redo.length + summary.commit_unknown.length, current: null }); return summary }).finally(() => off?.())
    },
    continueRemaining: (project_id, request_id) => this.call('recovery.continueRemaining', { project_id, request_id }),
    dismiss: (project_id) => this.call('recovery.dismiss', { project_id }).then(() => undefined),
  }

  files: V2LPAdapter['files'] = {
    openArtifact: (job_id, kind) => this.call('files.openArtifact', { job_id, kind }).then(() => undefined),
    revealOutput: (project_id, job_id) => this.call('files.revealOutput', { project_id, job_id }).then(() => undefined),
    readReport: (job_id) => this.call('files.readReport', { job_id }).then((result: any) => String(result.body ?? result.report ?? result)),
    pickOutputDir: () => this.bridge?.pickFile({ title: '选择导出目录', mode: 'directory' }) ?? Promise.resolve(null),
  }

  settings: V2LPAdapter['settings'] = {
    get: () => this.call<any>('settings.get').then((result) => result.settings ?? result) as Promise<AppSettings>,
    update: (patch) => this.call<any>('settings.update', patch).then((result) => result.settings ?? result) as Promise<AppSettings>,
    cacheInfo: () => this.call<any>('settings.cacheInfo').then((result) => result.cache ?? result),
    clearCache: (item_ids) => this.call('settings.clearCache', { item_ids }),
  }

  diagnostics: V2LPAdapter['diagnostics'] = {
    info: () => this.call<any>('diagnostics.info').then((result) => result.diagnostics ?? result),
    logs: (limit) => this.call('diagnostics.logs', { limit }).then((result: any) => result.logs ?? []),
    exportBundle: (opts) => this.call('diagnostics.exportBundle', opts),
  }

  app: V2LPAdapter['app'] = {
    onCloseRequested: (handler) => this.bridge?.on?.('v2lp:app:close-requested', handler) ?? (() => undefined),
    quit: () => this.bridge?.quit?.() ?? this.call('app.quit').then(() => undefined),
  }
}
