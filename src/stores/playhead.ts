import { ref } from 'vue'

/**
 * High-frequency playhead position kept outside Vue reactivity. Visual consumers (timeline line,
 * time readout) subscribe and write to the DOM directly; `coarse` is a throttled reactive mirror for
 * controls that only need an approximate value (e.g. enabling "add cut here").
 */
export function createPlayhead() {
  let frame = 0
  let playing = false
  const subs = new Set<(f: number, playing: boolean) => void>()
  const coarse = ref(0)
  const isPlaying = ref(false)
  let coarseTimer: ReturnType<typeof setTimeout> | null = null

  function notify() {
    subs.forEach((fn) => fn(frame, playing))
    if (!playing) {
      coarse.value = frame
      return
    }
    if (!coarseTimer) {
      coarseTimer = setTimeout(() => {
        coarseTimer = null
        coarse.value = frame
      }, 200)
    }
  }

  return {
    coarse,
    isPlaying,
    get frame() {
      return frame
    },
    get playing() {
      return playing
    },
    set(f: number) {
      if (f === frame) return
      frame = f
      notify()
    },
    setPlaying(p: boolean) {
      playing = p
      isPlaying.value = p
      notify()
    },
    subscribe(fn: (f: number, playing: boolean) => void) {
      subs.add(fn)
      fn(frame, playing)
      return () => subs.delete(fn)
    },
    /** request from UI to move the player (player listens) */
    seekRequests: new Set<(f: number) => void>(),
    requestSeek(f: number) {
      this.seekRequests.forEach((fn) => fn(f))
    },
    playRequests: new Set<(cmd: 'toggle' | 'play' | 'pause' | { from: number; to: number }) => void>(),
    requestPlay(cmd: 'toggle' | 'play' | 'pause' | { from: number; to: number }) {
      this.playRequests.forEach((fn) => fn(cmd))
    },
  }
}

export type Playhead = ReturnType<typeof createPlayhead>
