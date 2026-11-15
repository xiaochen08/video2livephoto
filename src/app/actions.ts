import { audioConflict } from '@/domain/timelineCore'
import { toAppError } from '@/domain/errors'
import type { AudioMode, ClipId, CutId, ProjectId } from '@/domain/types'
import type { AppContext } from './context'

/**
 * Cross-feature user flows. Pages, menus and shortcuts call these so every entry point shares the
 * same guards (unsaved changes, audio conflicts, duplicate submissions).
 */
export function createActions(ctx: AppContext) {
  const { session, selection, ui, home, tasks, playhead, view, adapter } = ctx

  async function leaveGuard(target: string): Promise<boolean> {
    if (!session.project.value) return true
    if (!session.dirty.value && session.saveState.value !== 'saving') return true
    const choice = await new Promise<'save' | 'discard' | 'cancel'>((resolve) => {
      ui.dialogs.leaveGuard.value = {
        target,
        resolve: (c) => {
          ui.dialogs.leaveGuard.value = null
          resolve(c)
        },
      }
    })
    if (choice === 'cancel') return false
    if (choice === 'discard') return true
    try {
      return await session.save()
    } catch {
      ui.toast('保存失败，仍停留在当前项目。可重试保存或选择不保存离开。', { tone: 'danger' })
      return false
    }
  }

  async function openProject(projectId: ProjectId) {
    if (session.project.value?.project_id === projectId && session.state.status === 'ready') {
      ui.state.route = 'editor'
      return
    }
    if (!(await leaveGuard('打开其他项目'))) return
    home.state.openError = null
    home.state.openingId = projectId
    try {
      const ok = await session.open(projectId)
      if (!ok) return
      tasks.attach(projectId)
      view.reset()
      ui.state.editorMode = 'edit'
      ui.state.route = 'editor'
      if (session.project.value?.recovery_pending) ui.dialogs.recovery.value = { project_id: projectId }
    } catch (e) {
      home.state.openError = { project_id: projectId, error: toAppError(e) }
      ui.state.route = 'home'
    } finally {
      if (home.state.openingId === projectId) home.state.openingId = null
    }
  }

  async function goHome() {
    if (!(await leaveGuard('返回首页'))) return
    session.close()
    tasks.detach()
    ui.state.route = 'home'
    void home.loadRecents()
  }

  function focusClip(id: ClipId, seek = true) {
    selection.focus(id)
    const c = session.clip(id)
    if (c && seek) playhead.requestSeek(c.start_frame)
    view.state.scrollToClip++
  }

  async function askAudio(kind: 'remove_cut' | 'merge_clips', clipIds: ClipId[], cutId?: CutId): Promise<AudioMode | null | undefined> {
    const clips = clipIds.map((id) => session.clip(id)).filter((c): c is NonNullable<typeof c> => !!c)
    if (!audioConflict(clips)) return undefined
    return new Promise((resolve) => {
      ui.dialogs.mergeConflict.value = {
        kind,
        cut_id: cutId,
        clip_ids: clipIds,
        muted: clips.filter((c) => c.audio === 'muted').length,
        source: clips.filter((c) => c.audio === 'source').length,
        resolve: (choice) => {
          ui.dialogs.mergeConflict.value = null
          resolve(choice)
        },
      }
    })
  }

  function reportEditError(e: unknown) {
    const err = toAppError(e)
    if (err.code !== 'EDIT_VERSION_CONFLICT') ui.toast(err.message, { tone: 'danger', timeout: 6000 })
  }

  async function removeCut(cutId: CutId) {
    const t = session.timeline.value
    if (!t) return
    const i = t.cuts.findIndex((c) => c.cut_id === cutId)
    if (i < 0) return
    const ids = [t.clips[i].clip_id, t.clips[i + 1].clip_id]
    const audio = await askAudio('remove_cut', ids, cutId)
    if (audio === null) return
    try {
      const res = await session.edit({ type: 'remove_cut', cut_id: cutId, audio_resolution: audio })
      if (res) {
        selection.selectCut(null)
        ui.toast(`已删除切点，片段 ${t.clips[i].display_index} 与 ${t.clips[i + 1].display_index} 合并为一个片段`, { action: { label: '撤销', run: () => void session.undo() } })
      }
    } catch (e) {
      reportEditError(e)
    }
  }

  async function mergeSelected() {
    const t = session.timeline.value
    if (!t) return
    const ids = mergeableSelection()
    if (!ids) {
      ui.toast('请选择 2 个及以上时间上相邻的片段再合并。', { tone: 'warning' })
      return
    }
    const audio = await askAudio('merge_clips', ids)
    if (audio === null) return
    try {
      const res = await session.edit({ type: 'merge_clips', clip_ids: ids, audio_resolution: audio })
      if (res) ui.toast(`已合并 ${ids.length} 个片段`, { action: { label: '撤销', run: () => void session.undo() } })
    } catch (e) {
      reportEditError(e)
    }
  }

  /** selected ids ordered by timeline if contiguous and ≥2, else null */
  function mergeableSelection(): ClipId[] | null {
    const t = session.timeline.value
    if (!t || selection.state.selected.length < 2) return null
    const idx = selection.state.selected.map((id) => session.clipIndexById.value.get(id) ?? -1).sort((a, b) => a - b)
    if (idx[0] < 0) return null
    for (let i = 1; i < idx.length; i++) if (idx[i] !== idx[i - 1] + 1) return null
    return idx.map((i) => t.clips[i].clip_id)
  }

  async function addCutAtPlayhead() {
    const f = playhead.frame
    const t = session.timeline.value
    if (!t) return
    const inside = t.clips.some((c) => f > c.start_frame && f < c.end_frame)
    if (!inside) {
      ui.toast('播放头位于片段边界上，无法在此添加切点。', { tone: 'warning' })
      return
    }
    try {
      await session.edit({ type: 'add_cut', frame: f })
    } catch (e) {
      reportEditError(e)
    }
  }

  async function setAudio(ids: ClipId[], mode: AudioMode) {
    const targets = ids.filter((id) => session.clip(id)?.audio !== mode)
    if (!targets.length) return
    try {
      await session.edit({ type: 'set_clip_props', clip_ids: targets, patch: { audio: mode } })
      if (targets.length > 1) ui.toast(`已${mode === 'muted' ? '静音' : '恢复原声'} ${targets.length} 个片段`, { action: { label: '撤销', run: () => void session.undo() } })
    } catch (e) {
      reportEditError(e)
    }
  }

  async function setExport(ids: ClipId[], value: boolean, opts: { toast?: boolean } = {}) {
    const targets = ids.filter((id) => session.clip(id)?.export_selected !== value)
    if (!targets.length) return
    try {
      await session.edit({ type: 'set_clip_props', clip_ids: targets, patch: { export_selected: value } })
      if (opts.toast || targets.length > 1) {
        ui.toast(`${value ? '已加入导出' : '已取消导出选择'}：${targets.length} 个片段${value ? '' : '（时间线画面保留）'}`, { action: { label: '撤销', run: () => void session.undo() } })
      }
    } catch (e) {
      reportEditError(e)
    }
  }

  async function save() {
    try {
      const ok = await session.save()
      if (ok && ctx.adapter.mode === 'demo') ui.toast('已保存（演示：模拟持久化）', { tone: 'success', timeout: 1800 })
    } catch (e) {
      ui.toast(toAppError(e).message, { tone: 'danger', timeout: 6000 })
    }
  }

  function openExport() {
    const t = session.timeline.value
    if (!t) return
    if (!t.clips.some((c) => c.export_selected)) {
      ui.toast('没有参与导出的片段。请在片段列表中勾选。', { tone: 'warning' })
      return
    }
    ui.dialogs.exportConfirm.value = true
  }

  function startReview(cutId?: string) {
    const pending = session.pendingCuts.value
    view.state.reviewCutId = cutId ?? view.state.reviewCutId ?? pending[0]?.cut_id ?? session.timeline.value?.cuts[0]?.cut_id ?? null
    ui.state.editorMode = 'review'
  }

  async function requestClose() {
    ui.dialogs.closeApp.value = true
  }

  async function reanalyze() {
    const p = session.project.value
    if (!p) return
    const ok = await ui.confirm({
      title: '重新分析镜头？',
      message: '重新分析会生成新的分析结果版本。已保存的人工切点修改、片段设置与审核记录会受到保护，不会被覆盖。',
      confirmLabel: '生成新分析版本',
    })
    if (!ok) return
    try {
      const res = await adapter.analysis.reanalyze(p.project_id, `reanalyze-${p.project_id}-${p.edit_version}`)
      ui.toast(res.preserved, { tone: 'success', timeout: 6000 })
    } catch (e) {
      ui.toast(toAppError(e).message, { tone: 'danger' })
    }
  }

  return {
    leaveGuard,
    openProject,
    goHome,
    focusClip,
    removeCut,
    mergeSelected,
    mergeableSelection,
    addCutAtPlayhead,
    setAudio,
    setExport,
    save,
    openExport,
    startReview,
    requestClose,
    reanalyze,
  }
}

export type Actions = ReturnType<typeof createActions>
