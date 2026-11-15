/** Keymap: single source for the handler (keyboard.ts) and the help dialog. */
export interface ShortcutDef {
  id: string
  keys: string
  label: string
  scope: '全局' | '编辑页' | '剪辑轨道' | '片段列表' | '切点检查' | '弹窗'
  note?: string
}

export const SHORTCUTS: ShortcutDef[] = [
  { id: 'open', keys: 'Ctrl+O', label: '打开项目 / 选择视频', scope: '全局' },
  { id: 'save', keys: 'Ctrl+S', label: '保存项目', scope: '全局' },
  { id: 'help', keys: '?', label: '快捷键说明', scope: '全局' },
  { id: 'esc', keys: 'Esc', label: '关闭最上层弹窗；无弹窗时清除多选', scope: '全局', note: '不会取消任何任务' },
  { id: 'undo', keys: 'Ctrl+Z', label: '撤销', scope: '编辑页' },
  { id: 'redo', keys: 'Ctrl+Shift+Z / Ctrl+Y', label: '重做', scope: '编辑页' },
  { id: 'play', keys: 'Space', label: '播放 / 暂停', scope: '编辑页' },
  { id: 'step', keys: '← / →', label: '前一帧 / 后一帧', scope: '编辑页' },
  { id: 'step10', keys: 'Shift+← / →', label: '后退 / 前进 1 秒', scope: '编辑页' },
  { id: 'clipnav', keys: '↑ / ↓', label: '上一个 / 下一个片段', scope: '编辑页' },
  { id: 'bounds', keys: 'Home / End', label: '跳到当前片段起点 / 最后一帧', scope: '编辑页' },
  { id: 'split', keys: 'C', label: '在播放头处添加切点（拆分）', scope: '编辑页' },
  { id: 'merge', keys: 'M', label: '合并所选相邻片段', scope: '编辑页' },
  { id: 'delete', keys: 'Delete', label: '删除所选切点（合并相邻片段）；选中片段时取消导出选择', scope: '编辑页', note: '画面不会被删除' },
  { id: 'nudge', keys: 'Alt+← / →', label: '所选切点前移 / 后移 1 帧', scope: '编辑页', note: '连续按键合并为一次可撤销操作' },
  { id: 'dock', keys: 'T', label: '切换底部「片段 / 剪辑轨道」', scope: '编辑页' },
  { id: 'in', keys: 'I / O', label: '把本段开头 / 结尾设到播放头', scope: '剪辑轨道' },
  { id: 'handle', keys: '← / →（把手聚焦时）', label: '开头 / 结尾把手逐帧移动，Shift 每次 10 帧', scope: '剪辑轨道' },
  { id: 'trimwheel', keys: '滚轮 / Ctrl+滚轮', label: '剪辑轨道平移 / 缩放；片段卡片栏滚轮横向滚动', scope: '剪辑轨道' },
  { id: 'esc-drag', keys: 'Esc（拖动中）', label: '取消本次拖动，回到确认位置', scope: '剪辑轨道' },
  { id: 'selectall', keys: 'Ctrl+A', label: '全选当前筛选结果', scope: '片段列表' },
  { id: 'multi', keys: 'Ctrl+点击 / Shift+点击', label: '多选 / 范围选择', scope: '片段列表' },
  { id: 'fit', keys: 'F', label: '剪辑轨道适应本段', scope: '剪辑轨道' },
  { id: 'zoom', keys: '= / -', label: '剪辑轨道放大 / 缩小', scope: '剪辑轨道' },
  { id: 'review', keys: 'R', label: '切换「编辑 / 检查切点」', scope: '编辑页' },
  { id: 'confirm', keys: 'Enter', label: '确认当前切点并前往下一处', scope: '切点检查' },
  { id: 'skip', keys: 'S', label: '暂时跳过当前切点（保持待检查）', scope: '切点检查' },
  { id: 'export', keys: 'Ctrl+E', label: '打开导出确认', scope: '编辑页' },
  { id: 'tab', keys: 'Tab / Shift+Tab', label: '在弹窗内循环焦点', scope: '弹窗' },
]
