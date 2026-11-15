# UI fidelity and desktop integration verification — 2026-11-15

## Scope and inputs

- ZIP: `Video2LivePhoto 桌面工具设计.zip`
  - SHA-256: `F4CFA5662D9EADA3F6E30BBA2509492D0E87F459A2EECDAF397E2FDDEB3109B9`
- TXT constraint: `Video2LivePhoto_Codex_UI_像素级迁移与后端接入提示词.txt`
  - SHA-256: `69D0DD96E1E9638BBCE66D5DE734DEFF6F3B0C940E05773C6A6FA571E5239783`
- Reference source: `E:\LIVE\_audit\video2livephoto-ui-reference`
- Integration worktree: `E:\LIVE\_audit\video2livephoto-ui-fidelity`
- Base checked out from the current `codex/v1-integration` HEAD `bea5a58bc512d0e40e1966018748087d06eb53ba`; the older report SHA `8db6ffb...` was not used as the base.

The attachment's visual screenshots were treated as historical context only.
The live ZIP source was run first and became the visual baseline. The migrated
renderer reuses that source's Vue components, CSS variables, icons, layouts and
motion states; no replacement UI was designed in this run.

## Reference and visual evidence (path A)

The reference Vite app was run at 1440×900 CSS pixels, DPR 1, with the same
Chrome executable and demo data. Reference checks passed: 30 tests, typecheck,
and build. The migrated Vite renderer was captured under the same conditions.

Evidence:

- Reference home/editor: `docs/evidence/reference-20261115-home-1440x900.png`, `docs/evidence/reference-20261115-editor-1440x900.png`
- Migrated home/editor: `docs/evidence/target-20261115-home-1440x900.png`, `docs/evidence/target-20261115-editor-1440x900.png`
- 50% overlays: `docs/evidence/home-overlay-1440x900.png`, `docs/evidence/editor-overlay-1440x900.png`
- Difference images: `docs/evidence/home-diff-1440x900.png`, `docs/evidence/editor-diff-1440x900.png`
- Metrics: `docs/evidence/visual-diff-metrics-20261115.json`

The measured mean absolute channel difference was 0.015 for home and 0.256
for editor; the ratio of pixels above an 8/255 channel difference was 0.0004
and 0.0060 respectively. These numbers are evidence for the captured states,
not a proof of every responsive breakpoint.

The requested video recording was not produced. Playwright's local video
encoder cache did not contain the required ffmpeg binary; this is recorded in
`docs/evidence/motion-recording-status-20261115.txt` rather than being reported
as a completed recording.

## Real desktop verification (path B)

The development Electron app was launched in explicit desktop mode with the
native preload and a real Python/FFmpeg/SQLite sidecar. The following checks
passed:

- `window.m3` and `window.v2lpBridge` were present in the native renderer.
- `ping` returned protocol `m3.ipc.v1`, service `m3-python`.
- The no-explicit-project-path import path was reproduced and fixed: analysis
  now creates a project under the configured project directory instead of
  treating an empty path as `Path('.')`. A real Electron smoke request passed
  through `analysis.start` → `analysis.result` after the fix.
- A real local MP4 was imported through `analysis.start` → `analysis.result`
  once, with real frame indexing and shot detection. A duplicate request id
  returned the same analysis id.
- After reload, the recent project opened in the migrated editor. The editor
  showed the backend's real clip count and exact frame previews. Screenshots:
  `docs/evidence/electron-20261115-home.png` and
  `docs/evidence/electron-20261115-real-editor.png`.
- `export.preflight` returned a real pending-review warning and the queue
  accepted `export.createBatch` with an immutable snapshot.

The real export attempt did not produce files. The synthetic fixture has no
complete colour metadata, so the safety gate returned
`UNKNOWN_COLOR_METADATA` for the default Rec.709 path. The first run also
exposed a queue completion callback attempting `failed → succeeded`; the
callback now checks the persisted state before committing success, and a
regression test covers the failure path. The absence of output files is an
expected result of that failed export, not evidence of a successful export.
The sanitised request/result summary is in
`docs/evidence/electron-20261115/real-backend-log.txt`.

## Automated checks for this worktree

The final command results are recorded in
`docs/evidence/final-test-log-20261115.txt`. The checks are:

```text
py -3 -m pytest -q
npm test
npm run typecheck
npm run build:desktop
node --check electron/main.cjs
node --check electron/preload.cjs
git diff --check
```

The Python suite includes the atomic multi-boundary edit, indexed VFR PTS
detection, explicit multi-video-stream selection, monotonic undo/redo versions,
analysis request deduplication, and queue failure-state guard.

## Remaining limits

- `preview.getSource` deliberately returns no playable URL until a secure
  media protocol is implemented; exact still-frame preview is the verified
  desktop path.
- Indexed PTS values now populate clip boundaries and cut displays, and the
  backend marks VFR from sampled frame-index spacing. Arbitrary in-clip player
  scrubbing still falls back to nominal rate because the renderer does not yet
  hold a full frame→PTS lookup table.
- Recent-list and batch-event metadata are process-memory structures; the
  SQLite queue itself persists jobs and interrupted states.
- Python contract methods for rename, re-analysis, artifact open/reveal, cache
  clear, and diagnostics bundle export return explicit unsupported errors. The
  output-directory picker itself is connected through the Electron preload
  dialog.
- Full responsive breakpoint coverage, an independent Windows target-machine
  acceptance run, package/signing/install tests, and real complex user media
  remain unexecuted.
- No installer, signing, upload, push, or merge was performed. Dependency
  audit warnings inherited from the existing lockfile were not auto-upgraded.

## Rollback

Keep this feature worktree and create a separate checkout at the verified base
or at `d80cc50` (the backend-adapter checkpoint) to inspect or run the prior
implementation. Reverting the final local commits on this feature branch is
also safe; the original `codex/v1-integration` worktree, its dirty files, main,
and the M0 audit clone were not changed.
