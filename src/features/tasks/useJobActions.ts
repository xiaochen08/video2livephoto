import { useApp } from '@/app/context'
import { toAppError } from '@/domain/errors'
import { jobUiState } from '@/domain/jobStates'
import type { Batch, ErrorActionKind, Job } from '@/domain/types'

/** Job-level actions shared by queue rows, results and the detail drawer. */
export function useJobActions() {
  const { tasks, ui, adapter, session } = useApp()

  function uiOf(job: Job, batch: Batch) {
    return jobUiState(job, batch, {
      outdated: session.outdated.value.has(job.clip_id) && job.stage === 'succeeded',
      recovery: !!session.project.value?.recovery_pending && batch.state === 'interrupted',
    })
  }

  async function run<T>(p: Promise<T>, ok?: string) {
    try {
      const r = await p
      if (ok && r !== null) ui.toast(ok, { timeout: 3000 })
      return r
    } catch (e) {
      ui.toast(toAppError(e).message, { tone: 'danger', timeout: 6000 })
      return null
    }
  }

  async function cancel(job: Job) {
    const r = await run(tasks.cancelJob(job.job_id))
    if (r && !r.immediate && r.wait_reason) ui.toast(`取消已请求：${r.wait_reason}`, { tone: 'warning', timeout: 6000 })
    else if (r) ui.toast(`已取消 ${job.file_stem}，临时产物已清理`, { timeout: 3000 })
  }
  const retry = (batch: Batch, job: Job) => run(tasks.retryFailed(batch.batch_id, [job.job_id]), `已重新排队 ${job.file_stem}（成功文件保持不变）`)

  async function open(job: Job, kind: 'mp4' | 'jpg' | 'mov') {
    await run(adapter.files.openArtifact(job.job_id, kind))
    if (adapter.mode === 'demo') ui.toast(`演示：已请求打开 ${job.file_stem}.${kind}（未打开真实文件）`, { timeout: 3000 })
  }
  async function reveal(job?: Job) {
    const p = session.project.value
    if (!p) return
    await run(adapter.files.revealOutput(p.project_id, job?.job_id))
    if (adapter.mode === 'demo') ui.toast('演示：已请求在资源管理器中定位（未打开真实目录）', { timeout: 3000 })
  }
  async function report(job: Job) {
    const body = await run(adapter.files.readReport(job.job_id))
    if (body) ui.dialogs.report.value = { title: `本地校验报告 · ${job.file_stem}`, body }
  }
  function onErrorAction(kind: ErrorActionKind, batch: Batch, job: Job) {
    if (kind === 'retry_job' || kind === 'retry') return retry(batch, job)
    if (kind === 'open_output_dir') return reveal(job)
    if (kind === 'close_other_program') return retry(batch, job)
    if (kind === 'choose_output_dir') {
      ui.toast('更换保存位置需要重新确认导出：失败片段将在新位置生成。', { timeout: 5000 })
      ui.dialogs.exportConfirm.value = true
    }
    if (kind === 'open_diagnostics') {
      ui.state.settingsSection = 'diagnostics'
      ui.state.route = 'settings'
    }
  }
  return { uiOf, cancel, retry, open, reveal, report, onErrorAction }
}
