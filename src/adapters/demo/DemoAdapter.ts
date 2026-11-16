/**
 * DemoAdapter — 演示适配器。All backend capabilities are simulated here with fixtures and timers.
 * Nothing in this file touches real files. Every simulated outcome is labelled in the UI by mode.
 */
import type {
  AnalysisEvent,
  AnalysisHandle,
  AnalysisStageState,
  AppSettings,
  ConnectionInfo,
  CreateBatchRequest,
  EditResult,
  FileRef,
  PreflightIssue,
  PreflightResult,
  ProbeResult,
  RecoverySummary,
  V2LPAdapter,
} from '@/adapters/contract'
import type { EditCommand } from '@/domain/commands'
import { commandLabel } from '@/domain/commands'
import { AdapterError, makeError } from '@/domain/errors'
import { checkNameBase, fileStem } from '@/domain/naming'
import { applyCommand, TimelineError } from '@/domain/timelineCore'
import type { Batch, Capabilities, ClipId, MediaInfo, Project, ProjectId } from '@/domain/types'
import { ExportSimulator, newJob, nextId, type JobPlan } from './exportSim'
import { DEFAULT_FAULTS, loadFaults, saveFaults, type DemoFaults } from './faults'
import {
  buildWorld,
  coreContextFor,
  DEFAULT_OUTPUT,
  ERR,
  makeProject,
  recentOf,
  snapshotFor,
  weddingAttrs,
  type DemoProjectRecord,
} from './fixtures/projects'
import { LANDSCAPE, LANDSCAPE_CUTS, MULTI_STREAM, PORTRAIT, PORTRAIT_CUTS, HDR_LANDSCAPE, type DemoMediaDef } from './fixtures/media'
import { DemoFrameProvider, sleep, type FrameSourceDef } from './frames'
import { DEMO_SAMPLES, DEMO_SCENARIOS, type DemoScenarioId } from './meta'
export { DEMO_SAMPLES, DEMO_SCENARIOS, type DemoScenarioId }

const SCENARIO_KEY = 'v2lp.demo.scenario'

export interface DemoControl {
  scenario: DemoScenarioId
  faults: DemoFaults
  setFault<K extends keyof DemoFaults>(k: K, v: DemoFaults[K]): void
  reset(scenario?: DemoScenarioId): void
  jumpTargets(): { project_id: ProjectId; name: string; note: string }[]
  simulateCrash(project_id: ProjectId): boolean
  simulateCloseRequest(): void
  frameStats(): { thumb: number; full: number; capacity: { thumb: number; full: number } }
  samples: typeof DEMO_SAMPLES
  sampleRef(ref_id: string): FileRef
  relocationCandidates(project_id: ProjectId): { ref: FileRef; path: string; hint: string }[]
}

const clone = <T>(v: T): T => structuredClone(v)
const err = (code: string, message: string, extra: Parameters<typeof makeError>[2] = {}) => new AdapterError(makeError(code, message, extra))

export class DemoAdapter implements V2LPAdapter {
  readonly mode = 'demo' as const
  private records = new Map<ProjectId, DemoProjectRecord>()
  private order: ProjectId[] = []
  private fileRefs = new Map<string, { file?: File; sample?: string; url?: string; probe?: { w: number; h: number; dur: number } }>()
  private frames = new DemoFrameProvider()
  private sim: ExportSimulator
  private closeHandlers = new Set<() => void>()
  private requestResults = new Map<string, unknown>()
  private logLines: string[] = []
  private recentErrors: { at: string; code: string; message: string; scope: string }[] = []
  private settingsState: AppSettings = {
    default_output_dir: DEFAULT_OUTPUT,
    default_quality: 'source',
    default_color: 'sdr_rec709',
    cache_limit_gb: 20,
    proxy_resolution: '720p',
  }
  private faults: DemoFaults
  private scenario: DemoScenarioId
  private caps: Capabilities
  readonly demo: DemoControl

  constructor() {
    this.faults = loadFaults()
    const fromUrl = new URLSearchParams(location.search).get('scenario')
    let stored: string | null = null
    try {
      stored = sessionStorage.getItem(SCENARIO_KEY)
    } catch {
      /* ignore */
    }
    this.scenario = (DEMO_SCENARIOS.find((s) => s.id === (fromUrl ?? stored))?.id ?? 'full') as DemoScenarioId
    this.caps = {
      backend_version: 'demo-backend 0.1（模拟）',
      frame_accurate_preview: false,
      gpu: this.faults.limitedCaps
        ? { available: false, verified_encoder: null, note: '未检测到经过验证的 GPU 编码路径，所有片段使用 CPU 编码。' }
        : { available: true, verified_encoder: 'h264_nvenc（模拟验证）', note: null },
      hdr_output: this.faults.limitedCaps
        ? { supported: false, note: '当前后端未提供 HDR 输出能力，HDR 源统一转换为 Rec.709 SDR。' }
        : { supported: true, note: '仅 HLG → HLG HEVC 10-bit 在验证范围内（模拟）；PQ / Dolby Vision 不支持。' },
      declick_audio: false,
      max_parallel_jobs: 2,
      livephoto_hint: { short_below_ms: 1000, long_above_ms: 3000 },
    }
    this.sim = new ExportSimulator({
      maxSlots: () => this.caps.max_parallel_jobs,
      gpuAvailable: () => this.caps.gpu.available,
      onJobSucceeded: (pid, job, batch) => this.onJobSucceeded(pid, job.clip_id, batch),
      onInterrupted: (pid) => {
        const r = this.records.get(pid)
        if (r) {
          r.project.recovery_pending = true
          r.status = 'recovery_pending'
        }
      },
      log: (l) => this.log(l),
    })
    this.sim.speed = this.faults.speed
    this.sim.chaos = this.faults.eventChaos
    this.applyFrameFaults()
    this.loadWorld()
    this.demo = this.makeControl()
  }

  private loadWorld() {
    const seed = buildWorld(this.scenario)
    for (const r of seed.records) {
      this.records.set(r.project.project_id, r)
      this.order.push(r.project.project_id)
    }
    for (const b of seed.batches) {
      this.sim.add(b.batch, b.plans, (j) => {
        const c = b.batch.snapshot.clips.find((x) => x.clip_id === j.clip_id)!
        return c.end_frame - c.start_frame
      })
    }
    this.log(`[demo] 载入场景 ${this.scenario}，${seed.records.length} 个项目`)
  }

  private applyFrameFaults() {
    this.frames.latency = this.faults.frameLatency ? () => Math.random() * 900 : () => 0
    this.frames.failRate = this.faults.frameFail ? 0.3 : 0
  }

  private log(line: string) {
    this.logLines.push(`${new Date().toISOString()} ${line}`)
    if (this.logLines.length > 500) this.logLines.splice(0, this.logLines.length - 500)
  }

  private recordError(code: string, message: string, scope: string) {
    this.recentErrors.unshift({ at: new Date().toISOString(), code, message, scope })
    this.recentErrors.length = Math.min(this.recentErrors.length, 50)
    this.log(`[error] ${code} ${message} (${scope})`)
  }

  private rec(project_id: ProjectId): DemoProjectRecord {
    const r = this.records.get(project_id)
    if (!r) throw err('PROJECT_NOT_FOUND', '项目不存在或已被移除。')
    return r
  }

  private latency(min = 80, max = 220, signal?: AbortSignal) {
    return sleep(Math.round((min + Math.random() * (max - min)) / Math.max(0.25, this.faults.speed)), signal)
  }

  /** idempotency: same request id → same result, no second execution */
  private async once<T>(key: string, fn: () => Promise<T>): Promise<T> {
    if (this.requestResults.has(key)) return this.requestResults.get(key) as Promise<T>
    const p = fn()
    this.requestResults.set(key, p)
    p.catch(() => this.requestResults.delete(key))
    return p
  }

  async connect(): Promise<ConnectionInfo> {
    await this.latency(120, 260)
    return { mode: 'demo', app_version: '0.1.0-ui', backend_version: this.caps.backend_version, capabilities: clone(this.caps) }
  }

  /* --------------------------------- projects --------------------------------- */

  projects: V2LPAdapter['projects'] = {
    listRecent: async () => {
      await this.latency(60, 160)
      return this.order.map((id) => recentOf(this.records.get(id)!))
    },
    open: async (project_id, signal) => {
      await this.latency(450, 800, signal)
      const r = this.rec(project_id)
      if (r.openBehavior === 'read_failed') {
        this.recordError('PROJECT_READ_FAILED', '项目数据库读取失败', project_id)
        throw err('PROJECT_READ_FAILED', '项目数据读取失败：数据库文件无法打开。', {
          scope: { project_id },
          preserved: '源视频与已导出的文件不受影响。',
          actions: ['retry', 'open_diagnostics'],
          detail: 'SQLITE_CORRUPT: database disk image is malformed — 模拟',
          retryable: true,
        })
      }
      if (r.openBehavior === 'source_missing') {
        throw err('SOURCE_MISSING', `找不到原视频：${r.project.source.path_display}`, {
          scope: { project_id },
          preserved: '项目中的切点、片段设置和审核记录完整保留。',
          actions: ['relocate_source'],
          retryable: false,
        })
      }
      if (r.openBehavior === 'source_changed') {
        throw err('SOURCE_CHANGED', '原视频位置的文件与项目记录不一致（大小与内容指纹不同），可能已被替换或重新导出。', {
          scope: { project_id },
          preserved: '为保护人工修改，项目暂不打开处理。请定位正确的原视频。',
          actions: ['relocate_source'],
          detail: '记录：2.03 GB · sha256:9f2c…e41a；当前：1.98 GB · sha256:41b0…77c2（模拟）',
        })
      }
      r.updatedAt = new Date().toISOString()
      const warnings = []
      if (r.project.media.video_streams[0].color.transfer === 'unknown') {
        warnings.push(makeError('COLOR_UNKNOWN', '源视频色彩信息未知，将按 Rec.709 处理。'))
      }
      return { project: clone(r.project), warnings }
    },
    pickProjectFile: async () => {
      // Desktop shows a native dialog. Demo: no native dialog; the UI shows its own list.
      return null
    },
    rename: async (project_id, name) => {
      await this.latency()
      const issues = checkNameBase(name).filter((i) => i.level === 'error' && i.code !== 'ILLEGAL_CHAR')
      if (!name.trim() || issues.length) throw err('INVALID_NAME', '项目名称不能为空。')
      this.rec(project_id).project.name = name.trim()
    },
    removeRecent: async (project_id) => {
      await this.latency()
      this.order = this.order.filter((id) => id !== project_id)
    },
    save: async (project_id, edit_version, request_id) =>
      this.once(`save:${request_id}`, async () => {
        await this.latency(250, 450)
        if (this.faults.saveSlow) await sleep(Math.random() * 1800)
        if (this.faults.saveFailNext) {
          this.setFault('saveFailNext', false)
          this.recordError('SAVE_FAILED', '保存项目失败', project_id)
          throw err('SAVE_FAILED', '项目保存失败：数据库写入被拒绝（演示注入）。', {
            scope: { project_id },
            preserved: '当前编辑仍保留在工作区，可以重试保存。',
            actions: ['retry_save', 'open_diagnostics'],
            retryable: true,
          })
        }
        const r = this.rec(project_id)
        if (edit_version > r.project.edit_version) throw err('EDIT_VERSION_UNKNOWN', '保存的版本不存在。')
        r.project.saved_edit_version = Math.max(r.project.saved_edit_version, edit_version)
        r.updatedAt = new Date().toISOString()
        return { saved_edit_version: edit_version }
      }),
    relocateSource: async (project_id, candidate) => {
      await this.latency(500, 900)
      const r = this.rec(project_id)
      if (candidate.ref_id === 'cand:match') {
        r.openBehavior = 'ok'
        r.project.source = { ...r.project.source, path_display: 'E:\\素材备份\\' + r.project.source.file_name, status: 'ok', modified_at: new Date().toISOString() }
        r.status = 'ready_to_export'
        return { accepted: true, identity: clone(r.project.source), mismatch: [] }
      }
      const mismatch =
        candidate.kind === 'browser'
          ? ['演示模式无法核对浏览器文件的身份。桌面后端会比较文件大小、内容指纹与视频流特征。']
          : ['文件大小不同：1.98 GB ≠ 2.03 GB', '内容指纹不一致', '视频流时长不同：65.96 秒 ≠ 66.00 秒']
      return { accepted: false, identity: clone(r.project.source), mismatch }
    },
  }

  /* ----------------------------------- media ---------------------------------- */

  media: V2LPAdapter['media'] = {
    pickVideo: async () => null,
    fromBrowserFile: (file: File) => {
      const ref_id = nextId('file')
      this.fileRefs.set(ref_id, { file })
      return { kind: 'browser', ref_id, name: file.name, size_bytes: String(file.size), mime: file.type }
    },
    probe: async (file, signal) => {
      await this.latency(250, 500, signal)
      if (file.kind === 'demo-sample') return this.probeSample(file)
      if (file.kind !== 'browser') throw err('UNSUPPORTED_REF', '演示模式不能读取桌面路径。')
      return this.probeBrowser(file, signal)
    },
  }

  private sampleDef(ref: string): DemoMediaDef {
    switch (ref) {
      case 'sample:portrait':
        return PORTRAIT
      case 'sample:hdr':
        return HDR_LANDSCAPE
      case 'sample:multistream':
        return MULTI_STREAM
      default:
        return LANDSCAPE
    }
  }

  private probeSample(file: Extract<FileRef, { kind: 'demo-sample' }>): ProbeResult {
    const def = this.sampleDef(file.ref_id)
    const notes: ProbeResult['notes'] = []
    if (!def.media.audio_streams.length) notes.push({ code: 'NO_AUDIO', message: '源视频无音轨，导出的片段不包含音频。' })
    const s = def.media.video_streams[0]
    if (s.color.transfer === 'hlg' || s.color.transfer === 'pq') notes.push({ code: 'HDR_SOURCE', message: `检测到 HDR（${s.color.transfer.toUpperCase()}），默认转换为 Rec.709 SDR。` })
    if (def.media.video_streams.some((v) => v.color.transfer === 'unknown')) notes.push({ code: 'COLOR_UNKNOWN', message: '有视频流色彩信息未知，将按 Rec.709 处理。' })
    return { file, media: clone(def.media), notes, needs_stream_choice: def.media.video_streams.length > 1 }
  }

  private async probeBrowser(file: Extract<FileRef, { kind: 'browser' }>, signal?: AbortSignal): Promise<ProbeResult> {
    const entry = this.fileRefs.get(file.ref_id)
    if (!entry?.file) throw err('FILE_REF_EXPIRED', '文件引用已失效，请重新选择。')
    if (!/\.(mp4|mov)$/i.test(file.name)) {
      throw err('UNSUPPORTED_FORMAT', `不支持的文件格式：${file.name.split('.').pop()?.toUpperCase() ?? '未知'}。请选择 MP4 或 MOV 成片。`, { actions: [] })
    }
    const url = URL.createObjectURL(entry.file)
    entry.url = url
    const meta = await new Promise<{ w: number; h: number; dur: number }>((resolve, reject) => {
      const v = document.createElement('video')
      v.preload = 'metadata'
      v.muted = true
      const timer = setTimeout(() => done(() => reject(err('MEDIA_READ_TIMEOUT', '浏览器读取媒体信息超时。'))), 8000)
      const done = (fn: () => void) => {
        clearTimeout(timer)
        v.removeAttribute('src')
        v.load()
        fn()
      }
      v.onloadedmetadata = () => {
        const w = v.videoWidth
        const h = v.videoHeight
        const dur = v.duration
        done(() => resolve({ w, h, dur }))
      }
      v.onerror = () =>
        done(() =>
          reject(
            err('MEDIA_READ_DENIED', '浏览器拒绝读取或无法解码此媒体（例如 HEVC / ProRes）。桌面版由 FFmpeg 读取，可能仍可处理。', {
              actions: [],
              detail: `MediaError code ${v.error?.code ?? '?'}`,
            }),
          ),
        )
      signal?.addEventListener('abort', () => done(() => reject(new DOMException('aborted', 'AbortError'))), { once: true })
      v.src = url
    })
    if (!meta.w || !meta.h) {
      URL.revokeObjectURL(url)
      throw err('NO_VIDEO_TRACK', '文件中没有有效的视频轨，无法分段。')
    }
    entry.probe = meta
    const frames = Math.max(1, Math.round(meta.dur * 30))
    const media: MediaInfo = {
      container: file.name.toLowerCase().endsWith('.mov') ? 'mov' : 'mp4',
      size_bytes: file.size_bytes,
      duration_us: Math.round(meta.dur * 1e6),
      video_streams: [
        {
          stream_index: 0,
          codec: '未知（浏览器）',
          width: meta.w,
          height: meta.h,
          display_aspect: { num: meta.w, den: meta.h },
          rotation_deg: 0,
          frame_rate: { num: 30, den: 1 },
          vfr: false,
          frame_count: frames,
          time_base: { num: 1, den: 30 },
          duration_us: Math.round(meta.dur * 1e6),
          color: { transfer: 'unknown', primaries: 'unknown', dolby_vision: false, log_profile: null, bit_depth: null },
          is_default: true,
          title: null,
        },
      ],
      audio_streams: [{ stream_index: 1, codec: '未核实', channels: 2, sample_rate: 48000, is_mixed_main: null }],
      selected_video_stream: 0,
    }
    return {
      file,
      media,
      notes: [
        { code: 'DEMO_BROWSER_PROBE', message: '演示：浏览器无法读取帧率、色彩与音轨，按 30fps / 未知色彩 / 有音轨假定。真实信息由后端探测。' },
        { code: 'COLOR_UNKNOWN', message: '色彩信息未知，将按 Rec.709 处理。' },
      ],
      needs_stream_choice: false,
    }
  }

  /* --------------------------------- analysis --------------------------------- */

  analysis: V2LPAdapter['analysis'] = {
    start: (params, onEvent) => this.startAnalysis(params, onEvent),
    reanalyze: async (project_id) => {
      await this.latency(600, 900)
      const r = this.rec(project_id)
      r.project.analysis_version++
      return { analysis_version: r.project.analysis_version, preserved: '已保存的人工切点修改、片段设置与审核记录保持不变；新结果作为第 ' + r.project.analysis_version + ' 版分析供对比。' }
    },
  }

  private startAnalysis(
    params: Parameters<V2LPAdapter['analysis']['start']>[0],
    onEvent: (e: AnalysisEvent) => void,
  ): AnalysisHandle {
    const key = `analysis:${params.request_id}`
    const existing = this.requestResults.get(key) as AnalysisHandle | undefined
    if (existing) return existing
    const analysis_id = nextId('ana')
    const ctrl = new AbortController()
    const speed = Math.max(0.25, this.faults.speed)
    const def = params.file.kind === 'demo-sample' ? this.sampleDef(params.file.ref_id) : null
    const frameTotal = def ? def.media.video_streams[0].frame_count : Math.round((this.fileRefs.get(params.file.ref_id)?.probe?.dur ?? 30) * 30)
    const cutsTotal =
      params.file.ref_id === 'sample:single' ? 0 : def ? (def === PORTRAIT ? PORTRAIT_CUTS.length : LANDSCAPE_CUTS.length) : Math.max(0, Math.floor(frameTotal / 120) - 1)
    const stages: AnalysisStageState[] = [
      { id: 'probe', status: 'running', progress: null, note: '读取容器与视频流信息' },
      { id: 'frame_index', status: 'pending', progress: null, note: null },
      { id: 'proxy', status: 'pending', progress: null, note: null },
      { id: 'shot_detect', status: 'pending', progress: null, note: null },
    ]
    let seq = 0
    let shots: number | null = null
    let slow: string | null = null
    const emit = () => onEvent({ analysis_id, seq: ++seq, stages: clone(stages), shots_found: shots, slow_hint: slow })
    const tick = (ms: number) => sleep(ms / speed, ctrl.signal)
    const st = (id: string) => stages.find((s) => s.id === id)!

    const run = async () => {
      emit()
      await tick(500)
      Object.assign(st('probe'), { status: 'done', note: '已读取媒体信息' })
      Object.assign(st('frame_index'), { status: 'running', progress: { done: 0, total: frameTotal, unit: 'frames' }, note: '建立帧与 PTS 对照' })
      Object.assign(st('proxy'), { status: 'running', progress: { done: 0, total: 100, unit: 'bytes' }, note: '生成预览代理' })
      emit()
      const proxySteps = this.faults.proxySlow ? 60 : 24
      let proxyDone = 0
      // frame index and proxy run in parallel
      const proxy = (async () => {
        for (let i = 1; i <= proxySteps; i++) {
          await tick(120)
          proxyDone = Math.round((i / proxySteps) * 100)
          st('proxy').progress = { done: proxyDone, total: 100, unit: 'bytes' }
          if (this.faults.proxySlow && i === 8) slow = '预览代理准备较慢：源为 4K HEVC 10-bit。镜头分析不受影响，可以先等待分析完成。'
          emit()
        }
        if (this.faults.previewPartial) Object.assign(st('proxy'), { status: 'partial', note: '7 张缩略图生成失败，可在编辑页重试；不影响分析与导出。' })
        else Object.assign(st('proxy'), { status: 'done', note: '预览代理已就绪' })
        emit()
      })()
      for (let i = 1; i <= 12; i++) {
        await tick(150)
        st('frame_index').progress = { done: Math.round((i / 12) * frameTotal), total: frameTotal, unit: 'frames' }
        emit()
      }
      Object.assign(st('frame_index'), { status: 'done', note: def?.media.video_streams[0].vfr ? '可变帧率：已建立 PTS 映射' : '恒定帧率' })
      Object.assign(st('shot_detect'), { status: 'running', progress: { done: 0, total: frameTotal, unit: 'frames' }, note: '检测硬切、叠化与闪光' })
      shots = 1
      emit()
      for (let i = 1; i <= 16; i++) {
        await tick(160)
        if (this.faults.analysisFail && i === 10) {
          Object.assign(st('shot_detect'), { status: 'failed', note: '镜头分析工作进程退出（演示注入）' })
          emit()
          this.recordError('ANALYSIS_WORKER_EXITED', '镜头分析进程退出', params.file.name)
          throw err('ANALYSIS_WORKER_EXITED', '镜头分析工作进程意外退出。', {
            preserved: '媒体信息与帧索引已完成，重试时会复用。源视频未被修改。',
            actions: ['retry', 'open_diagnostics'],
            retryable: true,
          })
        }
        st('shot_detect').progress = { done: Math.round((i / 16) * frameTotal), total: frameTotal, unit: 'frames' }
        shots = 1 + Math.round((i / 16) * cutsTotal)
        emit()
      }
      Object.assign(st('shot_detect'), { status: 'done', note: cutsTotal === 0 ? '未检测到镜头切换，将作为 1 个完整片段' : `发现 ${cutsTotal + 1} 个镜头` })
      emit()
      await proxy
      const project_id = this.createProjectFromImport(params)
      const warnings = []
      if (cutsTotal === 0) warnings.push({ code: 'NO_CUTS', message: '未检测到镜头切换，整条视频作为 1 个片段进入编辑，可手动添加切点。' })
      if (this.faults.previewPartial) warnings.push({ code: 'PREVIEW_PARTIAL', message: '部分缩略图生成失败，相关位置显示占位图。' })
      return { project_id, warnings }
    }
    const done = run()
    const handle: AnalysisHandle = {
      analysis_id,
      done,
      cancel: async () => {
        ctrl.abort()
        await sleep(150)
      },
    }
    this.requestResults.set(key, handle)
    done.catch(() => this.requestResults.delete(key))
    return handle
  }

  private createProjectFromImport(params: Parameters<V2LPAdapter['analysis']['start']>[0]): ProjectId {
    const id = nextId('p')
    let def: DemoMediaDef
    let project: Project
    const sourcePath = params.file.kind === 'browser' ? `（浏览器文件）${params.file.name}` : `D:\\示例素材\\${params.file.name}`
    if (params.file.kind === 'browser') {
      const f = this.fileRefs.get(params.file.ref_id)!
      const probe = f.probe!
      const frames = Math.max(1, Math.round(probe.dur * 30))
      def = {
        key: `browser-${params.file.ref_id}`,
        previewUrl: f.url ?? null,
        previewWidth: probe.w,
        previewHeight: probe.h,
        media: {
          ...LANDSCAPE.media,
          size_bytes: params.file.size_bytes,
          duration_us: Math.round(probe.dur * 1e6),
          video_streams: [{ ...LANDSCAPE.media.video_streams[0], codec: '未知（浏览器）', width: probe.w, height: probe.h, display_aspect: { num: probe.w, den: probe.h }, frame_rate: { num: 30, den: 1 }, frame_count: frames, time_base: { num: 1, den: 30 }, duration_us: Math.round(probe.dur * 1e6), color: { transfer: 'unknown', primaries: 'unknown', dolby_vision: false, log_profile: null, bit_depth: null } }],
        },
      }
      const ctx = coreContextFor(def)
      const cutFrames: number[] = []
      for (let f2 = 120; f2 < frames - 15; f2 += 90 + ((f2 * 7) % 60)) cutFrames.push(f2)
      const cuts = cutFrames.map((frame) => ({
        cut_id: ctx.newCutId(),
        frame,
        pts: ctx.ptsOf(frame),
        kind: 'hard' as const,
        transition: null,
        review: 'pending' as const,
        confirmed_by: null,
        skipped: false,
        origin: 'analysis' as const,
        reason: '演示：浏览器文件的切点为等距模拟结果，不代表真实镜头切换。',
        confidence: null,
      }))
      project = makeProject({ id, name: params.project_name, def, cuts, ctx, sourcePath })
      this.records.set(id, { project, mediaDef: def, past: [], future: [], openBehavior: 'ok', status: 'needs_review', updatedAt: new Date().toISOString(), thumbFrame: Math.min(frames - 1, 30), preflight: { externallyModified: 0, locked: 0 }, objectUrl: f.url ?? null, scenarioNote: '浏览器文件（模拟分析）' })
    } else {
      const ref = params.file.ref_id
      def = this.sampleDef(ref)
      if (ref === 'sample:multistream') {
        def = { ...def, media: { ...clone(def.media), selected_video_stream: params.video_stream_index } }
        const chosen = def.media.video_streams.find((s) => s.stream_index === params.video_stream_index) ?? def.media.video_streams[0]
        def.media.video_streams = [chosen]
        def.media.selected_video_stream = 0
      }
      const ctx = coreContextFor(def)
      const seeds = ref === 'sample:single' ? [] : def === PORTRAIT ? PORTRAIT_CUTS : LANDSCAPE_CUTS
      const cuts = seeds.map((s) => {
        const pending = s.review === 'pending'
        return { cut_id: ctx.newCutId(), pts: ctx.ptsOf(s.frame), transition: null, origin: 'analysis' as const, reason: null, confidence: null, skipped: false, ...s, review: pending ? ('pending' as const) : ('confirmed' as const), confirmed_by: pending ? null : ('analysis' as const) }
      })
      project = makeProject({ id, name: params.project_name, def, cuts, ctx, sourcePath, attrs: def === LANDSCAPE ? weddingAttrs : undefined })
      this.records.set(id, { project, mediaDef: def, past: [], future: [], openBehavior: 'ok', status: cuts.some((c) => c.review === 'pending') ? 'needs_review' : 'ready_to_export', updatedAt: new Date().toISOString(), thumbFrame: project.timeline.clips[0].cover.frame, preflight: { externallyModified: 0, locked: 0 }, objectUrl: null, scenarioNote: '新导入（模拟分析）' })
    }
    this.order.unshift(id)
    this.log(`[demo] 新建项目 ${id} ${params.project_name}`)
    return id
  }

  /* ---------------------------------- preview --------------------------------- */

  private frameSource(r: DemoProjectRecord): FrameSourceDef {
    const def = r.mediaDef
    const s = r.project.media.video_streams[0]
    const clips = r.project.timeline.clips
    return {
      key: def.key,
      url: def.previewUrl,
      rate: s.frame_rate,
      width: def.previewWidth,
      height: def.previewHeight,
      label: '演示替代帧',
      hueOf: (frame) => {
        let lo = 0
        let hi = clips.length - 1
        while (lo < hi) {
          const mid = (lo + hi + 1) >> 1
          if (clips[mid].start_frame <= frame) lo = mid
          else hi = mid - 1
        }
        return (lo * 47) % 360
      },
    }
  }

  preview: V2LPAdapter['preview'] = {
    getSource: async (project_id) => {
      await this.latency(60, 140)
      const r = this.rec(project_id)
      const def = r.mediaDef
      const has_audio = r.project.media.audio_streams.length > 0
      if (this.faults.previewBroken) {
        return { url: def.previewUrl ? def.previewUrl + '#broken-demo' + '?x=' : null, kind: 'proxy', width: def.previewWidth, height: def.previewHeight, has_audio, note: '演示注入：预览代理失效' }
      }
      return {
        url: def.previewUrl,
        kind: def.previewUrl ? 'proxy' : 'none',
        width: def.previewWidth,
        height: def.previewHeight,
        has_audio,
        note: def.previewUrl ? `演示预览代理 ${def.previewWidth}×${def.previewHeight}（合成示例素材）` : '演示：此项目没有可播放的预览代理，画面使用替代帧。',
      }
    },
    getFrame: async (req, signal) => {
      const r = this.rec(req.project_id)
      const src = this.frameSource(r)
      if (this.faults.previewBroken && src.url) src.url = src.url + '#broken'
      const url = await this.frames.get(src, req.frame, req.size, signal)
      return { url, frame: req.frame, exact: false, note: src.url ? '演示：浏览器定位，非精确帧' : '演示替代帧' }
    },
    releaseFrame: (url) => this.frames.release(url),
  }

  /* --------------------------------- timeline --------------------------------- */

  private editResult(r: DemoProjectRecord, partial: Partial<EditResult>): EditResult {
    const p = r.project
    p.history = {
      can_undo: r.past.length > 0,
      can_redo: r.future.length > 0,
      undo_label: r.past[r.past.length - 1]?.label ?? null,
      redo_label: r.future[r.future.length - 1]?.label ?? null,
    }
    return {
      edit_version: p.edit_version,
      timeline: clone(p.timeline),
      history: { ...p.history },
      affected_clip_ids: [],
      removed_clip_ids: [],
      notes: [],
      outdated_clip_ids: [...p.outdated_clip_ids],
      ...partial,
    }
  }

  private checkBase(r: DemoProjectRecord, base: number) {
    if (base !== r.project.edit_version) {
      throw err('EDIT_VERSION_CONFLICT', `编辑版本已变化（当前 v${r.project.edit_version}，请求基于 v${base}），已刷新到最新状态。`, { retryable: true })
    }
  }

  private markOutdated(r: DemoProjectRecord, cmd: EditCommand, ids: ClipId[]) {
    const contentChange =
      cmd.type !== 'review_cut' && !(cmd.type === 'set_clip_props' && cmd.patch.audio === undefined)
    if (!contentChange) return
    const exported = new Set<ClipId>()
    for (const b of this.sim.batchesOf(r.project.project_id)) for (const j of b.jobs) if (j.stage === 'succeeded' || j.stage === 'encoding' || j.stage === 'verifying' || j.stage === 'committing') exported.add(j.clip_id)
    const set = new Set(r.project.outdated_clip_ids)
    for (const id of ids) if (exported.has(id)) set.add(id)
    r.project.outdated_clip_ids = [...set]
  }

  timeline: V2LPAdapter['timeline'] = {
    apply: (project_id, base, cmd, request_id) =>
      this.once(`edit:${request_id}`, async () => {
        await this.latency(90, 200)
        const r = this.rec(project_id)
        this.checkBase(r, base)
        if (cmd.type === 'move_cut' && this.faults.rejectNextMove) {
          this.setFault('rejectNextMove', false)
          throw err('CUT_REJECTED', '时间线核心拒绝了该位置：目标帧不是合法的解码边界（演示注入）。已恢复到上次确认的切点位置。', { retryable: false })
        }
        try {
          const res = applyCommand(r.project.timeline, cmd, coreContextFor(r.mediaDef))
          r.past.push({ timeline: r.project.timeline, label: commandLabel(cmd) })
          if (r.past.length > 200) r.past.shift()
          r.future = []
          r.project.timeline = res.timeline
          r.project.edit_version++
          this.markOutdated(r, cmd, [...res.affected_clip_ids, ...res.removed_clip_ids])
          r.status = res.timeline.cuts.some((c) => c.review === 'pending') ? 'needs_review' : 'ready_to_export'
          return this.editResult(r, { affected_clip_ids: res.affected_clip_ids, removed_clip_ids: res.removed_clip_ids, notes: res.notes })
        } catch (e) {
          if (e instanceof TimelineError) throw err(e.code, e.message)
          throw e
        }
      }),
    undo: (project_id, base, request_id) =>
      this.once(`undo:${request_id}`, async () => {
        await this.latency(60, 140)
        const r = this.rec(project_id)
        this.checkBase(r, base)
        const prev = r.past.pop()
        if (!prev) throw err('NOTHING_TO_UNDO', '没有可撤销的操作。')
        r.future.push({ timeline: r.project.timeline, label: prev.label })
        r.project.timeline = prev.timeline
        r.project.edit_version++
        return this.editResult(r, { notes: [`已撤销：${prev.label}`] })
      }),
    redo: (project_id, base, request_id) =>
      this.once(`redo:${request_id}`, async () => {
        await this.latency(60, 140)
        const r = this.rec(project_id)
        this.checkBase(r, base)
        const next = r.future.pop()
        if (!next) throw err('NOTHING_TO_REDO', '没有可重做的操作。')
        r.past.push({ timeline: r.project.timeline, label: next.label })
        r.project.timeline = next.timeline
        r.project.edit_version++
        return this.editResult(r, { notes: [`已重做：${next.label}`] })
      }),
  }

  /* ---------------------------------- export ---------------------------------- */

  export: V2LPAdapter['export'] = {
    preflight: async (project_id, edit_version, clip_ids, settings, signal) => {
      await this.latency(300, 600, signal)
      const r = this.rec(project_id)
      const issues: PreflightIssue[] = []
      const dir = settings.output_dir.replace(/[\\/]+$/, '')
      const src = r.project.source.path_display
      const srcDir = src.slice(0, src.lastIndexOf('\\'))
      if (dir.toLowerCase() === src.toLowerCase()) {
        issues.push({ level: 'error', code: 'OUTPUT_IS_SOURCE', message: '保存位置指向源视频文件本身。源视频只读，必须选择其他文件夹。', action: 'choose_output_dir' })
      }
      const stems = clip_ids.map((id) => fileStem(settings.name_base, r.project.timeline.clips.find((c) => c.clip_id === id)?.display_index ?? 0))
      if (dir.toLowerCase() === `${srcDir}\\视频片段`.toLowerCase() && stems.some((s) => `${s}.mp4`.toLowerCase() === r.project.source.file_name.toLowerCase())) {
        issues.push({ level: 'error', code: 'OUTPUT_OVERWRITES_SOURCE', message: '有输出文件会与源视频同名同路径，导出被阻止。', action: 'choose_output_dir' })
      }
      if (/^[e-z]:/i.test(dir) && !/^[d]:/i.test(dir)) {
        issues.push({ level: 'error', code: 'TARGET_UNAVAILABLE', message: `目标盘 ${dir.slice(0, 2).toUpperCase()} 未连接或不可写（演示：仅 C:/D: 可用）。`, action: 'choose_output_dir' })
      }
      if (this.faults.preflightDiskFull) {
        issues.push({ level: 'error', code: 'DISK_SPACE', message: '目标盘剩余 1.2 GB，本次预计需要 3.4 GB。', action: 'choose_output_dir' })
      }
      const active = this.sim.batchesOf(project_id).filter((b) => ['running', 'pause_requested', 'paused'].includes(b.state))
      const dup = active.filter((b) => b.snapshot.edit_version === edit_version && b.snapshot.settings.output_dir === settings.output_dir && b.jobs.some((j) => clip_ids.includes(j.clip_id) && j.stage !== 'succeeded'))
      if (dup.length) {
        issues.push({ level: 'error', code: 'DUPLICATE_RUNNING', message: '相同版本、相同目标的片段正在导出中。请等待当前批次完成，或先停止它。', action: null })
      }
      const prior = this.sim.batchesOf(project_id).some((b) => b.jobs.some((j) => j.stage === 'succeeded' && clip_ids.includes(j.clip_id)))
      const existing = { count: prior ? clip_ids.length : 0, externally_modified: prior ? r.preflight.externallyModified : 0, locked: prior ? r.preflight.locked : 0 }
      if (existing.count) {
        issues.push({ level: 'info', code: 'REPLACE_EXISTING', message: `目标位置已有 ${existing.count} 个片段的上次结果。新版会先生成并校验，再安全替换；替换完成前旧版保持不变。`, action: 'acknowledge' })
      }
      if (existing.externally_modified) {
        issues.push({ level: 'warning', code: 'OUTPUT_MODIFIED', message: `${existing.externally_modified} 个旧输出文件在上次导出后被外部修改（陈氏婚礼MV_005.jpg）。继续将以新版替换，旧版会先移入备份目录。`, action: 'acknowledge' })
      }
      const totalFrames = clip_ids.reduce((a, id) => {
        const c = r.project.timeline.clips.find((x) => x.clip_id === id)
        return a + (c ? c.end_frame - c.start_frame : 0)
      }, 0)
      return {
        ok: !issues.some((i) => i.level === 'error'),
        issues,
        free_space_bytes: this.faults.preflightDiskFull ? '1288490188' : '412316860416',
        estimated_bytes: String(totalFrames * 52_000 + clip_ids.length * 900_000),
        existing_outputs: existing,
        sample_names: { mp4: `${stems[0] ?? 'x'}.mp4`, livp: `${stems[0] ?? 'x'}.livp` },
      } satisfies PreflightResult
    },
    createBatch: (req: CreateBatchRequest) =>
      this.once(`batch:${req.request_id}`, async () => {
        await this.latency(300, 600)
        const r = this.rec(req.project_id)
        if (req.edit_version !== r.project.edit_version) throw err('EDIT_VERSION_CONFLICT', '导出请求基于旧的编辑版本，请重新确认。')
        const clips = r.project.timeline.clips.filter((c) => req.clip_ids.includes(c.clip_id))
        if (!clips.length) throw err('EMPTY_SELECTION', '没有选中导出的片段。')
        r.project.export_settings = clone(req.settings)
        const snap = snapshotFor(r.project, clips)
        const batch_id = nextId('batch')
        const prior = new Set(this.sim.batchesOf(req.project_id).flatMap((b) => b.jobs.filter((j) => j.stage === 'succeeded').map((j) => j.clip_id)))
        const jobs = snap.clips.map((c) => newJob(batch_id, c, prior.has(c.clip_id)))
        const plans = new Map<string, JobPlan>()
        const f = this.faults
        const longest = jobs.find((j) => {
          const c = snap.clips.find((x) => x.clip_id === j.clip_id)!
          return c.end_frame - c.start_frame > 50
        })
        if (f.gpuFallback && longest) plans.set(longest.job_id, { gpuFailAt: 0.4 })
        if (f.diskFull && jobs[2]) plans.set(jobs[2].job_id, { ...plans.get(jobs[2].job_id), fail: { stage: 'encoding', at: 0.6, error: ERR.diskFull(jobs[2].file_stem) } })
        if (f.fileLocked && jobs[3]) plans.set(jobs[3].job_id, { ...plans.get(jobs[3].job_id), fail: { stage: 'committing', at: 0, error: ERR.fileLocked(jobs[3].file_stem) } })
        if (f.commitInterrupt && jobs[4]) plans.set(jobs[4].job_id, { commitInterrupt: true })
        const batch: Batch = { batch_id, project_id: req.project_id, snapshot: snap, state: 'running', created_at: new Date().toISOString(), seq: 0, jobs, active_slots: 1 }
        this.sim.add(batch, plans, (j) => {
          const c = snap.clips.find((x) => x.clip_id === j.clip_id)!
          return c.end_frame - c.start_frame
        })
        r.status = 'exporting'
        this.log(`[demo] 创建批次 ${batch_id}，${jobs.length} 个片段，快照 v${snap.edit_version}`)
        // notify subscribers with a snapshot of the new batch
        this.pushSnapshot(req.project_id, batch_id)
        return { batch_id, snapshot_id: snap.snapshot_id, deduplicated: false }
      }),
  }

  private subscribers = new Map<ProjectId, Set<(e: import('@/adapters/contract').TaskEvent) => void>>()

  private pushSnapshot(project_id: ProjectId, batch_id: string) {
    const b = this.sim.get(batch_id)
    if (!b) return
    this.subscribers.get(project_id)?.forEach((fn) => fn({ type: 'batch_snapshot', project_id, batch: clone(b) }))
  }

  private onJobSucceeded(project_id: ProjectId, clip_id: ClipId, batch: Batch) {
    const r = this.records.get(project_id)
    if (!r) return
    // a newer success clears "待更新" only when it was produced from the current edit version
    if (batch.snapshot.edit_version === r.project.edit_version) r.project.outdated_clip_ids = r.project.outdated_clip_ids.filter((id) => id !== clip_id)
    const all = this.sim.batchesOf(project_id)
    if (all.every((b) => !['running', 'pause_requested', 'stop_requested'].includes(b.state) || b === batch)) {
      const failed = batch.jobs.some((j) => j.stage === 'failed')
      r.status = failed ? 'partial_failed' : 'exported'
    }
  }

  /* ----------------------------------- tasks ---------------------------------- */

  tasks: V2LPAdapter['tasks'] = {
    subscribe: (project_id, handler) => {
      let set = this.subscribers.get(project_id)
      if (!set) this.subscribers.set(project_id, (set = new Set()))
      set.add(handler)
      const off = this.sim.subscribe(project_id, handler)
      return () => {
        set!.delete(handler)
        off()
      }
    },
    getBatch: async (batch_id) => {
      await this.latency(40, 120)
      const b = this.sim.get(batch_id)
      if (!b) throw err('BATCH_NOT_FOUND', '批次不存在。')
      return clone(b)
    },
    listBatches: async (project_id) => {
      await this.latency(40, 120)
      return clone(this.sim.batchesOf(project_id))
    },
    pauseQueue: (batch_id, request_id) => this.once(`pause:${request_id}`, async () => (await this.latency(), this.sim.pause(batch_id))),
    resumeQueue: (batch_id, request_id) => this.once(`resume:${request_id}`, async () => (await this.latency(), this.sim.resume(batch_id))),
    cancelJob: (job_id, request_id) => this.once(`cancel:${request_id}`, async () => (await this.latency(), this.sim.cancel(job_id))),
    stopBatch: (batch_id, request_id) => this.once(`stop:${request_id}`, async () => (await this.latency(), this.sim.stop(batch_id))),
    retryFailed: (batch_id, request_id, job_ids) =>
      this.once(`retry:${request_id}`, async () => {
        await this.latency()
        return { retried: this.sim.retryFailed(batch_id, job_ids) }
      }),
  }

  /* --------------------------------- recovery --------------------------------- */

  recovery: V2LPAdapter['recovery'] = {
    inspect: async (project_id, onProgress, signal) => {
      const r = this.rec(project_id)
      const batch = this.sim.batchesOf(project_id).find((b) => b.state === 'interrupted') ?? null
      const jobs = batch?.jobs ?? []
      const total = Math.max(1, jobs.length)
      for (let i = 0; i < total; i++) {
        await sleep(110 / Math.max(0.25, this.faults.speed), signal)
        if (this.faults.recoveryInspectFail && i === Math.floor(total / 2)) {
          this.recordError('RECOVERY_DB_READ_FAILED', '恢复记录读取失败', project_id)
          throw err('RECOVERY_DB_READ_FAILED', '读取恢复记录失败：任务数据库被锁定（演示注入）。', {
            scope: { project_id, stage: 'recovery_inspect' },
            preserved: '没有修改任何文件；已成功的导出结果保持不变。',
            actions: ['retry', 'open_diagnostics'],
            retryable: true,
          })
        }
        onProgress({ checked: i + 1, total, current: jobs[i] ? `${jobs[i].file_stem}（MP4 / LIVP）` : null })
      }
      const summary: RecoverySummary = {
        project_id,
        batch_id: batch?.batch_id ?? null,
        interrupted_at: batch?.created_at ?? new Date().toISOString(),
        verified_success: jobs.filter((j) => j.stage === 'succeeded').map((j) => ({ clip_id: j.clip_id, display_index: j.display_index })),
        needs_redo: jobs
          .filter((j) => j.stage === 'interrupted' || j.stage === 'commit_unknown')
          .map((j) => ({
            clip_id: j.clip_id,
            display_index: j.display_index,
            reason: j.stage === 'commit_unknown' ? '提交中断：MOV 未完成替换，已恢复旧版' : j.attempts.length ? '编码中断，临时文件已清理' : '尚未开始',
          })),
        reusable_intermediate: jobs
          .filter((j) => j.stage === 'interrupted' && j.artifacts.some((a) => a.status === 'verified'))
          .map((j) => ({ clip_id: j.clip_id, display_index: j.display_index, what: '封面 JPG 已生成并通过校验' })),
        needs_relocate: r.project.source.status === 'ok' ? [] : [{ label: '源视频', path_display: r.project.source.path_display }],
        commit_unknown: jobs.filter((j) => j.stage === 'commit_unknown').map((j) => ({ clip_id: j.clip_id, display_index: j.display_index, detail: 'MP4 已提交；LIVP 写入未完成。旧版文件仍在备份中，已恢复。' })),
        pending_actions: batch ? ['确认后从第一个未完成片段继续编码', '已核实成功的片段不会重新生成'] : ['没有找到中断的批次，可直接关闭恢复提示'],
      }
      return summary
    },
    continueRemaining: (project_id, request_id) =>
      this.once(`continue:${request_id}`, async () => {
        await this.latency(200, 400)
        const r = this.rec(project_id)
        const batch = this.sim.batchesOf(project_id).find((b) => ['interrupted', 'stopped'].includes(b.state))
        if (!batch) throw err('NOTHING_TO_CONTINUE', '没有可继续的任务。')
        this.sim.resolveCommitUnknown(batch.batch_id, false)
        this.sim.continueRemaining(batch.batch_id)
        r.project.recovery_pending = false
        r.status = 'exporting'
        return { batch_id: batch.batch_id }
      }),
    dismiss: async (project_id) => {
      await this.latency()
      this.rec(project_id)
    },
  }

  /* ----------------------------------- files ---------------------------------- */

  files: V2LPAdapter['files'] = {
    openArtifact: async (job_id, kind) => {
      await this.latency()
      this.log(`[demo] 打开文件请求 ${job_id} ${kind}（演示：未打开真实文件）`)
    },
    revealOutput: async (project_id, job_id) => {
      await this.latency()
      this.log(`[demo] 定位目录 ${project_id} ${job_id ?? ''}（演示）`)
    },
    readReport: async (job_id) => {
      await this.latency()
      const f = this.sim.findJob(job_id)
      if (!f) throw err('REPORT_NOT_FOUND', '找不到该任务的校验报告。')
      const j = f.sj.job
      return JSON.stringify(
        {
          note: '演示模式：以下为模拟的本地校验报告',
          job_id: j.job_id,
          clip_id: j.clip_id,
          snapshot_edit_version: f.sb.batch.snapshot.edit_version,
          pair_id: f.sb.batch.snapshot.clips.find((c) => c.clip_id === j.clip_id)?.pair_id,
          checks: {
            mp4_decodes: j.verification.local === 'passed',
            frame_range_matches_snapshot: j.verification.local === 'passed',
            jpg_mov_content_identifier_match: j.verification.local === 'passed',
            mov_still_image_time_present: j.verification.local === 'passed',
          },
          device_playback: { iphone: '待验证', wechat_moments: '待验证', xiaohongshu: '待验证', douyin: '待验证' },
          attempts: j.attempts.map((a) => ({ n: a.n, encoder: a.encoder, result: a.result, error: a.error?.code ?? null })),
        },
        null,
        2,
      )
    },
    pickOutputDir: async () => {
      await this.latency()
      return 'D:\\导出\\Video2LivePhoto\\' + new Date().toISOString().slice(0, 10)
    },
  }

  /* --------------------------------- settings --------------------------------- */

  settings: V2LPAdapter['settings'] = {
    get: async () => (await this.latency(), clone(this.settingsState)),
    update: async (patch) => {
      await this.latency()
      this.settingsState = { ...this.settingsState, ...patch }
      return clone(this.settingsState)
    },
    cacheInfo: async () => {
      await this.latency()
      const fs = this.frames.stats()
      return {
        items: [
          { id: 'proxy', label: '预览代理文件', size_bytes: '1288490188', clearable: true, protected_reason: null },
          { id: 'thumbs', label: '缩略图缓存', size_bytes: '192937984', clearable: true, protected_reason: null },
          { id: 'frames', label: `帧预览内存缓存（${fs.thumb + fs.full} 张）`, size_bytes: String((fs.thumb * 9 + fs.full * 60) * 1024), clearable: true, protected_reason: null },
          { id: 'job_temp', label: '运行中任务的临时文件', size_bytes: '734003200', clearable: false, protected_reason: '正在被导出任务使用，任务结束后可清理。' },
          { id: 'source', label: '源视频', size_bytes: '0', clearable: false, protected_reason: '源视频只读，从不属于缓存。' },
          { id: 'outputs', label: '导出结果', size_bytes: '0', clearable: false, protected_reason: '导出结果属于用户文件，不在清理范围。' },
        ],
      }
    },
    clearCache: async (ids) => {
      await this.latency(400, 700)
      if (ids.includes('frames')) this.frames.dispose()
      return { freed_bytes: ids.includes('proxy') ? '1481428172' : '192937984' }
    },
  }

  /* -------------------------------- diagnostics ------------------------------- */

  diagnostics: V2LPAdapter['diagnostics'] = {
    info: async () => {
      await this.latency()
      return {
        app_version: '0.1.0-ui',
        backend_version: this.caps.backend_version,
        ui_build: `${import.meta.env.MODE} · ${__BUILD_TIME__}`,
        mode: 'demo',
        capabilities: clone(this.caps),
        recent_errors: clone(this.recentErrors),
        workers: [
          { name: '分析进程（模拟）', status: '空闲' },
          { name: '编码进程（模拟）', status: this.sim.anyActive() ? '运行中' : '按需启动' },
          { name: '项目存储（模拟 SQLite）', status: '内存' },
        ],
      }
    },
    logs: async (limit) => (await this.latency(), this.logLines.slice(-limit)),
    exportBundle: async (opts) => {
      await this.latency(500, 900)
      this.log(`[demo] 诊断包导出请求 include_paths=${opts.include_paths}（演示：未写入文件）`)
      return { saved_to: '演示模式：未写入任何文件' }
    },
  }

  /* ------------------------------------ app ----------------------------------- */

  app: V2LPAdapter['app'] = {
    onCloseRequested: (handler) => {
      this.closeHandlers.add(handler)
      return () => this.closeHandlers.delete(handler)
    },
    quit: async () => {
      this.log('[demo] 退出请求（演示：浏览器不会关闭桌面进程）')
    },
  }

  /* ----------------------------------- demo ----------------------------------- */

  private setFault<K extends keyof DemoFaults>(k: K, v: DemoFaults[K]) {
    this.faults[k] = v
    saveFaults(this.faults)
    this.sim.speed = this.faults.speed
    this.sim.chaos = this.faults.eventChaos
    this.applyFrameFaults()
  }

  private makeControl(): DemoControl {
    const self = this
    return {
      get scenario() {
        return self.scenario
      },
      get faults() {
        return { ...self.faults }
      },
      setFault: (k, v) => self.setFault(k, v),
      reset: (scenario) => {
        try {
          sessionStorage.setItem(SCENARIO_KEY, scenario ?? self.scenario)
          if (!scenario) sessionStorage.setItem('v2lp.demo.faults', JSON.stringify(DEFAULT_FAULTS))
        } catch {
          /* ignore */
        }
        self.dispose()
        const url = new URL(location.href)
        url.searchParams.delete('scenario')
        location.replace(url.toString())
      },
      jumpTargets: () => self.order.map((id) => ({ project_id: id, name: self.records.get(id)!.project.name, note: self.records.get(id)!.scenarioNote })),
      simulateCrash: (project_id) => {
        const batches = self.sim.batchesOf(project_id)
        let any = false
        for (const b of batches) any = self.sim.crash(b.batch_id) || any
        if (any) {
          const r = self.records.get(project_id)!
          r.project.recovery_pending = true
          r.status = 'recovery_pending'
        }
        return any
      },
      simulateCloseRequest: () => self.closeHandlers.forEach((h) => h()),
      frameStats: () => self.frames.stats(),
      samples: DEMO_SAMPLES,
      sampleRef: (ref_id) => {
        const s = DEMO_SAMPLES.find((x) => x.ref_id === ref_id)!
        return { kind: 'demo-sample', ref_id, name: s.name, size_bytes: self.sampleDef(ref_id).media.size_bytes }
      },
      relocationCandidates: (project_id) => {
        const r = self.rec(project_id)
        const name = r.project.source.file_name
        return [
          { ref: { kind: 'demo-sample', ref_id: 'cand:match', name, size_bytes: r.project.source.size_bytes }, path: `E:\\素材备份\\${name}`, hint: '同名 · 大小一致' },
          { ref: { kind: 'demo-sample', ref_id: 'cand:mismatch', name, size_bytes: '2126008811' }, path: `D:\\下载\\${name}`, hint: '同名 · 大小不同' },
        ]
      },
    }
  }

  dispose() {
    this.sim.dispose()
    this.frames.dispose()
    for (const r of this.records.values()) if (r.objectUrl) URL.revokeObjectURL(r.objectUrl)
    for (const f of this.fileRefs.values()) if (f.url) URL.revokeObjectURL(f.url)
  }
}
