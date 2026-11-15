# Video2LivePhoto UI Fidelity and Desktop Integration Implementation Plan

> **For agentic workers:** Use the repository worktree and the adapter/backend contracts described below. Keep each change scoped and verify it before claiming completion.

**Goal:** Migrate the ZIP's current Vue 3 workflow UI into the Windows Electron renderer and connect it to the existing m3.ipc.v1 Python/FFmpeg/SQLite backend without changing the frozen visual system.

**Architecture:** The ZIP UI remains the renderer source of truth. A desktop adapter translates the existing `V2LPAdapter` shape into the typed `window.m3` bridge and the existing Python request methods; no demo adapter is allowed in desktop mode. Backend additions stay behind the Electron/Python bridge and preserve existing project, frame-index, queue, transaction, and recovery implementations. Evidence is versioned beside the branch and separates reference rendering, migrated rendering, and real Electron behavior.

**Tech Stack:** Vue 3, TypeScript, Vite, Electron 31, contextIsolation preload, Python 3 JSONL IPC, FFmpeg, SQLite, Vitest, pytest, Playwright/Chrome for fixed-viewport evidence.

---

### Task 1: Preserve the source facts and establish evidence

**Files:**
- Create: `docs/evidence/reference-20261115/*`
- Create: `docs/superpowers/plans/2026-11-15-ui-fidelity-integration.md`
- Reference only: `E:/LIVE/_audit/video2livephoto-ui-reference/*`

- [x] Record the TXT SHA-256 and confirm the actual base HEAD (`bea5a58bc512d0e40e1966018748087d06eb53ba`) differs from the older report HEAD.
- [x] Run the reference with its lockfile; use `--config.minimumReleaseAge=0` only because the lock includes the same-day `@vue/test-utils@2.6.0`, and record that environment exception.
- [x] Capture the reference home and editor at 1440×900, DPR 1, Windows Chrome, with the actual demo interaction.
- [x] Add per-state metadata and equal-viewport reference/target/overlay/diff evidence; motion recording is separately marked blocked by the local Playwright ffmpeg cache.

### Task 2: Migrate the frozen Vue renderer

**Files:**
- Modify: `src/`, `vite.config.ts`, `package.json`, `index.html`, `tsconfig.json`
- Preserve: Electron `loadFile(dist/renderer/index.html)` contract

- [x] Copy the reference `src/app`, `src/components`, `src/features`, `src/stores`, `src/domain`, `src/styles`, `src/adapters`, and `src/main.ts` as the renderer source of truth.
- [x] Set Vite `root=src`, `base=./`, and `outDir=../dist/renderer`; keep the desktop mode explicit and make `index.html` mount `#root` with an offline title and assets.
- [x] Preserve tokens, base reset, system fonts, icons, transitions, focus behavior, responsive breakpoints, reduced-motion behavior, and all normal markup. Do not replace the UI with the old single-file renderer.
- [x] Keep demo data in demo-only paths and ensure the desktop entry fails with a real connection/configuration error instead of silently using demo data.
- [x] Run typecheck and desktop build before integrating bridge changes.

### Task 3: Map the desktop adapter to the real bridge

**Files:**
- Modify: `src/adapters/desktop/DesktopAdapter.ts`, `src/adapters/desktop/channels.ts`, `src/adapters/contract.ts`, `src/domain/time.ts`, `src/features/editor/Player.vue`, `src/features/editor/TrimEditor.vue`, `src/stores/tasks.ts`
- Modify: `electron/preload.cjs`, `electron/main.cjs`

- [x] Replace proposed channels with a typed, allow-listed bridge over `m3:request` and the existing file dialogs; keep contextIsolation and reject arbitrary renderer commands or paths.
- [x] Map project/media/probe/open/save/relocate, analysis, frame preview, timeline, export, tasks, recovery, files, settings, diagnostics, and app operations to real backend methods. Mark unsupported operations as explicit errors.
- [x] Make analysis one real start request plus completion polling/subscription for that task; bind events to project/request/analysis IDs and remember cancellation before the ID is returned.
- [x] Translate indexed frame/PTS/time-base information so displayed boundaries and exact-frame requests do not assume CFR; arbitrary in-clip player scrub remains a documented limit.
- [x] Submit multi-boundary slide/restore edits atomically with one request ID and one undo unit; rollback the confirmed boundary on rejection or version conflict.
- [x] Handle pointerup, pointercancel, Esc, lost capture, blur, visibility change, and unmount as distinct paths; only a normal pointerup commits.
- [x] Filter the currently supported task/recovery events by project and request; durable sequence/attempt resync remains a documented limit.

### Task 4: Connect and verify the real desktop workflow

**Files:**
- Modify: `desktop/ipc_server.py`, `desktop/service.py`, `desktop/models.py`, `core/media/frame_index.py`, `core/queue/*` only when the real contract requires it
- Create/modify: focused tests under `tests/desktop`, `tests/media`, `tests/queue`, and renderer unit tests
- Create: `docs/evidence/migrated-20261115/*`, `docs/interface-mapping.md`, `docs/verification-20261115.md`

- [x] Preserve existing import/analyze/edit/export/validate/commit/recovery semantics and add only minimal versioned protocol fields for request IDs, cancellation, PTS mapping, event snapshots, and atomic edit transactions.
- [x] Verify the real desktop import/analysis/editor path and backend queue routes; classify export, file actions, and unexecuted manual flows explicitly in `docs/verification-20261115.md`.
- [x] Keep generated runtime databases/caches in a named audit directory outside the repository; never upload private media or alter source files.
- [x] Generate reference/target/50% overlay/diff images at the same viewport/data and classify motion recording as blocked by local tooling.

### Task 5: Independent review and completion gate

**Files:**
- Review: all changed files and evidence
- Update: `docs/verification-20261115.md`, `docs/TECH_DEBT.md` only for confirmed entries

- [x] Run the full relevant pytest suite, renderer build/selftest, typecheck, desktop build, and Electron syntax checks from the final branch.
- [x] Have an independent review inspect the final diff, interface mapping, visual evidence, and raw logs; fix the queue false-success and multi-boundary edit findings and rerun affected checks.
- [x] Record exact branch, start/end SHAs, modified files, launch command, rollback target, and every unverified boundary. Do not package, sign, publish, push, merge main, or delete worktrees.
