import { inject, type InjectionKey, type Ref, shallowRef } from 'vue'
import type { ConnectionInfo, V2LPAdapter } from '@/adapters/contract'
import { createEditorView } from '@/stores/editorView'
import { createHome } from '@/stores/home'
import { createPlayhead } from '@/stores/playhead'
import { createPrefs } from '@/stores/prefs'
import { createSelection } from '@/stores/selection'
import { createSession } from '@/stores/session'
import { createTasks } from '@/stores/tasks'
import { createUi } from '@/stores/ui'

export function createAppContext(adapter: V2LPAdapter) {
  const conn: Ref<ConnectionInfo | null> = shallowRef(null)
  const ui = createUi()
  const prefs = createPrefs()
  const selection = createSelection()
  const session = createSession(adapter, selection, () => conn.value)
  const tasks = createTasks(adapter)
  const home = createHome(adapter)
  const playhead = createPlayhead()
  const view = createEditorView(session)
  return { adapter, conn, ui, prefs, selection, session, tasks, home, playhead, view }
}

export type AppContext = ReturnType<typeof createAppContext>
export const APP_CONTEXT: InjectionKey<AppContext> = Symbol('v2lp-app')

export function useApp(): AppContext {
  const ctx = inject(APP_CONTEXT)
  if (!ctx) throw new Error('App context not provided')
  return ctx
}

import type { Actions } from './actions'
export const APP_ACTIONS: InjectionKey<Actions> = Symbol('v2lp-actions')
export function useActions(): Actions {
  const a = inject(APP_ACTIONS)
  if (!a) throw new Error('Actions not provided')
  return a
}
