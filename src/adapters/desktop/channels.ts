/**
 * Renderer-facing names mapped to the existing M3 JSONL methods and preload
 * event topics. The Electron main process still enforces its request allowlist.
 */
export const CHANNELS = {
  connect: 'connect',
  'projects.listRecent': 'projects.listRecent',
  'projects.open': 'projects.open',
  'projects.pickProjectFile': 'projects.pickProjectFile',
  'projects.rename': 'projects.rename',
  'projects.removeRecent': 'projects.removeRecent',
  'projects.save': 'projects.save',
  'projects.relocateSource': 'projects.relocateSource',
  'media.pickVideo': 'media.pickVideo',
  'media.probe': 'media.probe',
  'analysis.start': 'analysis.start',
  'analysis.cancel': 'analysis.cancel',
  'analysis.event': 'v2lp:analysis:event',
  'analysis.reanalyze': 'analysis.reanalyze',
  'preview.getSource': 'preview.getSource',
  'preview.getFrame': 'preview.getFrame',
  'preview.releaseFrame': 'preview.releaseFrame',
  'timeline.apply': 'timeline.apply',
  'timeline.undo': 'timeline.undo',
  'timeline.redo': 'timeline.redo',
  'export.preflight': 'export.preflight',
  'export.createBatch': 'export.createBatch',
  'tasks.event': 'v2lp:tasks:event',
  'tasks.subscribe': 'tasks.subscribe',
  'tasks.unsubscribe': 'tasks.unsubscribe',
  'tasks.getBatch': 'tasks.getBatch',
  'tasks.listBatches': 'tasks.listBatches',
  'tasks.pauseQueue': 'tasks.pauseQueue',
  'tasks.resumeQueue': 'tasks.resumeQueue',
  'tasks.cancelJob': 'tasks.cancelJob',
  'tasks.stopBatch': 'tasks.stopBatch',
  'tasks.retryFailed': 'tasks.retryFailed',
  'recovery.inspect': 'recovery.inspect',
  'recovery.progress': 'v2lp:recovery:progress',
  'recovery.continueRemaining': 'recovery.continueRemaining',
  'recovery.dismiss': 'recovery.dismiss',
  'files.openArtifact': 'files.openArtifact',
  'files.revealOutput': 'files.revealOutput',
  'files.readReport': 'files.readReport',
  'files.pickOutputDir': 'files.pickOutputDir',
  'settings.get': 'settings.get',
  'settings.update': 'settings.update',
  'settings.cacheInfo': 'settings.cacheInfo',
  'settings.clearCache': 'settings.clearCache',
  'diagnostics.info': 'diagnostics.info',
  'diagnostics.logs': 'diagnostics.logs',
  'diagnostics.exportBundle': 'diagnostics.exportBundle',
  'app.closeRequested': 'v2lp:app:close-requested',
  'app.quit': 'app.quit',
} as const

export type ChannelKey = keyof typeof CHANNELS

/**
 * Shape expected from the Electron preload (contextBridge). Limited, typed
 * operations only: no arbitrary command execution or file reads are exposed.
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
