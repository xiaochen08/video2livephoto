# Desktop contract mapping — 2026-11-15

The TXT attachment is treated as this run's execution constraint. Its proposed
`DesktopAdapter` and `CHANNELS` names were checked against the existing M3
JSONL bridge; they were not treated as an existing backend API.

| Renderer operation | Actual route | Status |
|---|---|---|
| connect / ping | Electron `m3:request` → Python `connect` / `ping` | Connected; connection explicitly reports `mode: desktop`. |
| Recent projects / open / save / source relocation | `projects.listRecent`, `projects.open`, `projects.save`, `projects.relocateSource` | Connected to SQLite project service. Recent metadata is process-memory only. |
| Pick video / drag and drop | Electron native dialog; preload `webUtils.getPathForFile`; `media.probe` | Connected; media path is validated before ffprobe/analysis and ambiguous streams are returned for user choice. |
| Analysis start / result / cancel | One `analysis.start`, then `analysis.result`; `v2lp:analysis:event`; `analysis.cancel` | Connected; selected video stream is passed into probe/index/detection, duplicate starts deduplicate by request id, and stale epochs cannot replace the active project. Cancellation is cooperative once an analysis id exists. |
| Exact frame preview | `preview.getFrame` → `M3ProjectService.preview_frame` | Connected; selected video stream and indexed PTS are used. |
| Source playback | `preview.getSource` | Partial; returns `url: null` until a secure Electron media protocol is registered. |
| Timeline edits | `timeline.apply` → `_contract_edit` → M3 service | Connected; `set_clip_bounds` makes slide/reset a single atomic revision and undo step. |
| Drag cancellation | Vue `pointercancel`, `lostpointercapture`, Escape, window blur, visibility change | Connected; cancelled gestures discard tentative values without submitting an edit. |
| Export preflight / batch | `export.preflight`, `export.createBatch` → SQLite queue | Connected; immutable snapshots, idempotency and output-path reporting are wired. Unknown color metadata remains a safety failure for the Rec.709 path. |
| Task subscription / pause / resume / cancel / retry | `tasks.*`, `v2lp:tasks:event`, queue watcher | Connected for the active process; batch metadata and event cursors are not durable across a renderer/backend restart. |
| Recovery inspection / continuation | `recovery.inspect`, `recovery.continueRemaining`, `recovery.dismiss` | Connected to interrupted SQLite jobs; progress is filtered by project. |
| Artifact open / reveal / output directory | `files.openArtifact`, `files.revealOutput`; native preload directory dialog for `files.pickOutputDir` | Artifact open/reveal remain unsupported in Python; output-directory picking is connected through Electron's native directory dialog. |
| Settings / cache / diagnostics | `settings.get/update/cacheInfo`; `settings.clearCache`; `diagnostics.*` | Read/update and log listing are connected. Cache clearing and diagnostics bundle export are intentionally unsupported until safe enumeration/log-directory plumbing exists. |

`src/adapters/desktop/channels.ts` now contains the mapped method/event names;
`DesktopAdapter.ts` calls the typed `window.m3` bridge directly. The preload
and Electron main process keep an allowlist and sender validation, while the
Python side validates media and project paths before opening them.
