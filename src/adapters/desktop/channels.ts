/**
 * Proposed IPC channel names. 全部为「待映射」— Codex replaces these with the existing
 * Electron preload API after reading the main project. Keep the UI-facing contract unchanged.
 */
export const CHANNELS = {
  connect: 'v2lp:app:connect',
  'projects.listRecent': 'v2lp:projects:list-recent',
  'projects.open': 'v2lp:projects:open',
  'projects.pickProjectFile': 'v2lp:projects:pick-file',
  'projects.rename': 'v2lp:projects:rename',
  'projects.removeRecent': 'v2lp:projects:remove-recent',
  'projects.save': 'v2lp:projects:save',
  'projects.relocateSource': 'v2lp:projects:relocate-source',
  'media.pickVideo': 'v2lp:media:pick-video',
  'media.probe': 'v2lp:media:probe',
  'analysis.start': 'v2lp:analysis:start',
  'analysis.cancel': 'v2lp:analysis:cancel',
  'analysis.event': 'v2lp:analysis:event',
  'analysis.reanalyze': 'v2lp:analysis:reanalyze',
  'preview.getSource': 'v2lp:preview:source',
  'preview.getFrame': 'v2lp:preview:frame',
  'preview.releaseFrame': 'v2lp:preview:release',
  'timeline.apply': 'v2lp:timeline:apply',
  'timeline.undo': 'v2lp:timeline:undo',
  'timeline.redo': 'v2lp:timeline:redo',
  'export.preflight': 'v2lp:export:preflight',
  'export.createBatch': 'v2lp:export:create-batch',
  'tasks.event': 'v2lp:tasks:event',
  'tasks.subscribe': 'v2lp:tasks:subscribe',
  'tasks.unsubscribe': 'v2lp:tasks:unsubscribe',
  'tasks.getBatch': 'v2lp:tasks:get-batch',
  'tasks.listBatches': 'v2lp:tasks:list-batches',
  'tasks.pauseQueue': 'v2lp:tasks:pause',
  'tasks.resumeQueue': 'v2lp:tasks:resume',
  'tasks.cancelJob': 'v2lp:tasks:cancel-job',
  'tasks.stopBatch': 'v2lp:tasks:stop',
  'tasks.retryFailed': 'v2lp:tasks:retry-failed',
  'recovery.inspect': 'v2lp:recovery:inspect',
  'recovery.progress': 'v2lp:recovery:progress',
  'recovery.continueRemaining': 'v2lp:recovery:continue',
  'recovery.dismiss': 'v2lp:recovery:dismiss',
  'files.openArtifact': 'v2lp:files:open-artifact',
  'files.revealOutput': 'v2lp:files:reveal',
  'files.readReport': 'v2lp:files:read-report',
  'files.pickOutputDir': 'v2lp:files:pick-output-dir',
  'settings.get': 'v2lp:settings:get',
  'settings.update': 'v2lp:settings:update',
  'settings.cacheInfo': 'v2lp:settings:cache-info',
  'settings.clearCache': 'v2lp:settings:clear-cache',
  'diagnostics.info': 'v2lp:diagnostics:info',
  'diagnostics.logs': 'v2lp:diagnostics:logs',
  'diagnostics.exportBundle': 'v2lp:diagnostics:export',
  'app.closeRequested': 'v2lp:app:close-requested',
  'app.quit': 'v2lp:app:quit',
} as const

export type ChannelKey = keyof typeof CHANNELS

/**
 * Shape expected from the Electron preload (contextBridge). Limited, typed operations only:
 * no arbitrary command execution and no arbitrary file reads are exposed to the renderer.
 */
export interface V2LPBridge {
  invoke(channel: string, payload?: unknown): Promise<unknown>
  on(channel: string, listener: (payload: unknown) => void): () => void
}

declare global {
  interface Window {
    v2lpBridge?: V2LPBridge
  }
}
