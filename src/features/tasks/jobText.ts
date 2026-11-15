import { STAGE_LABEL } from '@/domain/jobStates'
import type { Artifact, Job } from '@/domain/types'

/** Human text for the progress basis; never invents a percentage when the basis is unknown. */
export function progressText(job: Job): string {
  const p = job.progress
  if (job.stage === 'queued') return '等待领取'
  if (!p) return STAGE_LABEL[job.stage]
  if (p.kind === 'frames') return `${STAGE_LABEL[job.stage]} ${p.done.toLocaleString()} / ${p.total.toLocaleString()} 帧`
  if (p.kind === 'artifacts') return `${STAGE_LABEL[job.stage]} ${p.done} / ${p.total} 个产物`
  return `${STAGE_LABEL[job.stage]}：${p.note}`
}

export function progressRatio(job: Job): number | null {
  const p = job.progress
  if (!p || p.kind === 'unknown') return null
  return p.total ? p.done / p.total : null
}

export function attemptText(job: Job): string | null {
  const n = job.attempts.length
  if (!n) return null
  const cur = job.attempts[n - 1]
  const fellBack = job.attempts.some((a) => a.encoder === 'gpu' && a.result === 'failed') && cur.encoder === 'cpu'
  return `第 ${cur.n} 次尝试 · ${cur.encoder.toUpperCase()}${fellBack ? '（GPU 失败已回退）' : ''}`
}

export const ARTIFACT_STATUS: Record<Artifact['status'], { label: string; tone: 'muted' | 'accent' | 'success' | 'danger' | 'warning' }> = {
  pending: { label: '未生成', tone: 'muted' },
  writing: { label: '生成中', tone: 'accent' },
  verified: { label: '已校验', tone: 'accent' },
  committed: { label: '已提交', tone: 'success' },
  failed: { label: '失败', tone: 'danger' },
  missing: { label: '缺失', tone: 'warning' },
}
