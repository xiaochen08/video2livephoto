import { reactive, watch } from 'vue'

/** UI-only preferences (layout, preview volume). Stored locally; never contains project data. */
export interface Prefs {
  leftWidth: number
  rightWidth: number
  leftCollapsed: boolean
  rightCollapsed: boolean
  timelineHeight: number
  previewVolume: number
  previewMuted: boolean
  reduceMotion: 'system' | 'on' | 'off'
}

const KEY = 'v2lp.ui.prefs.v1'
export const PREF_LIMITS = { left: [240, 420], right: [280, 440], timeline: [132, 320] } as const

const DEFAULTS: Prefs = {
  leftWidth: 296,
  rightWidth: 320,
  leftCollapsed: false,
  rightCollapsed: false,
  timelineHeight: 184,
  previewVolume: 0.8,
  previewMuted: false,
  reduceMotion: 'system',
}

export function createPrefs() {
  let initial = DEFAULTS
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) initial = { ...DEFAULTS, ...JSON.parse(raw) }
  } catch {
    /* ignore */
  }
  const prefs = reactive<Prefs>({ ...initial })
  let t: ReturnType<typeof setTimeout> | null = null
  watch(
    () => ({ ...prefs }),
    (v) => {
      if (t) clearTimeout(t)
      t = setTimeout(() => {
        try {
          localStorage.setItem(KEY, JSON.stringify(v))
        } catch {
          /* ignore */
        }
      }, 300)
    },
    { deep: true },
  )
  watch(
    () => prefs.reduceMotion,
    (v) => {
      const root = document.documentElement
      const sys = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      root.classList.toggle('reduce-motion', v === 'on' || (v === 'system' && !!sys))
    },
    { immediate: true },
  )
  return prefs
}

export type PrefsStore = ReturnType<typeof createPrefs>
