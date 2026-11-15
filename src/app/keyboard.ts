import { onBeforeUnmount, onMounted } from 'vue'
import type { Actions } from './actions'
import type { AppContext } from './context'

function isEditable(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  if (t.isContentEditable) return true
  const tag = t.tagName
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (tag === 'INPUT') {
    const type = (t as HTMLInputElement).type
    return !['checkbox', 'radio', 'button', 'range'].includes(type)
  }
  return false
}

function isActivatable(t: EventTarget | null): boolean {
  return t instanceof HTMLElement && (t.tagName === 'BUTTON' || t.getAttribute('role') === 'checkbox' || t.getAttribute('role') === 'switch' || t.tagName === 'A')
}

/**
 * Global shortcuts with explicit precedence:
 *  1. IME composition → ignored entirely
 *  2. Esc → top-most overlay first (ui.escape), then clear selection
 *  3. any modal open → modal owns the keyboard
 *  4. focus in a text field → the field owns the keyboard
 *  5. route-specific shortcuts
 */
export function useGlobalKeys(ctx: AppContext, actions: Actions, hooks: { openPicker: () => void }) {
  const { ui, session, selection, playhead, view } = ctx
  let nudge: { cut_id: string; frame: number; timer: ReturnType<typeof setTimeout> } | null = null

  function commitNudge() {
    if (!nudge) return
    const n = nudge
    nudge = null
    session.edit({ type: 'move_cut', cut_id: n.cut_id, frame: n.frame }).catch((e) => ui.toast(e.message ?? String(e), { tone: 'danger', timeout: 6000 }))
  }

  function stepFrames(delta: number) {
    const t = session.timeline.value
    if (!t) return
    playhead.requestPlay('pause')
    playhead.requestSeek(Math.max(0, Math.min(t.frame_count - 1, playhead.frame + delta)))
  }

  function onKey(e: KeyboardEvent) {
    if (e.isComposing || e.keyCode === 229) return
    const ctrl = e.ctrlKey || e.metaKey
    const key = e.key

    if (key === 'Escape') {
      if (ui.escape()) {
        e.preventDefault()
        return
      }
      if (ui.state.devPanelOpen) {
        ui.state.devPanelOpen = false
        return
      }
      if (isEditable(e.target)) return
      if (ui.state.route === 'editor') {
        if (selection.state.selectedCutId) selection.selectCut(null)
        else selection.clear()
      }
      return
    }
    if (ui.state.overlays.length) return
    if (isEditable(e.target)) return

    // global
    if (ctrl && key.toLowerCase() === 'o') {
      e.preventDefault()
      if (ui.state.route === 'home') hooks.openPicker()
      else void actions.goHome()
      return
    }
    if (ctrl && key.toLowerCase() === 's') {
      e.preventDefault()
      void actions.save()
      return
    }
    if (key === '?' || (e.shiftKey && key === '/')) {
      e.preventDefault()
      ui.dialogs.shortcuts.value = true
      return
    }

    if (ui.state.route !== 'editor' || !session.project.value) return
    const t = session.timeline.value!

    if (ctrl && !e.shiftKey && key.toLowerCase() === 'z') {
      e.preventDefault()
      void session.undo()
      return
    }
    if (ctrl && ((e.shiftKey && key.toLowerCase() === 'z') || key.toLowerCase() === 'y')) {
      e.preventDefault()
      void session.redo()
      return
    }
    if (ctrl && key.toLowerCase() === 'e') {
      e.preventDefault()
      actions.openExport()
      return
    }
    if (ctrl && key.toLowerCase() === 'a') {
      e.preventDefault()
      selection.selectAll(view.visibleIds.value)
      return
    }
    if (ctrl) return

    switch (key) {
      case ' ':
        if (isActivatable(e.target)) return
        e.preventDefault()
        playhead.requestPlay('toggle')
        return
      case 'ArrowLeft':
      case 'ArrowRight': {
        const dir = key === 'ArrowLeft' ? -1 : 1
        if (e.target instanceof HTMLElement && e.target.getAttribute('role') === 'radio') return
        e.preventDefault()
        if (e.altKey && selection.state.selectedCutId) {
          const ci = t.cuts.findIndex((c) => c.cut_id === selection.state.selectedCutId)
          if (ci < 0) return
          const base = nudge?.cut_id === t.cuts[ci].cut_id ? nudge.frame : t.cuts[ci].frame
          const min = t.clips[ci].start_frame + 1
          const max = t.clips[ci + 1].end_frame - 1
          const next = Math.max(min, Math.min(max, base + dir))
          if (nudge) clearTimeout(nudge.timer)
          nudge = { cut_id: t.cuts[ci].cut_id, frame: next, timer: setTimeout(commitNudge, 450) }
          session.state.tentative = { cut_id: nudge.cut_id, frame: next }
          playhead.requestSeek(next)
          return
        }
        stepFrames(e.shiftKey ? dir * Math.round(session.stream.value!.frame_rate.num / session.stream.value!.frame_rate.den) : dir)
        return
      }
      case 'ArrowUp':
      case 'ArrowDown': {
        e.preventDefault()
        const ids = view.visibleIds.value
        const cur = selection.state.focusedId ? ids.indexOf(selection.state.focusedId) : -1
        const nextId = ids[Math.max(0, Math.min(ids.length - 1, cur + (key === 'ArrowUp' ? -1 : 1)))]
        if (!nextId) return
        if (e.shiftKey) selection.click(nextId, { shift: true }, ids)
        else actions.focusClip(nextId)
        return
      }
      case 'Home':
      case 'End': {
        const c = session.clip(selection.state.focusedId)
        if (!c) return
        e.preventDefault()
        playhead.requestPlay('pause')
        playhead.requestSeek(key === 'Home' ? c.start_frame : c.end_frame - 1)
        return
      }
      case 'Delete':
      case 'Backspace':
        e.preventDefault()
        if (selection.state.selectedCutId) void actions.removeCut(selection.state.selectedCutId)
        else if (selection.state.selected.length) void actions.setExport(selection.state.selected, false, { toast: true })
        return
      case 'c':
      case 'C':
        void actions.addCutAtPlayhead()
        return
      case 'm':
      case 'M':
        void actions.mergeSelected()
        return
      case 'f':
      case 'F':
        view.state.trimZoom = 1
        return
      case '=':
      case '+':
        view.state.dock = 'trim'
        view.state.trimZoom = Math.min(16, view.state.trimZoom * 1.4)
        return
      case '-':
        view.state.trimZoom = Math.max(1, view.state.trimZoom / 1.4)
        return
      case 't':
      case 'T':
        view.state.dock = view.state.dock === 'cards' ? 'trim' : 'cards'
        return
      case 'r':
      case 'R':
        if (ui.state.editorMode === 'review') ui.state.editorMode = 'edit'
        else actions.startReview()
        return
    }
  }

  onMounted(() => window.addEventListener('keydown', onKey))
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKey)
    if (nudge) clearTimeout(nudge.timer)
  })
}
