import { computed, reactive, shallowRef } from 'vue'
import type { ConnectionInfo, EditResult, PreviewSource, V2LPAdapter } from '@/adapters/contract'
import { clipHints, type ClipHint } from '@/domain/clipHints'
import { commandLabel, type EditCommand } from '@/domain/commands'
import { isAbort, toAppError } from '@/domain/errors'
import { requestId } from '@/domain/ids'
import type { AppError, Capabilities, Clip, ClipId, Project, ProjectId, VideoStreamInfo } from '@/domain/types'
import type { SelectionStore } from './selection'

export type SaveState = 'saved' | 'dirty' | 'saving' | 'failed'
export type OpPhase = 'requested' | 'processing'

export interface PendingOp {
  id: string
  label: string
  phase: OpPhase
}

const AUTOSAVE_MS = 1500

/**
 * Editing session for one open project.
 * - Every async result is checked against `token`; a project switch invalidates older results.
 * - Edits are serialised: one command in flight, each based on the latest confirmed edit_version.
 * - UI shows the backend-confirmed timeline only; `tentative` carries an unconfirmed drag position.
 */
export function createSession(adapter: V2LPAdapter, selection: SelectionStore, conn: () => ConnectionInfo | null) {
  const project = shallowRef<Project | null>(null)
  const state = reactive({
    token: 0,
    status: 'idle' as 'idle' | 'opening' | 'ready' | 'error',
    openingId: null as ProjectId | null,
    openError: null as AppError | null,
    warnings: [] as AppError[],
    preview: null as PreviewSource | null,
    pending: null as PendingOp | null,
    queueLength: 0,
    rejection: null as { message: string; code: string; at: number } | null,
    notes: [] as string[],
    savingVersion: null as number | null,
    saveError: null as AppError | null,
    tentative: null as { cut_id: string; frame: number } | null,
  })

  let openCtrl: AbortController | null = null
  let chain: Promise<unknown> = Promise.resolve()
  let autosaveTimer: ReturnType<typeof setTimeout> | null = null

  const timeline = computed(() => project.value?.timeline ?? null)
  const stream = computed<VideoStreamInfo | null>(() => {
    const p = project.value
    if (!p) return null
    return p.media.video_streams[p.media.selected_video_stream ?? 0] ?? p.media.video_streams[0] ?? null
  })
  const caps = computed<Capabilities | null>(() => conn()?.capabilities ?? null)
  const hasAudio = computed(() => (project.value?.media.audio_streams.length ?? 0) > 0)
  const clipsById = computed(() => new Map((timeline.value?.clips ?? []).map((c) => [c.clip_id, c])))
  const clipIndexById = computed(() => new Map((timeline.value?.clips ?? []).map((c, i) => [c.clip_id, i])))
  const pendingCuts = computed(() => (timeline.value?.cuts ?? []).filter((c) => c.review === 'pending'))
  const hints = computed(() => {
    const map = new Map<ClipId, ClipHint[]>()
    const t = timeline.value
    const s = stream.value
    const c = caps.value
    if (!t || !s || !c) return map
    t.clips.forEach((clip, i) => map.set(clip.clip_id, clipHints(clip, i, t, s, c)))
    return map
  })
  const outdated = computed(() => new Set(project.value?.outdated_clip_ids ?? []))

  const saveState = computed<SaveState>(() => {
    const p = project.value
    if (!p) return 'saved'
    if (state.savingVersion !== null) return 'saving'
    if (p.saved_edit_version >= p.edit_version) return 'saved'
    if (state.saveError) return 'failed'
    return 'dirty'
  })
  const dirty = computed(() => !!project.value && project.value.saved_edit_version < project.value.edit_version)

  async function open(projectId: ProjectId): Promise<boolean> {
    openCtrl?.abort()
    const ctrl = (openCtrl = new AbortController())
    const token = ++state.token
    state.status = 'opening'
    state.openingId = projectId
    state.openError = null
    try {
      const res = await adapter.projects.open(projectId, ctrl.signal)
      if (token !== state.token) return false
      const preview = await adapter.preview.getSource(projectId).catch(() => null)
      if (token !== state.token) return false
      project.value = res.project
      state.warnings = res.warnings
      state.preview = preview
      state.status = 'ready'
      state.openingId = null
      state.pending = null
      state.rejection = null
      state.saveError = null
      state.savingVersion = null
      state.tentative = null
      selection.reset()
      const first = res.project.timeline.clips[0]
      if (first) selection.focus(first.clip_id)
      return true
    } catch (e) {
      if (token !== state.token || isAbort(e)) return false
      state.status = project.value ? 'ready' : 'error'
      state.openingId = null
      state.openError = toAppError(e, { scope: { project_id: projectId } })
      throw state.openError
    }
  }

  function close() {
    openCtrl?.abort()
    state.token++
    if (autosaveTimer) clearTimeout(autosaveTimer)
    project.value = null
    state.status = 'idle'
    state.preview = null
    state.pending = null
    state.tentative = null
    state.savingVersion = null
    state.saveError = null
    chain = Promise.resolve()
    state.queueLength = 0
    selection.reset()
  }

  function applyResult(res: EditResult) {
    const p = project.value
    if (!p) return
    // never let an older confirmed version replace a newer one
    if (res.edit_version <= p.edit_version) return
    project.value = { ...p, timeline: res.timeline, edit_version: res.edit_version, history: res.history, outdated_clip_ids: res.outdated_clip_ids }
    selection.reconcile(res.timeline, res.removed_clip_ids, res.affected_clip_ids)
    state.notes = res.notes
    scheduleAutosave()
  }

  type Runner = (base: number, rid: string) => Promise<EditResult>

  function enqueue(label: string, run: Runner): Promise<EditResult | null> {
    const token = state.token
    const op: PendingOp = { id: requestId('op'), label, phase: 'requested' }
    state.queueLength++
    const p = chain.then(async () => {
      if (token !== state.token || !project.value) return null
      state.pending = { ...op, phase: 'processing' }
      try {
        const res = await run(project.value.edit_version, op.id)
        if (token !== state.token) return null
        applyResult(res)
        state.rejection = null
        return res
      } catch (e) {
        if (token !== state.token) return null
        const err = toAppError(e)
        state.rejection = { message: err.message, code: err.code, at: Date.now() }
        if (err.code === 'EDIT_VERSION_CONFLICT' && project.value) await refresh(token)
        throw err
      } finally {
        if (token === state.token) {
          state.queueLength--
          if (state.queueLength === 0) state.pending = null
          state.tentative = null
        }
      }
    })
    if (!state.pending) state.pending = op
    chain = p.catch(() => undefined)
    return p
  }

  async function refresh(token: number) {
    const p = project.value
    if (!p) return
    const res = await adapter.projects.open(p.project_id).catch(() => null)
    if (!res || token !== state.token) return
    project.value = { ...res.project, saved_edit_version: Math.max(res.project.saved_edit_version, p.saved_edit_version) }
    selection.reconcile(res.project.timeline, [], [])
  }

  function edit(cmd: EditCommand) {
    const pid = project.value?.project_id
    if (!pid) return Promise.resolve(null)
    return enqueue(commandLabel(cmd), (base, rid) => adapter.timeline.apply(pid, base, cmd, rid))
  }

  function undo() {
    const p = project.value
    if (!p?.history.can_undo) return Promise.resolve(null)
    return enqueue(`撤销：${p.history.undo_label ?? ''}`, (base, rid) => adapter.timeline.undo(p.project_id, base, rid))
  }

  function redo() {
    const p = project.value
    if (!p?.history.can_redo) return Promise.resolve(null)
    return enqueue(`重做：${p.history.redo_label ?? ''}`, (base, rid) => adapter.timeline.redo(p.project_id, base, rid))
  }

  function scheduleAutosave() {
    if (autosaveTimer) clearTimeout(autosaveTimer)
    autosaveTimer = setTimeout(() => void save().catch(() => undefined), AUTOSAVE_MS)
  }

  /** Persist the current edit version. "已保存" only after the backend confirms. */
  async function save(): Promise<boolean> {
    const p = project.value
    if (!p) return true
    if (autosaveTimer) clearTimeout(autosaveTimer)
    if (p.saved_edit_version >= p.edit_version) return true
    const token = state.token
    const version = p.edit_version
    state.savingVersion = version
    state.saveError = null
    try {
      const res = await adapter.projects.save(p.project_id, version, requestId('save'))
      if (token !== state.token || !project.value) return false
      const cur = project.value
      // stale receipts (older version) never lower or overwrite the saved marker
      if (res.saved_edit_version > cur.saved_edit_version) project.value = { ...cur, saved_edit_version: res.saved_edit_version }
      return project.value!.saved_edit_version >= project.value!.edit_version
    } catch (e) {
      if (token !== state.token) return false
      state.saveError = toAppError(e)
      throw state.saveError
    } finally {
      if (token === state.token && state.savingVersion === version) state.savingVersion = null
    }
  }

  async function rename(name: string) {
    const p = project.value
    if (!p) return
    await adapter.projects.rename(p.project_id, name)
    if (project.value?.project_id === p.project_id) project.value = { ...project.value, name: name.trim() }
  }

  function setRecoveryPending(v: boolean) {
    if (project.value) project.value = { ...project.value, recovery_pending: v }
  }

  function clip(id: ClipId | null): Clip | null {
    return id ? (clipsById.value.get(id) ?? null) : null
  }

  return {
    project,
    state,
    timeline,
    stream,
    caps,
    hasAudio,
    clipsById,
    clipIndexById,
    pendingCuts,
    hints,
    outdated,
    saveState,
    dirty,
    open,
    close,
    edit,
    undo,
    redo,
    save,
    rename,
    clip,
    setRecoveryPending,
  }
}

export type SessionStore = ReturnType<typeof createSession>
