import type { AppError, ErrorActionKind } from './types'

export class AdapterError extends Error {
  constructor(public readonly error: AppError) {
    super(error.message)
  }
}

export function toAppError(e: unknown, fallback: Partial<AppError> = {}): AppError {
  if (e instanceof AdapterError) return e.error
  if (e && typeof e === 'object' && 'code' in e && 'message' in e) {
    // already an AppError-shaped object: keep every field (actions, preserved, scope …)
    const o = e as Partial<AppError> & { code: string; message: string }
    return makeError(o.code, o.message, { ...fallback, ...o, scope: { ...fallback.scope, ...o.scope } })
  }
  if (e instanceof DOMException && e.name === 'AbortError') return makeError('ABORTED', '操作已取消。', fallback)
  return makeError('UNKNOWN', e instanceof Error ? e.message : String(e), fallback)
}

export function makeError(code: string, message: string, extra: Partial<AppError> = {}): AppError {
  return {
    code,
    message,
    scope: extra.scope ?? {},
    preserved: extra.preserved ?? null,
    actions: extra.actions ?? [],
    detail: extra.detail ?? null,
    retryable: extra.retryable ?? false,
  }
}

export const ACTION_LABEL: Record<ErrorActionKind, string> = {
  retry: '重试',
  relocate_source: '重新定位源视频',
  choose_output_dir: '更换保存位置',
  open_output_dir: '打开输出目录',
  copy_error: '复制错误信息',
  open_diagnostics: '查看诊断',
  reanalyze: '重新分析',
  retry_save: '重试保存',
  retry_job: '重试该片段',
  check_files: '重新检查文件',
  close_other_program: '关闭占用程序后重试',
}

export function isAbort(e: unknown): boolean {
  return (e instanceof DOMException && e.name === 'AbortError') || (e instanceof AdapterError && e.error.code === 'ABORTED')
}

export function errorToClipboardText(err: AppError, context: string): string {
  return [
    `[Video2LivePhoto] ${context}`,
    `错误码: ${err.code}`,
    `说明: ${err.message}`,
    err.scope.project_id ? `项目: ${err.scope.project_id}` : null,
    err.scope.clip_id ? `片段: ${err.scope.clip_id}` : null,
    err.scope.job_id ? `任务: ${err.scope.job_id}` : null,
    err.scope.stage ? `阶段: ${err.scope.stage}` : null,
    err.preserved ? `已保留: ${err.preserved}` : null,
    err.detail ? `详情: ${err.detail}` : null,
  ]
    .filter(Boolean)
    .join('\n')
}
