import { reactive, shallowRef } from 'vue'
import type { AnalysisEvent, AnalysisHandle, FileRef, ProbeResult, V2LPAdapter } from '@/adapters/contract'
import { isAbort, toAppError } from '@/domain/errors'
import { requestId } from '@/domain/ids'
import type { AppError, ImportColorSelection, ProjectId, RecentProject } from '@/domain/types'

export type AnalysisStatus = 'probing' | 'running' | 'failed' | 'cancelling' | 'cancelled' | 'done'

export interface AnalysisSession {
  file: FileRef
  projectName: string
  streamIndex: number
  colorOverride: ImportColorSelection | null
  status: AnalysisStatus
  event: AnalysisEvent | null
  probe: ProbeResult | null
  error: AppError | null
  minimized: boolean
  warnings: { code: string; message: string }[]
  projectId: ProjectId | null
  requestId: string
}

/** Home: recent projects, import/probe and the analysis run. One analysis at a time. */
export function createHome(adapter: V2LPAdapter) {
  const state = reactive({
    recents: [] as RecentProject[],
    loading: false,
    loadError: null as AppError | null,
    openingId: null as ProjectId | null,
    openError: null as { project_id: ProjectId; error: AppError } | null,
    importError: null as { file: string; error: AppError } | null,
    probing: null as string | null,
    queue: [] as File[],
  })
  const analysis = shallowRef<AnalysisSession | null>(null)
  let handle: AnalysisHandle | null = null
  let probeCtrl: AbortController | null = null

  async function loadRecents() {
    state.loading = true
    state.loadError = null
    try {
      state.recents = await adapter.projects.listRecent()
    } catch (e) {
      state.loadError = toAppError(e)
    } finally {
      state.loading = false
    }
  }

  function patchAnalysis(p: Partial<AnalysisSession>) {
    if (analysis.value) analysis.value = { ...analysis.value, ...p }
  }

  async function probe(file: FileRef): Promise<ProbeResult | null> {
    probeCtrl?.abort()
    const ctrl = (probeCtrl = new AbortController())
    state.importError = null
    state.probing = file.name
    try {
      const res = await adapter.media.probe(file, ctrl.signal)
      return ctrl === probeCtrl ? res : null
    } catch (e) {
      if (isAbort(e)) return null
      state.importError = { file: file.name, error: toAppError(e) }
      return null
    } finally {
      if (ctrl === probeCtrl) state.probing = null
    }
  }

  /** Starts analysis. Guarded so repeated clicks never start a second identical job. */
  function startAnalysis(probeRes: ProbeResult, streamIndex: number, colorOverride: ImportColorSelection | null = null): boolean {
    if (analysis.value && ['probing', 'running', 'cancelling'].includes(analysis.value.status)) return false
    const name = probeRes.file.name.replace(/\.[^.]+$/, '')
    const rid = requestId('analysis')
    analysis.value = {
      file: probeRes.file,
      projectName: name,
      streamIndex,
      colorOverride,
      status: 'running',
      event: null,
      probe: probeRes,
      error: null,
      minimized: false,
      warnings: [],
      projectId: null,
      requestId: rid,
    }
    run(rid)
    return true
  }

  function run(rid: string) {
    const a = analysis.value!
    const h = adapter.analysis.start({ file: a.file, video_stream_index: a.streamIndex, project_name: a.projectName, request_id: rid, color_override: a.colorOverride }, (e) => {
      if (analysis.value?.requestId !== rid) return
      const prev = analysis.value.event
      if (prev && e.seq <= prev.seq) return
      patchAnalysis({ event: e })
    })
    handle = h
    h.done
      .then((res) => {
        if (analysis.value?.requestId !== rid) return
        patchAnalysis({ status: 'done', projectId: res.project_id, warnings: res.warnings })
      })
      .catch((e) => {
        if (analysis.value?.requestId !== rid) return
        if (isAbort(e)) patchAnalysis({ status: 'cancelled' })
        else patchAnalysis({ status: 'failed', error: toAppError(e) })
      })
  }

  function retryAnalysis() {
    const a = analysis.value
    if (!a || a.status !== 'failed') return
    const rid = requestId('analysis')
    analysis.value = { ...a, status: 'running', error: null, event: null, requestId: rid }
    run(rid)
  }

  async function cancelAnalysis() {
    const a = analysis.value
    if (!a || a.status !== 'running') return
    patchAnalysis({ status: 'cancelling' })
    await handle?.cancel()
    patchAnalysis({ status: 'cancelled' })
  }

  function clearAnalysis() {
    analysis.value = null
    handle = null
  }

  return { state, analysis, loadRecents, probe, startAnalysis, retryAnalysis, cancelAnalysis, clearAnalysis, patchAnalysis }
}

export type HomeStore = ReturnType<typeof createHome>
