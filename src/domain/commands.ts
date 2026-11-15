import type { AudioMode, ClipId, CutId } from './types'

/**
 * Edit commands sent to the timeline core (backend authoritative).
 * 待映射: command names / payloads must be matched to the existing timeline API.
 */
export type EditCommand =
  | { type: 'add_cut'; frame: number }
  | { type: 'move_cut'; cut_id: CutId; frame: number }
  | { type: 'remove_cut'; cut_id: CutId; audio_resolution?: AudioMode }
  | { type: 'merge_clips'; clip_ids: ClipId[]; audio_resolution?: AudioMode }
  | {
      type: 'set_clip_props'
      clip_ids: ClipId[]
      patch: { audio?: AudioMode; export_selected?: boolean; name?: string | null }
    }
  | { type: 'set_cover'; clip_id: ClipId; frame: number | null }
  | { type: 'regenerate_cover'; clip_id: ClipId }
  | { type: 'review_cut'; cut_id: CutId; action: 'confirm' | 'skip' }

export function commandLabel(cmd: EditCommand): string {
  switch (cmd.type) {
    case 'add_cut':
      return '添加切点'
    case 'move_cut':
      return '移动切点'
    case 'remove_cut':
      return '删除切点（合并相邻片段）'
    case 'merge_clips':
      return `合并 ${cmd.clip_ids.length} 个片段`
    case 'set_clip_props':
      if (cmd.patch.audio) return cmd.patch.audio === 'muted' ? '静音' : '恢复原声'
      if (cmd.patch.export_selected !== undefined) return cmd.patch.export_selected ? '加入导出' : '取消导出选择'
      return '重命名片段'
    case 'set_cover':
      return cmd.frame === null ? '恢复自动封面' : '选择封面'
    case 'regenerate_cover':
      return '重新生成封面'
    case 'review_cut':
      return cmd.action === 'confirm' ? '确认切点' : '跳过切点'
  }
}
