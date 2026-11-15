import type { Tone } from '@/domain/jobStates'
import type { ProjectStatusTag } from '@/domain/types'

export const PROJECT_STATUS: Record<ProjectStatusTag, { label: string; tone: Tone; icon: string }> = {
  analyzing: { label: '分析中', tone: 'accent', icon: 'spinner' },
  needs_review: { label: '待检查', tone: 'warning', icon: 'dot' },
  ready_to_export: { label: '待导出', tone: 'neutral', icon: 'clock' },
  exporting: { label: '导出中', tone: 'accent', icon: 'spinner' },
  partial_failed: { label: '部分失败', tone: 'danger', icon: 'x' },
  exported: { label: '已导出', tone: 'success', icon: 'check' },
  recovery_pending: { label: '等待恢复', tone: 'warning', icon: 'alert' },
  source_missing: { label: '原视频已移动', tone: 'danger', icon: 'alert' },
  source_changed: { label: '原视频已变化', tone: 'danger', icon: 'alert' },
  read_failed: { label: '读取失败', tone: 'danger', icon: 'x' },
}
