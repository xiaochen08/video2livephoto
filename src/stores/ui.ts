import { reactive, shallowRef } from 'vue'
import type { ProbeResult, RecoverySummary } from '@/adapters/contract'
import type { AppError, AudioMode, ClipId, CutId, ImportColorSelection, ProjectId } from '@/domain/types'

export type Route = 'boot' | 'connection_error' | 'config_error' | 'home' | 'editor' | 'tasks' | 'settings'

export interface Toast {
  id: number
  tone: 'neutral' | 'success' | 'warning' | 'danger'
  message: string
  action?: { label: string; run: () => void }
  timeout: number
}

export interface OverlayEntry {
  id: string
  close: () => void
  closable: () => boolean
}

export interface MergeConflictState {
  kind: 'remove_cut' | 'merge_clips'
  cut_id?: CutId
  clip_ids: ClipId[]
  muted: number
  source: number
  resolve: (choice: AudioMode | null) => void
}

export interface ConfirmState {
  title: string
  message: string
  detail?: string
  confirmLabel: string
  cancelLabel?: string
  tone?: 'primary' | 'danger'
  resolve: (ok: boolean) => void
}

export interface PromptState {
  title: string
  label: string
  value: string
  hint?: string
  confirmLabel: string
  validate?: (v: string) => string | null
  resolve: (v: string | null) => void
}

export function createUi() {
  const state = reactive({
    route: 'boot' as Route,
    editorMode: 'edit' as 'edit' | 'review',
    tasksTab: 'queue' as 'queue' | 'results',
    settingsSection: 'export' as 'export' | 'preview' | 'shortcuts' | 'diagnostics' | 'about',
    connectionError: null as AppError | null,
    overlays: [] as OverlayEntry[],
    toasts: [] as Toast[],
    devPanelOpen: false,
    pickerRequest: 0,
    windowTooSmall: false,
  })

  const dialogs = {
    exportConfirm: shallowRef(false),
    shortcuts: shallowRef(false),
    cover: shallowRef<ClipId | null>(null),
    mergeConflict: shallowRef<MergeConflictState | null>(null),
    confirm: shallowRef<ConfirmState | null>(null),
    prompt: shallowRef<PromptState | null>(null),
    recovery: shallowRef<{ project_id: ProjectId; summary?: RecoverySummary } | null>(null),
    relocate: shallowRef<{ project_id: ProjectId; name: string; reason: 'missing' | 'changed' } | null>(null),
    multiFile: shallowRef<File[] | null>(null),
    streamSelect: shallowRef<{ probe: ProbeResult; resolve: (idx: number | null) => void } | null>(null),
    colorSelect: shallowRef<{ probe: ProbeResult; streamIndex: number; resolve: (choice: ImportColorSelection | null) => void } | null>(null),
    leaveGuard: shallowRef<{ target: string; resolve: (choice: 'save' | 'discard' | 'cancel') => void } | null>(null),
    closeApp: shallowRef(false),
    report: shallowRef<{ title: string; body: string } | null>(null),
  }

  let toastId = 0
  function toast(message: string, opts: Partial<Omit<Toast, 'id' | 'message'>> = {}) {
    const t: Toast = { id: ++toastId, message, tone: opts.tone ?? 'neutral', action: opts.action, timeout: opts.timeout ?? 4200 }
    state.toasts.push(t)
    if (state.toasts.length > 4) state.toasts.shift()
    if (t.timeout > 0) setTimeout(() => dismissToast(t.id), t.timeout)
    return t.id
  }
  function dismissToast(id: number) {
    const i = state.toasts.findIndex((t) => t.id === id)
    if (i >= 0) state.toasts.splice(i, 1)
  }

  function pushOverlay(entry: OverlayEntry) {
    state.overlays.push(entry)
  }
  function popOverlay(id: string) {
    const i = state.overlays.findIndex((o) => o.id === id)
    if (i >= 0) state.overlays.splice(i, 1)
  }
  /** Esc: close the top-most closable overlay. Returns true when something handled it. */
  function escape(): boolean {
    const top = state.overlays[state.overlays.length - 1]
    if (!top) return false
    if (top.closable()) top.close()
    return true
  }

  function confirm(opts: Omit<ConfirmState, 'resolve'>): Promise<boolean> {
    return new Promise((resolve) => {
      dialogs.confirm.value = {
        ...opts,
        resolve: (ok) => {
          dialogs.confirm.value = null
          resolve(ok)
        },
      }
    })
  }

  function prompt(opts: Omit<PromptState, 'resolve'>): Promise<string | null> {
    return new Promise((resolve) => {
      dialogs.prompt.value = {
        ...opts,
        resolve: (v) => {
          dialogs.prompt.value = null
          resolve(v)
        },
      }
    })
  }

  return { state, dialogs, toast, dismissToast, pushOverlay, popOverlay, escape, confirm, prompt }
}

export type UiStore = ReturnType<typeof createUi>
