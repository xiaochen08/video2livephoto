import type { V2LPAdapter } from './contract'
import type { RunMode } from '@/app/config'

/** Single injection point. Pages never import a concrete adapter. */
export async function createAdapter(mode: RunMode): Promise<V2LPAdapter> {
  if (mode === 'desktop') {
    const { DesktopAdapter } = await import('./desktop/DesktopAdapter')
    return new DesktopAdapter()
  }
  // Build-time constant: desktop builds drop the demo adapter, fixtures and sample media entirely.
  if (import.meta.env.MODE !== 'desktop' && mode === 'demo') {
    const { DemoAdapter } = await import('./demo/DemoAdapter')
    return new DemoAdapter()
  }
  throw new Error('未指定运行模式（demo / desktop）。')
}
