/**
 * DesktopAdapter — 桌面适配器骨架（未连接）。
 * Forwards every contract call to the Electron preload bridge. It never falls back to demo data:
 * when the bridge is missing or the backend does not answer, connect() rejects and the app shows
 * the connection-error screen with a diagnostics entry.
 */
import type { AnalysisEvent, ConnectionInfo, RecoveryProgress, TaskEvent, V2LPAdapter } from '@/adapters/contract'
import { AdapterError, makeError } from '@/domain/errors'
import type { AppError } from '@/domain/types'
import { CHANNELS, type ChannelKey, type V2LPBridge } from './channels'

function isAppError(v: unknown): v is AppError {
  return !!v && typeof v === 'object' && 'code' in v && 'message' in v
}

export class DesktopAdapter implements V2LPAdapter {
  readonly mode = 'desktop' as const
  private bridge: V2LPBridge | null = typeof window !== 'undefined' ? (window.v2lpBridge ?? null) : null

  private async call<T>(key: ChannelKey, payload?: unknown, signal?: AbortSignal): Promise<T> {
    if (!this.bridge) {
      throw new AdapterError(makeError('BRIDGE_UNAVAILABLE', '未检测到桌面桥接（window.v2lpBridge）。', { actions: ['open_diagnostics', 'retry'] }))
    }
    if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
    try {
      const result = await this.bridge.invoke(CHANNELS[key], payload)
      if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
      return result as T
    } catch (e) {
      if (e instanceof DOMException) throw e
      // 待映射: existing backend error envelope → AppError (codes passed through verbatim)
      if (isAppError(e)) throw new AdapterError(makeError(e.code, e.message, e))
      throw new AdapterError(makeError('IPC_ERROR', e instanceof Error ? e.message : String(e), { detail: CHANNELS[key] }))
    }
  }

  connect: V2LPAdapter['connect'] = async () => {
    if (!this.bridge) {
      throw new AdapterError(
        makeError('BRIDGE_UNAVAILABLE', '无法连接桌面后端：当前窗口没有可用的桌面桥接。', {
          detail: '生产模式不会使用演示数据。请确认应用由 Electron 启动且 preload 已注入 window.v2lpBridge。',
          actions: ['retry', 'open_diagnostics'],
          retryable: true,
        }),
      )
    }
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new AdapterError(makeError('BACKEND_TIMEOUT', '桌面后端在 8 秒内没有响应。', { retryable: true, actions: ['retry', 'open_diagnostics'] }))), 8000),
    )
    return Promise.race([this.call<ConnectionInfo>('connect'), timeout])
  }

  projects: V2LPAdapter['projects'] = {
    listRecent: () => this.call('projects.listRecent'),
    open: (project_id, signal) => this.call('projects.open', { project_id }, signal),
    pickProjectFile: () => this.call('projects.pickProjectFile'),
    rename: (project_id, name) => this.call('projects.rename', { project_id, name }),
    removeRecent: (project_id) => this.call('projects.removeRecent', { project_id }),
    save: (project_id, edit_version, request_id) => this.call('projects.save', { project_id, edit_version, request_id }),
    relocateSource: (project_id, candidate) => this.call('projects.relocateSource', { project_id, candidate }),
  }

  media: V2LPAdapter['media'] = {
    pickVideo: () => this.call('media.pickVideo'),
    fromBrowserFile: () => {
      // Desktop flow uses native dialogs / drag-drop paths resolved in the preload.
      throw new AdapterError(makeError('UNSUPPORTED_IN_DESKTOP', '桌面模式通过系统对话框选择文件。'))
    },
    probe: (file, signal) => this.call('media.probe', { file }, signal),
  }

  analysis: V2LPAdapter['analysis'] = {
    start: (params, onEvent) => {
      let analysisId = ''
      const off = this.bridge?.on(CHANNELS['analysis.event'], (p) => {
        const e = p as AnalysisEvent
        if (!analysisId || e.analysis_id === analysisId) onEvent(e)
      })
      const started = this.call<{ analysis_id: string }>('analysis.start', params)
      const done = started
        .then((r) => {
          analysisId = r.analysis_id
          // 待映射: completion signal; proposal: backend resolves a second invoke
          return this.call<{ project_id: string; warnings: { code: string; message: string }[] }>('analysis.start', { ...params, await_result: true })
        })
        .finally(() => off?.())
      return {
        get analysis_id() {
          return analysisId
        },
        done,
        cancel: async () => {
          if (analysisId) await this.call('analysis.cancel', { analysis_id: analysisId })
        },
      }
    },
    reanalyze: (project_id, request_id) => this.call('analysis.reanalyze', { project_id, request_id }),
  }

  preview: V2LPAdapter['preview'] = {
    getSource: (project_id) => this.call('preview.getSource', { project_id }),
    getFrame: (req, signal) => this.call('preview.getFrame', req, signal),
    releaseFrame: (url) => void this.call('preview.releaseFrame', { url }).catch(() => undefined),
  }

  timeline: V2LPAdapter['timeline'] = {
    apply: (project_id, base_edit_version, cmd, request_id) => this.call('timeline.apply', { project_id, base_edit_version, cmd, request_id }),
    undo: (project_id, base_edit_version, request_id) => this.call('timeline.undo', { project_id, base_edit_version, request_id }),
    redo: (project_id, base_edit_version, request_id) => this.call('timeline.redo', { project_id, base_edit_version, request_id }),
  }

  export: V2LPAdapter['export'] = {
    preflight: (project_id, edit_version, clip_ids, settings, signal) => this.call('export.preflight', { project_id, edit_version, clip_ids, settings }, signal),
    createBatch: (req) => this.call('export.createBatch', req),
  }

  tasks: V2LPAdapter['tasks'] = {
    subscribe: (project_id, handler) => {
      const off = this.bridge?.on(CHANNELS['tasks.event'], (p) => {
        const e = p as TaskEvent
        if (e.project_id === project_id) handler(e)
      })
      // backend replies with batch_snapshot events first (see contract)
      void this.call('tasks.subscribe', { project_id }).catch(() => undefined)
      return () => {
        off?.()
        void this.call('tasks.unsubscribe', { project_id }).catch(() => undefined)
      }
    },
    getBatch: (batch_id) => this.call('tasks.getBatch', { batch_id }),
    listBatches: (project_id) => this.call('tasks.listBatches', { project_id }),
    pauseQueue: (batch_id, request_id) => this.call('tasks.pauseQueue', { batch_id, request_id }),
    resumeQueue: (batch_id, request_id) => this.call('tasks.resumeQueue', { batch_id, request_id }),
    cancelJob: (job_id, request_id) => this.call('tasks.cancelJob', { job_id, request_id }),
    stopBatch: (batch_id, request_id) => this.call('tasks.stopBatch', { batch_id, request_id }),
    retryFailed: (batch_id, request_id, job_ids) => this.call('tasks.retryFailed', { batch_id, request_id, job_ids }),
  }

  recovery: V2LPAdapter['recovery'] = {
    inspect: (project_id, onProgress, signal) => {
      const off = this.bridge?.on(CHANNELS['recovery.progress'], (p) => onProgress(p as RecoveryProgress))
      return this.call<Awaited<ReturnType<V2LPAdapter['recovery']['inspect']>>>('recovery.inspect', { project_id }, signal).finally(() => off?.())
    },
    continueRemaining: (project_id, request_id) => this.call('recovery.continueRemaining', { project_id, request_id }),
    dismiss: (project_id) => this.call('recovery.dismiss', { project_id }),
  }

  files: V2LPAdapter['files'] = {
    openArtifact: (job_id, kind) => this.call('files.openArtifact', { job_id, kind }),
    revealOutput: (project_id, job_id) => this.call('files.revealOutput', { project_id, job_id }),
    readReport: (job_id) => this.call('files.readReport', { job_id }),
    pickOutputDir: () => this.call('files.pickOutputDir'),
  }

  settings: V2LPAdapter['settings'] = {
    get: () => this.call('settings.get'),
    update: (patch) => this.call('settings.update', patch),
    cacheInfo: () => this.call('settings.cacheInfo'),
    clearCache: (item_ids) => this.call('settings.clearCache', { item_ids }),
  }

  diagnostics: V2LPAdapter['diagnostics'] = {
    info: () => this.call('diagnostics.info'),
    logs: (limit) => this.call('diagnostics.logs', { limit }),
    exportBundle: (opts) => this.call('diagnostics.exportBundle', opts),
  }

  app: V2LPAdapter['app'] = {
    onCloseRequested: (handler) => this.bridge?.on(CHANNELS['app.closeRequested'], () => handler()) ?? (() => undefined),
    quit: () => this.call('app.quit'),
  }
}
