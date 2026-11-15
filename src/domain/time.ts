import type { Clip, Rational, VideoStreamInfo } from './types'

/** Frame duration in microseconds for a CFR stream (display only; VFR uses PTS from backend). */
export function frameDurationUs(rate: Rational): number {
  return (1_000_000 * rate.den) / rate.num
}

export function framesToUs(frames: number, rate: Rational): number {
  return Math.round((frames * 1_000_000 * rate.den) / rate.num)
}

/** Nearest frame index that starts at or before `us` (display-time → frame index). */
export function usToFrame(us: number, rate: Rational): number {
  return Math.floor((us * rate.num) / (1_000_000 * rate.den) + 1e-6)
}

export function rateToString(rate: Rational): string {
  if (rate.den === 1) return `${rate.num}`
  const v = rate.num / rate.den
  return v.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')
}

/** PTS (bigint string) × time_base → microseconds, using BigInt to avoid precision loss. */
export function ptsToUs(pts: string, timeBase: Rational): number {
  const value = BigInt(pts) * 1_000_000n * BigInt(timeBase.num)
  return Number(value / BigInt(timeBase.den))
}

export function clipFrames(clip: Pick<Clip, 'start_frame' | 'end_frame'>): number {
  return clip.end_frame - clip.start_frame
}

/**
 * Clip duration in µs. For VFR streams the PTS boundaries supplied by the backend are
 * authoritative; nominal frame rate is only used for CFR or when PTS is missing.
 */
export function clipDurationUs(clip: Clip, stream: VideoStreamInfo): number {
  if (stream.vfr && clip.start_pts && clip.end_pts) {
    return ptsToUs(clip.end_pts, stream.time_base) - ptsToUs(clip.start_pts, stream.time_base)
  }
  return framesToUs(clipFrames(clip), stream.frame_rate)
}

export function frameToUs(frame: number, stream: VideoStreamInfo, pts: string | null = null): number {
  if (stream.vfr && pts !== null) return ptsToUs(pts, stream.time_base)
  return framesToUs(frame, stream.frame_rate)
}

/** `mm:ss.mmm` (or `h:mm:ss.mmm`) – display time code, never used for seeking decisions. */
export function formatTime(us: number): string {
  const neg = us < 0
  const totalMs = Math.round(Math.abs(us) / 1000)
  const ms = totalMs % 1000
  const s = Math.floor(totalMs / 1000) % 60
  const m = Math.floor(totalMs / 60000) % 60
  const h = Math.floor(totalMs / 3_600_000)
  const core = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
  return (neg ? '-' : '') + (h > 0 ? `${h}:${core}` : core)
}

/** Human duration: 0.20 s / 5.04 s / 1:02.3 */
export function formatDuration(us: number): string {
  const s = us / 1_000_000
  if (s < 60) return `${s.toFixed(2)} 秒`
  const m = Math.floor(s / 60)
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, '0')}`
}

export function formatDurationShort(us: number): string {
  const s = us / 1_000_000
  if (s < 60) return `${s.toFixed(2)}s`
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.floor(s - m * 60)).padStart(2, '0')}`
}

export function formatFrame(frame: number): string {
  return `#${frame}`
}

export function formatBytes(bytes: string | number | null): string {
  if (bytes === null) return '—'
  const n = typeof bytes === 'string' ? Number(bytes) : bytes
  if (!Number.isFinite(n)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export function formatClock(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (sameDay) return `今天 ${hm}`
  return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
}
