import { computed } from 'vue'
import type { FileRef } from '@/adapters/contract'
import { useApp } from '@/app/context'

/** probe → (optional) stream choice → analysis. Shared by home, drop and multi-file dialog. */
export function useImport() {
  const { home, ui } = useApp()
  const analysisBusy = computed(() => !!home.analysis.value && ['probing', 'running', 'cancelling'].includes(home.analysis.value.status))

  async function importRef(ref: FileRef) {
    if (analysisBusy.value) {
      ui.toast('已有分析任务进行中，一次处理一条成片。', { tone: 'warning' })
      return
    }
    if (home.analysis.value && ['failed', 'cancelled', 'done'].includes(home.analysis.value.status)) home.clearAnalysis()
    const probe = await home.probe(ref)
    if (!probe) return
    let streamIndex = probe.media.selected_video_stream ?? probe.media.video_streams[0]?.stream_index ?? 0
    if (probe.needs_stream_choice) {
      const chosen = await new Promise<number | null>((resolve) => {
        ui.dialogs.streamSelect.value = {
          probe,
          resolve: (idx) => {
            ui.dialogs.streamSelect.value = null
            resolve(idx)
          },
        }
      })
      if (chosen === null) return
      streamIndex = chosen
    }
    home.startAnalysis(probe, streamIndex)
  }

  return { importRef, analysisBusy }
}
