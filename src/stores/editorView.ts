import { computed, reactive } from 'vue'
import type { Clip, ClipId } from '@/domain/types'
import { clipDurationUs } from '@/domain/time'
import type { SessionStore } from './session'

export type ClipFilter = 'all' | 'review' | 'hints' | 'muted' | 'excluded' | 'outdated'
export type ClipSort = 'timeline' | 'duration_desc' | 'duration_asc'

/** View-only state of the editor: filter / sort / timeline zoom. Shared by list, timeline and shortcuts. */
export function createEditorView(session: SessionStore) {
  const state = reactive({
    filter: 'all' as ClipFilter,
    sort: 'timeline' as ClipSort,
    reviewCutId: null as string | null,
    /** bottom dock: clip cards or the trim track of the focused clip */
    dock: 'cards' as 'cards' | 'trim',
    trimZoom: 1,
    scrollToClip: 0,
  })

  function matches(c: Clip, f: ClipFilter): boolean {
    const h = session.hints.value.get(c.clip_id) ?? []
    switch (f) {
      case 'all':
        return true
      case 'review':
        return h.includes('review')
      case 'hints':
        return h.includes('short') || h.includes('long') || h.includes('cover')
      case 'muted':
        return c.audio === 'muted'
      case 'excluded':
        return !c.export_selected
      case 'outdated':
        return session.outdated.value.has(c.clip_id)
    }
  }

  const counts = computed(() => {
    const clips = session.timeline.value?.clips ?? []
    const r: Record<ClipFilter, number> = { all: clips.length, review: 0, hints: 0, muted: 0, excluded: 0, outdated: 0 }
    for (const c of clips) for (const f of ['review', 'hints', 'muted', 'excluded', 'outdated'] as const) if (matches(c, f)) r[f]++
    return r
  })

  const visible = computed<Clip[]>(() => {
    const clips = session.timeline.value?.clips ?? []
    const s = session.stream.value
    let list = state.filter === 'all' ? clips : clips.filter((c) => matches(c, state.filter))
    if (state.sort !== 'timeline' && s) {
      const dir = state.sort === 'duration_desc' ? -1 : 1
      list = [...list].sort((a, b) => dir * (clipDurationUs(a, s) - clipDurationUs(b, s)) || a.start_frame - b.start_frame)
    }
    return list
  })
  const visibleIds = computed<ClipId[]>(() => visible.value.map((c) => c.clip_id))

  function reset() {
    state.filter = 'all'
    state.sort = 'timeline'
    state.reviewCutId = null
    state.dock = 'cards'
    state.trimZoom = 1
  }

  return { state, counts, visible, visibleIds, reset }
}

export type EditorViewStore = ReturnType<typeof createEditorView>
