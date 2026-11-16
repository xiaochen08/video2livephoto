/**
 * Adapter boundary between the UI and the desktop backend (Electron + Python/FFmpeg + SQLite).
 *
 * The renderer-facing contract is implemented by DesktopAdapter on top of the
 * existing Electron → Python/FFmpeg/SQLite M3 bridge. Backend-specific errors
 * and PTS strings stay visible at this boundary.
 *
 * Rules for every method:
 *  - Async, rejects with AdapterError(AppError). Error codes are passed through verbatim.
 *  - Long operations accept an AbortSignal; abort means "UI no longer interested" and, where the
 *    backend supports it, a cancel request. Backend confirms cancellation through events/results.
 *  - Mutating calls take an idempotency key (`request_id`) so repeated clicks never duplicate work.
 *  - Edit calls carry `base_edit_version`; the backend rejects stale bases with EDIT_VERSION_CONFLICT.
 */
import type { EditCommand } from '@/domain/commands'
import type {
  AppError,
  Batch,
  BatchId,
  Capabilities,
  ClipId,
  ExportSettings,
  HistoryState,
  ImportColorSelection,
  JobId,
  MediaInfo,
  Project,
  ProjectId,
  RecentProject,
  RequestId,
  SourceIdentity,
  Timeline,
} from '@/domain/types'

export type AdapterMode = 'demo' | 'desktop'

export interface ConnectionInfo {
  mode: AdapterMode
  app_version: string
  backend_version: string
  capabilities: Capabilities
}

/** Reference to a user-chosen file. Browser and desktop references are kept apart. */
export type FileRef =
  | { kind: 'desktop'; ref_id: string; display_path: string; name: string; size_bytes: string }
  | { kind: 'browser'; ref_id: string; name: string; size_bytes: string; mime: string }
  | { kind: 'demo-sample'; ref_id: string; name: string; size_bytes: string }

export interface ProbeResult {
  file: FileRef
  media: MediaInfo
  /** non-fatal notes such as unknown colour, no audio */
  notes: { code: string; message: string }[]
  /** true when more than one video stream exists and the user must choose */
  needs_stream_choice: boolean
}

export type AnalysisStageId = 'probe' | 'frame_index' | 'proxy' | 'shot_detect'

export interface AnalysisStageState {
  id: AnalysisStageId
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped' | 'partial'
  /** null = total unknown → indeterminate UI */
  progress: { done: number; total: number; unit: 'frames' | 'thumbnails' | 'bytes' } | null
  note: string | null
}

export interface AnalysisEvent {
  analysis_id: string
  request_id?: string
  seq: number
  stages: AnalysisStageState[]
  shots_found: number | null
  slow_hint: string | null
}

export interface AnalysisHandle {
  analysis_id: string
  /** resolves with the created project id */
  done: Promise<{ project_id: ProjectId; warnings: { code: string; message: string }[] }>
  cancel(): Promise<void>
}

export interface OpenProjectResult {
  project: Project
  /** non-blocking problems to show in the editor */
  warnings: AppError[]
}

export interface EditResult {
  edit_version: number
  timeline: Timeline
  history: HistoryState
  affected_clip_ids: ClipId[]
  removed_clip_ids: ClipId[]
  notes: string[]
  outdated_clip_ids: ClipId[]
}

export interface FrameRequest {
  project_id: ProjectId
  frame: number
  size: 'thumb' | 'full'
}

export interface FrameResult {
  /** object URL / custom-protocol URL owned by the adapter's frame cache */
  url: string
  frame: number
  /** true when the backend decoded exactly this frame */
  exact: boolean
  note: string | null
}

export interface PreviewSource {
  /** URL playable by <video>; desktop: proxy via custom protocol. null when unavailable */
  url: string | null
  kind: 'proxy' | 'source' | 'none'
  width: number
  height: number
  has_audio: boolean
  note: string | null
}

export interface PreflightIssue {
  level: 'error' | 'warning' | 'info'
  code: string
  message: string
  action: 'choose_output_dir' | 'review' | 'retry' | 'close_other_program' | 'acknowledge' | null
}

export interface PreflightResult {
  ok: boolean
  issues: PreflightIssue[]
  free_space_bytes: string | null
  estimated_bytes: string | null
  existing_outputs: { count: number; externally_modified: number; locked: number }
  sample_names: { mp4: string; livp: string }
}

export interface CreateBatchRequest {
  project_id: ProjectId
  edit_version: number
  clip_ids: ClipId[]
  settings: ExportSettings
  acknowledged: { unreviewed_cuts: boolean; livephoto_hints: boolean; replace_existing: boolean }
  request_id: RequestId
}

export type TaskEvent =
  | { type: 'batch_snapshot'; project_id: ProjectId; batch: Batch }
  | { type: 'batch_patch'; project_id: ProjectId; batch_id: BatchId; seq: number; patch: Partial<Pick<Batch, 'state' | 'active_slots'>> }
  | {
      type: 'job_patch'
      project_id: ProjectId
      batch_id: BatchId
      seq: number
      job_id: JobId
      attempt_id: string | null
      patch: Partial<Batch['jobs'][number]>
    }

export interface RecoveryProgress {
  checked: number
  total: number
  current: string | null
}

export interface RecoverySummary {
  project_id: ProjectId
  batch_id: BatchId | null
  interrupted_at: string
  verified_success: { clip_id: ClipId; display_index: number }[]
  needs_redo: { clip_id: ClipId; display_index: number; reason: string }[]
  reusable_intermediate: { clip_id: ClipId; display_index: number; what: string }[]
  needs_relocate: { label: string; path_display: string }[]
  commit_unknown: { clip_id: ClipId; display_index: number; detail: string }[]
  pending_actions: string[]
}

export interface DiagnosticsInfo {
  app_version: string
  backend_version: string
  ui_build: string
  mode: AdapterMode
  capabilities: Capabilities
  recent_errors: { at: string; code: string; message: string; scope: string }[]
  workers: { name: string; status: string }[]
}

export interface AppSettings {
  default_output_dir: string
  default_quality: ExportSettings['quality']
  default_color: ExportSettings['color']
  cache_limit_gb: number
  proxy_resolution: '540p' | '720p' | '1080p'
}

export interface CacheInfo {
  items: { id: string; label: string; size_bytes: string; clearable: boolean; protected_reason: string | null }[]
}

export interface V2LPAdapter {
  readonly mode: AdapterMode
  connect(): Promise<ConnectionInfo>

  projects: {
    listRecent(): Promise<RecentProject[]>
    open(project_id: ProjectId, signal?: AbortSignal): Promise<OpenProjectResult>
    /** Desktop: native open-project dialog. Returns null when the user cancels. */
    pickProjectFile(): Promise<ProjectId | null>
    rename(project_id: ProjectId, name: string): Promise<void>
    /** Only removes the recent-list entry. Project data and source video are untouched. */
    removeRecent(project_id: ProjectId): Promise<void>
    save(project_id: ProjectId, edit_version: number, request_id: RequestId): Promise<{ saved_edit_version: number }>
    /** Backend identity check (size + fingerprint + stream signature). Name match is only a hint. */
    relocateSource(project_id: ProjectId, candidate: FileRef): Promise<{ accepted: boolean; identity: SourceIdentity; mismatch: string[] }>
  }

  media: {
    /** Desktop: native file dialog. Browser demo uses <input type=file> instead. */
    pickVideo(): Promise<FileRef | null>
    fromBrowserFile(file: File): FileRef
    probe(file: FileRef, signal?: AbortSignal): Promise<ProbeResult>
  }

  analysis: {
    start(
      params: { file: FileRef; video_stream_index: number; project_name: string; request_id: RequestId; color_override?: ImportColorSelection | null },
      onEvent: (e: AnalysisEvent) => void,
    ): AnalysisHandle
    reanalyze(project_id: ProjectId, request_id: RequestId): Promise<{ analysis_version: number; preserved: string }>
  }

  preview: {
    getSource(project_id: ProjectId): Promise<PreviewSource>
    getFrame(req: FrameRequest, signal?: AbortSignal): Promise<FrameResult>
    /** release a URL obtained from getFrame (ref-counted inside the adapter) */
    releaseFrame(url: string): void
  }

  timeline: {
    apply(project_id: ProjectId, base_edit_version: number, cmd: EditCommand, request_id: RequestId): Promise<EditResult>
    undo(project_id: ProjectId, base_edit_version: number, request_id: RequestId): Promise<EditResult>
    redo(project_id: ProjectId, base_edit_version: number, request_id: RequestId): Promise<EditResult>
  }

  export: {
    preflight(project_id: ProjectId, edit_version: number, clip_ids: ClipId[], settings: ExportSettings, signal?: AbortSignal): Promise<PreflightResult>
    createBatch(req: CreateBatchRequest): Promise<{ batch_id: BatchId; snapshot_id: string; deduplicated: boolean }>
  }

  tasks: {
    /** Snapshot first, then incremental events. Handler receives a batch_snapshot after (re)connect. */
    subscribe(project_id: ProjectId, handler: (e: TaskEvent) => void): () => void
    getBatch(batch_id: BatchId): Promise<Batch>
    listBatches(project_id: ProjectId): Promise<Batch[]>
    pauseQueue(batch_id: BatchId, request_id: RequestId): Promise<void>
    resumeQueue(batch_id: BatchId, request_id: RequestId): Promise<void>
    cancelJob(job_id: JobId, request_id: RequestId): Promise<{ immediate: boolean; wait_reason: string | null }>
    stopBatch(batch_id: BatchId, request_id: RequestId): Promise<void>
    retryFailed(batch_id: BatchId, request_id: RequestId, job_ids?: JobId[]): Promise<{ retried: number }>
  }

  recovery: {
    inspect(project_id: ProjectId, onProgress: (p: RecoveryProgress) => void, signal?: AbortSignal): Promise<RecoverySummary>
    /** Starts remaining work only after explicit user confirmation */
    continueRemaining(project_id: ProjectId, request_id: RequestId): Promise<{ batch_id: BatchId }>
    dismiss(project_id: ProjectId): Promise<void>
  }

  files: {
    openArtifact(job_id: JobId, kind: 'mp4' | 'livp' | 'jpg' | 'mov'): Promise<void>
    revealOutput(project_id: ProjectId, job_id?: JobId): Promise<void>
    readReport(job_id: JobId): Promise<string>
    pickOutputDir(): Promise<string | null>
  }

  settings: {
    get(): Promise<AppSettings>
    update(patch: Partial<AppSettings>): Promise<AppSettings>
    cacheInfo(): Promise<CacheInfo>
    clearCache(item_ids: string[]): Promise<{ freed_bytes: string }>
  }

  diagnostics: {
    info(): Promise<DiagnosticsInfo>
    logs(limit: number): Promise<string[]>
    exportBundle(opts: { include_paths: boolean }): Promise<{ saved_to: string }>
  }

  app: {
    /** Desktop: window close requested by the OS. Browser demo triggers it from the dev panel. */
    onCloseRequested(handler: () => void): () => void
    /** Desktop: actually quit after the UI resolved unsaved work. */
    quit(): Promise<void>
  }
}
