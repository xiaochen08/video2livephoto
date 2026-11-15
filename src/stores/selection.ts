import { computed, reactive } from 'vue'
import type { ClipId, CutId, Timeline } from '@/domain/types'

/**
 * Four independent concepts, deliberately kept apart:
 *  - focusedId      当前查看片段 (drives preview + single inspector)
 *  - selected       当前多选集合 (drives batch inspector & batch actions)
 *  - clip.export_selected  是否参与导出 (lives on the clip, edited through commands)
 *  - cut.review     切点检查状态 (lives on the cut)
 * All keys are stable clip_id / cut_id; display numbers are never used.
 */
export function createSelection() {
  const state = reactive({
    focusedId: null as ClipId | null,
    selected: [] as ClipId[],
    anchorId: null as ClipId | null,
    selectedCutId: null as CutId | null,
    /** last interaction zone – decides what Delete acts on */
    zone: 'list' as 'list' | 'timeline' | 'cut',
  })

  const selectedSet = computed(() => new Set(state.selected))
  const count = computed(() => state.selected.length)

  function focus(id: ClipId | null, opts: { keepSelection?: boolean } = {}) {
    state.focusedId = id
    if (!opts.keepSelection) state.selected = id ? [id] : []
    state.anchorId = id
  }

  /** Click with modifiers. `ordered` = ids in the order currently displayed (after filter/sort). */
  function click(id: ClipId, mods: { ctrl?: boolean; shift?: boolean }, ordered: ClipId[]) {
    state.zone = 'list'
    state.selectedCutId = null
    if (mods.shift && state.anchorId && ordered.includes(state.anchorId)) {
      const a = ordered.indexOf(state.anchorId)
      const b = ordered.indexOf(id)
      const [lo, hi] = a < b ? [a, b] : [b, a]
      const range = ordered.slice(lo, hi + 1)
      state.selected = mods.ctrl ? [...new Set([...state.selected, ...range])] : range
      state.focusedId = id
      return
    }
    if (mods.ctrl) {
      const set = new Set(state.selected)
      if (set.has(id)) {
        set.delete(id)
        if (state.focusedId === id) state.focusedId = set.size ? [...set][set.size - 1] : null
      } else {
        set.add(id)
        state.focusedId = id
      }
      state.selected = ordered.filter((x) => set.has(x)).concat([...set].filter((x) => !ordered.includes(x)))
      state.anchorId = id
      return
    }
    focus(id)
  }

  function selectAll(ids: ClipId[]) {
    state.selected = [...ids]
    if (!state.focusedId || !ids.includes(state.focusedId)) state.focusedId = ids[0] ?? null
  }

  function keepOnly(ids: ClipId[]) {
    const keep = new Set(ids)
    state.selected = state.selected.filter((x) => keep.has(x))
    if (state.focusedId && !keep.has(state.focusedId)) state.focusedId = state.selected[0] ?? null
  }

  function clear() {
    state.selected = state.focusedId ? [state.focusedId] : []
    state.selectedCutId = null
  }

  function selectCut(id: CutId | null) {
    state.selectedCutId = id
    state.zone = id ? 'cut' : 'timeline'
  }

  /**
   * After a confirmed edit: drop removed ids, map merged clips onto the surviving id,
   * keep split results selected, and clear a selected cut that no longer exists.
   */
  function reconcile(t: Timeline, removed: ClipId[], affected: ClipId[]) {
    const alive = new Set(t.clips.map((c) => c.clip_id))
    const removedSet = new Set(removed)
    const hadRemoved = state.selected.some((id) => removedSet.has(id))
    let sel = state.selected.filter((id) => alive.has(id))
    if (hadRemoved) for (const id of affected) if (alive.has(id) && !sel.includes(id)) sel.push(id)
    state.selected = sel
    if (state.focusedId && !alive.has(state.focusedId)) {
      state.focusedId = affected.find((id) => alive.has(id)) ?? sel[0] ?? t.clips[0]?.clip_id ?? null
      if (state.focusedId && !sel.includes(state.focusedId)) state.selected = [...sel, state.focusedId]
    }
    if (state.anchorId && !alive.has(state.anchorId)) state.anchorId = state.focusedId
    if (state.selectedCutId && !t.cuts.some((c) => c.cut_id === state.selectedCutId)) state.selectedCutId = null
    if (!state.focusedId && t.clips.length) focus(t.clips[0].clip_id)
  }

  function reset() {
    state.focusedId = null
    state.selected = []
    state.anchorId = null
    state.selectedCutId = null
  }

  return { state, selectedSet, count, focus, click, selectAll, keepOnly, clear, selectCut, reconcile, reset }
}

export type SelectionStore = ReturnType<typeof createSelection>
