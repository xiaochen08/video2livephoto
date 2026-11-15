import type { Clip } from './types'

export function padIndex(n: number, width = 3): string {
  return String(n).padStart(width, '0')
}

export function defaultClipName(displayIndex: number): string {
  return `片段 ${padIndex(displayIndex)}`
}

export function clipDisplayName(clip: Pick<Clip, 'name' | 'display_index'>): string {
  return clip.name && clip.name.trim() ? clip.name : defaultClipName(clip.display_index)
}

/** File stem: `<base>_<index>`; the stable clip_id is tracked separately in the snapshot. */
export function fileStem(base: string, displayIndex: number, width = 3): string {
  return `${sanitizeForFileName(base)}_${padIndex(displayIndex, width)}`
}

const ILLEGAL = /[<>:"/\\|?*\u0000-\u001f]/g
const RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i

export function sanitizeForFileName(input: string): string {
  let s = input.replace(ILLEGAL, '_').replace(/[. ]+$/g, '').trim()
  if (!s) s = '未命名'
  if (RESERVED.test(s)) s = `${s}_`
  return s
}

export interface NameIssue {
  level: 'error' | 'warning'
  code: string
  message: string
}

/**
 * Front-end basic checks for Windows file/dir names. The desktop backend remains the authority
 * for permissions, free space, locked files and path safety.
 */
export function checkNameBase(base: string): NameIssue[] {
  const issues: NameIssue[] = []
  if (!base.trim()) issues.push({ level: 'error', code: 'EMPTY', message: '命名不能为空。' })
  const illegal = base.match(ILLEGAL)
  if (illegal) {
    issues.push({
      level: 'error',
      code: 'ILLEGAL_CHAR',
      message: `包含 Windows 文件名不允许的字符：${[...new Set(illegal)].join(' ')}`,
    })
  }
  if (/[. ]$/.test(base)) issues.push({ level: 'error', code: 'TRAILING', message: '末尾不能是空格或句点。' })
  if (RESERVED.test(base.trim())) {
    issues.push({ level: 'error', code: 'RESERVED', message: `“${base.trim()}”是 Windows 保留名称。` })
  }
  if (/^\s|\s{2,}/.test(base)) {
    issues.push({ level: 'warning', code: 'SPACES', message: '开头或连续空格可能导致文件不易查找。' })
  }
  return issues
}

export const MAX_PATH = 260

export function checkOutputPath(dir: string, longestFile: string): NameIssue[] {
  const issues: NameIssue[] = []
  if (!dir.trim()) {
    issues.push({ level: 'error', code: 'EMPTY_DIR', message: '请选择保存位置。' })
    return issues
  }
  if (!/^[a-zA-Z]:[\\/]/.test(dir) && !dir.startsWith('\\\\')) {
    issues.push({ level: 'error', code: 'NOT_ABSOLUTE', message: '保存位置需要是完整的 Windows 路径，例如 D:\\导出。' })
  }
  const full = `${dir.replace(/[\\/]+$/, '')}\\LivePhoto\\${longestFile}`
  if (full.length >= MAX_PATH) {
    issues.push({
      level: 'warning',
      code: 'LONG_PATH',
      message: `最长输出路径 ${full.length} 个字符，超过 Windows 传统限制 ${MAX_PATH}。后端需确认长路径支持，否则请缩短目录或命名。`,
    })
  }
  return issues
}
