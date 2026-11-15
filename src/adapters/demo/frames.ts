/**
 * DEMO frame provider. Stands in for the backend's exact frame decoder:
 *  - with a preview URL: seeks a hidden <video> and captures the frame to a canvas
 *    (browser seeking is approximate → results are flagged exact=false);
 *  - without one: draws a clearly labelled placeholder frame.
 * Object URLs are ref-counted and evicted LRU with a fixed capacity; evicted entries are revoked.
 */
import { AdapterError, makeError } from '@/domain/errors'
import type { Rational } from '@/domain/types'

interface Entry {
  url: string
  refs: number
  used: number
  size: 'thumb' | 'full'
}

export interface FrameSourceDef {
  key: string
  url: string | null
  rate: Rational
  width: number
  height: number
  /** hue per frame for placeholder frames */
  hueOf?: (frame: number) => number
  label?: string
}

const CAPACITY = { thumb: 360, full: 32 }

export class DemoFrameProvider {
  private cache = new Map<string, Entry>()
  private byUrl = new Map<string, string>()
  private inflight = new Map<string, Promise<string>>()
  private videos = new Map<string, { el: HTMLVideoElement; queue: Promise<unknown> }>()
  private clock = 0
  latency: () => number = () => 0
  failRate = 0

  stats() {
    let thumb = 0
    let full = 0
    for (const e of this.cache.values()) e.size === 'thumb' ? thumb++ : full++
    return { thumb, full, capacity: CAPACITY }
  }

  async get(src: FrameSourceDef, frame: number, size: 'thumb' | 'full', signal?: AbortSignal): Promise<string> {
    const key = `${src.key}:${size}:${frame}`
    const hit = this.cache.get(key)
    if (hit) {
      hit.refs++
      hit.used = ++this.clock
      return hit.url
    }
    let p = this.inflight.get(key)
    if (!p) {
      p = this.render(src, frame, size)
        .then((url) => {
          // registered immediately (refs 0) so an aborted caller never leaks the URL
          this.cache.set(key, { url, refs: 0, used: ++this.clock, size })
          this.byUrl.set(url, key)
          return url
        })
        .finally(() => this.inflight.delete(key))
      this.inflight.set(key, p)
    }
    const delay = size === 'full' ? this.latency() : 0
    await p
    if (delay) await sleep(delay, signal)
    if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
    if (size === 'full' && this.failRate > 0 && Math.random() < this.failRate) {
      throw new AdapterError(
        makeError('FRAME_DECODE_FAILED', `第 ${frame} 帧解码失败（演示注入）。`, { retryable: true, actions: ['retry'] }),
      )
    }
    const entry = this.cache.get(key)
    if (!entry) return this.get(src, frame, size, signal) // evicted meanwhile → re-render
    entry.refs++
    entry.used = ++this.clock
    this.evict(size)
    return entry.url
  }

  release(url: string): void {
    const key = this.byUrl.get(url)
    if (!key) return
    const e = this.cache.get(key)
    if (e && e.refs > 0) e.refs--
  }

  private evict(size: 'thumb' | 'full') {
    const entries = [...this.cache.entries()].filter(([, e]) => e.size === size)
    if (entries.length <= CAPACITY[size]) return
    const removable = entries.filter(([, e]) => e.refs === 0).sort((a, b) => a[1].used - b[1].used)
    let over = entries.length - CAPACITY[size]
    for (const [key, e] of removable) {
      if (over-- <= 0) break
      URL.revokeObjectURL(e.url)
      this.cache.delete(key)
      this.byUrl.delete(e.url)
    }
  }

  /** Drops everything for a source (project closed / scenario reset). */
  dispose(sourceKey?: string) {
    for (const [key, e] of [...this.cache.entries()]) {
      if (!sourceKey || key.startsWith(sourceKey + ':')) {
        URL.revokeObjectURL(e.url)
        this.cache.delete(key)
        this.byUrl.delete(e.url)
      }
    }
    for (const [k, v] of [...this.videos.entries()]) {
      if (!sourceKey || k === sourceKey) {
        v.el.removeAttribute('src')
        v.el.load()
        this.videos.delete(k)
      }
    }
  }

  private async render(src: FrameSourceDef, frame: number, size: 'thumb' | 'full'): Promise<string> {
    const w = size === 'thumb' ? 192 : Math.min(src.width, 960)
    const h = Math.round((w * src.height) / src.width)
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new AdapterError(makeError('CANVAS_UNAVAILABLE', '浏览器无法创建画布。'))
    if (src.url) {
      await this.captureFromVideo(src, frame, ctx, w, h)
    } else {
      drawPlaceholder(ctx, w, h, frame, src)
    }
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/jpeg', size === 'thumb' ? 0.72 : 0.86))
    if (!blob) throw new AdapterError(makeError('FRAME_ENCODE_FAILED', '帧图像编码失败。', { retryable: true }))
    return URL.createObjectURL(blob)
  }

  private captureFromVideo(src: FrameSourceDef, frame: number, ctx: CanvasRenderingContext2D, w: number, h: number) {
    let slot = this.videos.get(src.key)
    if (!slot) {
      const el = document.createElement('video')
      el.muted = true
      el.preload = 'auto'
      el.playsInline = true
      el.src = src.url!
      slot = { el, queue: Promise.resolve() }
      this.videos.set(src.key, slot)
    }
    const s = slot
    // one seek at a time per element (bounded concurrency)
    const job = s.queue.then(
      () =>
        new Promise<void>((resolve, reject) => {
          const el = s.el
          const t = ((frame + 0.5) * src.rate.den) / src.rate.num
          const onError = () => {
            cleanup()
            reject(new AdapterError(makeError('PREVIEW_DECODE_FAILED', '浏览器无法解码预览媒体。', { retryable: true })))
          }
          const onSeeked = () => {
            cleanup()
            try {
              ctx.drawImage(el, 0, 0, w, h)
              resolve()
            } catch (e) {
              reject(e)
            }
          }
          const cleanup = () => {
            el.removeEventListener('seeked', onSeeked)
            el.removeEventListener('error', onError)
          }
          el.addEventListener('seeked', onSeeked)
          el.addEventListener('error', onError)
          const go = () => {
            if (Math.abs(el.currentTime - t) < 1e-4) el.currentTime = t + 1e-3
            else el.currentTime = t
          }
          if (el.readyState >= 1) go()
          else el.addEventListener('loadedmetadata', go, { once: true })
        }),
    )
    s.queue = job.catch(() => undefined)
    return job
  }
}

function drawPlaceholder(ctx: CanvasRenderingContext2D, w: number, h: number, frame: number, src: FrameSourceDef) {
  const hue = src.hueOf ? src.hueOf(frame) : (frame * 7) % 360
  const g = ctx.createLinearGradient(0, 0, w, h)
  g.addColorStop(0, `hsl(${hue} 14% 30%)`)
  g.addColorStop(1, `hsl(${(hue + 30) % 360} 10% 14%)`)
  ctx.fillStyle = g
  ctx.fillRect(0, 0, w, h)
  ctx.fillStyle = 'rgba(255,255,255,0.06)'
  for (let i = 0; i < 6; i++) ctx.fillRect(((frame * 3 + i * 53) % w) | 0, 0, 1, h)
  ctx.fillStyle = 'rgba(255,255,255,0.78)'
  const fs = Math.max(10, Math.round(h / 9))
  ctx.font = `600 ${fs}px "Segoe UI", system-ui, sans-serif`
  ctx.textAlign = 'center'
  ctx.fillText(`#${frame}`, w / 2, h / 2)
  ctx.font = `${Math.max(9, Math.round(fs * 0.55))}px "Segoe UI", system-ui, sans-serif`
  ctx.fillStyle = 'rgba(255,255,255,0.55)'
  ctx.fillText(src.label ?? '演示替代帧', w / 2, h / 2 + fs)
}

export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('aborted', 'AbortError'))
    const t = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(t)
      reject(new DOMException('aborted', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}
