/**
 * Framework-independent data model for the Video2LivePhoto UI.
 *
 * STATUS: 前端接入提案（待映射契约）。字段名与现有后端的实际映射由 Codex 核对后完成，
 * 见 docs/BACKEND_CONTRACT.md。Units are explicit in field names:
 *   *_frame   – integer frame index in the selected video stream (0-based)
 *   *_pts     – decimal string of an integer PTS in the stream time_base (bigint-safe)
 *   *_us      – integer microseconds
 *   *_ms      – integer milliseconds
 *   *_bytes   – decimal string (may exceed 2^53)
 * Ranges are half-open: [start_frame, end_frame).
 */

export type ProjectId = string
export type ClipId = string
export type CutId = string
export type BatchId = string
export type JobId = string
export type AttemptId = string
export type SnapshotId = string
export type RequestId = string

/** Rational number, e.g. 30000/1001. Never stored as a float. */
export interface Rational {
  num: number
  den: number
}

/** Integer PTS encoded as a decimal string so 64-bit values survive JSON/IPC. */
export type PtsString = string

export type ColorTransfer = 'bt709' | 'pq' | 'hlg' | 'log' | 'unknown'

export interface ColorInfo {
  transfer: ColorTransfer
  primaries: 'bt709' | 'bt2020' | 'unknown'
  dolby_vision: boolean
  /** e.g. 'S-Log3', 'C-Log', null when not a log profile or unknown */
  log_profile: string | null
  bit_depth: number | null
}

export interface VideoStreamInfo {
  stream_index: number
  codec: string
  width: number
  height: number
  /** display aspect ratio after SAR is applied */
  display_aspect: Rational
  rotation_deg: 0 | 90 | 180 | 270
  /** nominal / average frame rate */
  frame_rate: Rational
  vfr: boolean
  frame_count: number
  time_base: Rational
  duration_us: number
  color: ColorInfo
  is_default: boolean
  title: string | null
}

export interface AudioStreamInfo {
  stream_index: number
  codec: string
  channels: number
  sample_rate: number
  /** 待后端补充: 是否为混合主音轨 */
  is_mixed_main: boolean | null
}

export interface MediaInfo {
  container: 'mp4' | 'mov' | string
  size_bytes: string
  duration_us: number
  video_streams: VideoStreamInfo[]
  audio_streams: AudioStreamInfo[]
  selected_video_stream: number | null
}

export type SourceStatus = 'ok' | 'missing' | 'changed' | 'unverified'

export interface SourceIdentity {
  /** Display-only path. Never used to build file operations in the UI. */
  path_display: string
  file_name: string
  size_bytes: string
  modified_at: string
  /** 待映射: backend content fingerprint (partial hash) */
  fingerprint: string | null
  status: SourceStatus
}

export type ReviewStatus = 'pending' | 'confirmed'
export type CutKind = 'hard' | 'dissolve' | 'flash_candidate' | 'fast_motion_candidate' | 'manual'

export interface FrameRange {
  start_frame: number
  end_frame: number
}

export interface Cut {
  cut_id: CutId
  /** first frame of the clip to the right of this cut */
  frame: number
  pts: PtsString | null
  kind: CutKind
  /** Transition range for dissolves, [start, end). Content is kept untouched. */
  transition: FrameRange | null
  review: ReviewStatus
  /** who confirmed: analysis (clean hard cut, no review suggested) or the user */
  confirmed_by: 'analysis' | 'user' | null
  /** user skipped while reviewing; still counts as pending */
  skipped: boolean
  origin: 'analysis' | 'user'
  /** human-readable candidate reason supplied by analysis */
  reason: string | null
  /** null when the analysis does not provide a score – never fabricated */
  confidence: number | null
}

export type AudioMode = 'source' | 'muted'

export interface CoverInfo {
  frame: number
  origin: 'auto' | 'user'
  status: 'valid' | 'out_of_range' | 'regenerating'
}

export type NameOrigin = 'default' | 'user' | 'example'

export interface Clip {
  clip_id: ClipId
  start_frame: number
  end_frame: number
  start_pts: PtsString | null
  end_pts: PtsString | null
  /** 1-based, presentation only. Never used as a key. */
  display_index: number
  name: string | null
  name_origin: NameOrigin
  export_selected: boolean
  audio: AudioMode
  cover: CoverInfo
}

export interface Timeline {
  frame_count: number
  cuts: Cut[]
  clips: Clip[]
}

export interface HistoryState {
  can_undo: boolean
  can_redo: boolean
  undo_label: string | null
  redo_label: string | null
}

export type ExportQuality = 'source' | 'high' | 'compact'
export type ExportColor = 'sdr_rec709' | 'hdr_keep'

export interface ExportSettings {
  output_dir: string
  quality: ExportQuality
  color: ExportColor
  /** naming base, default = project name */
  name_base: string
}

export type ProjectStatusTag =
  | 'analyzing'
  | 'needs_review'
  | 'ready_to_export'
  | 'exporting'
  | 'partial_failed'
  | 'exported'
  | 'recovery_pending'
  | 'source_missing'
  | 'source_changed'
  | 'read_failed'

export interface Project {
  project_id: ProjectId
  schema_version: number
  name: string
  source: SourceIdentity
  media: MediaInfo
  analysis_version: number
  edit_version: number
  /** edit version confirmed persisted by backend */
  saved_edit_version: number
  timeline: Timeline
  history: HistoryState
  export_settings: ExportSettings
  recovery_pending: boolean
  /** clip ids edited after their last successful export snapshot */
  outdated_clip_ids: ClipId[]
}

export interface RecentProject {
  project_id: ProjectId
  name: string
  updated_at: string
  status: ProjectStatusTag
  clip_count: number | null
  pending_review: number | null
  source_name: string
  thumb_key: string | null
  orientation: 'landscape' | 'portrait'
}

export interface Capabilities {
  backend_version: string
  frame_accurate_preview: boolean
  gpu: { available: boolean; verified_encoder: string | null; note: string | null }
  hdr_output: { supported: boolean; note: string | null }
  declick_audio: boolean
  max_parallel_jobs: number
  /** compatibility hint thresholds; the backend owns real values */
  livephoto_hint: { short_below_ms: number; long_above_ms: number }
}

/* ---------------------------------- export ---------------------------------- */

export interface SnapshotClip {
  clip_id: ClipId
  display_index: number
  start_frame: number
  end_frame: number
  audio: AudioMode
  cover_frame: number
  file_stem: string
  /** pairs JPG + MOV as a Live Photo (content identifier) */
  pair_id: string
}

export interface ExportSnapshot {
  snapshot_id: SnapshotId
  project_id: ProjectId
  edit_version: number
  created_at: string
  settings: ExportSettings
  clips: SnapshotClip[]
}

export type JobStage =
  | 'queued'
  | 'encoding'
  | 'verifying'
  | 'committing'
  | 'succeeded'
  | 'failed'
  | 'skipped'
  | 'cancelled'
  | 'interrupted'
  | 'commit_unknown'

export type ProgressBasis =
  | { kind: 'frames'; done: number; total: number }
  | { kind: 'artifacts'; done: number; total: number }
  | { kind: 'unknown'; note: string }

export interface Attempt {
  attempt_id: AttemptId
  n: number
  encoder: 'gpu' | 'cpu'
  started_at: string
  ended_at: string | null
  result: 'running' | 'failed' | 'succeeded' | 'cancelled' | 'interrupted'
  error: AppError | null
}

export type ArtifactKind = 'mp4' | 'jpg' | 'mov'

export interface Artifact {
  kind: ArtifactKind
  file_name: string
  rel_dir: string
  status: 'pending' | 'writing' | 'verified' | 'committed' | 'failed' | 'missing'
  size_bytes: string | null
}

export type DeviceCheck = 'unverified' | 'passed' | 'failed'

export interface Verification {
  local: 'pending' | 'passed' | 'failed'
  local_report_id: string | null
  /** real-device playback results are recorded separately, default 待验证 */
  devices: { iphone: DeviceCheck; wechat_moments: DeviceCheck; xiaohongshu: DeviceCheck; douyin: DeviceCheck }
}

export interface Job {
  job_id: JobId
  batch_id: BatchId
  clip_id: ClipId
  display_index: number
  file_stem: string
  stage: JobStage
  progress: ProgressBasis | null
  attempts: Attempt[]
  current_attempt_id: AttemptId | null
  artifacts: Artifact[]
  error: AppError | null
  cancellable: boolean
  /** reason when cancel must wait for a safe point */
  cancel_wait_reason: string | null
  cancel_requested: boolean
  verification: Verification
  /** previous successful version protected until the new one commits */
  replaces_previous: boolean
  previous_protected: boolean
}

export type BatchState =
  | 'running'
  | 'pause_requested'
  | 'paused'
  | 'stop_requested'
  | 'stopped'
  | 'completed'
  | 'interrupted'

export interface Batch {
  batch_id: BatchId
  project_id: ProjectId
  snapshot: ExportSnapshot
  state: BatchState
  created_at: string
  /** last applied event sequence number */
  seq: number
  jobs: Job[]
  active_slots: number
}

/* ---------------------------------- errors ---------------------------------- */

export type ErrorActionKind =
  | 'retry'
  | 'relocate_source'
  | 'choose_output_dir'
  | 'open_output_dir'
  | 'copy_error'
  | 'open_diagnostics'
  | 'reanalyze'
  | 'retry_save'
  | 'retry_job'
  | 'check_files'
  | 'close_other_program'

export interface AppError {
  /** backend error code, kept verbatim */
  code: string
  message: string
  scope: { project_id?: ProjectId; clip_id?: ClipId; job_id?: JobId; stage?: string }
  /** what has been preserved, in user language */
  preserved: string | null
  actions: ErrorActionKind[]
  detail: string | null
  retryable: boolean
}
