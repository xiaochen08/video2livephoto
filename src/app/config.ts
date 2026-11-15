/**
 * Run mode is chosen explicitly at build/start time (vite --mode):
 *   demo | development → DemoAdapter (browser preview, all results simulated)
 *   desktop            → DesktopAdapter (Electron bridge; never falls back to demo)
 *   anything else      → configuration error screen
 */
export type RunMode = 'demo' | 'desktop' | 'invalid'

export function resolveRunMode(mode: string = import.meta.env.MODE): RunMode {
  if (mode === 'demo' || mode === 'development' || mode === 'test') return 'demo'
  if (mode === 'desktop') return 'desktop'
  return 'invalid'
}

export const RUN_MODE: RunMode = resolveRunMode()
export const VITE_MODE = import.meta.env.MODE
export const SHOW_DEV_TOOLS = RUN_MODE === 'demo'
