const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const { existsSync } = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");
const { SystemLogger } = require("./logger.cjs");

class PythonBridge {
  constructor(logger) {
    this.pending = new Map();
    this.eventHandlers = new Set();
    this.sequence = 0;
    this.process = null;
    this.logger = logger;
  }

  start() {
    const root = path.resolve(__dirname, "..");
    const bundled = path.join(process.resourcesPath, "runtime", "desktop-ipc-server.exe");
    const useBundled = app.isPackaged || process.env.VIDEO2LIVEPHOTO_USE_BUNDLED === "1";
    const command = useBundled && existsSync(bundled)
      ? bundled
      : process.env.VIDEO2LIVEPHOTO_PYTHON || (process.platform === "win32" ? "C:\\Windows\\py.exe" : "python3");
    const args = useBundled && existsSync(bundled)
      ? []
      : command === "py" || command.toLowerCase().endsWith("py.exe")
        ? ["-3", "-u", "-m", "desktop.ipc_server"]
        : ["-u", "-m", "desktop.ipc_server"];
    this.process = spawn(command, args, {
      cwd: root,
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONPATH: root,
        VIDEO2LIVEPHOTO_LOG_DIR: this.logger?.logDir,
        VIDEO2LIVEPHOTO_SESSION_ID: this.logger?.sessionId,
        VIDEO2LIVEPHOTO_FFMPEG_DIR: existsSync(bundled)
          ? path.join(process.resourcesPath, "runtime", "ffmpeg")
          : process.env.VIDEO2LIVEPHOTO_FFMPEG_DIR,
      },
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.logger?.info("python.spawn", { command_path: String(command), bundled_path: bundled, cwd_path: root });
    const lines = readline.createInterface({ input: this.process.stdout });
    lines.on("line", (line) => {
      try {
        const response = JSON.parse(line);
        if (response && typeof response.event === "string") {
          for (const handler of this.eventHandlers) handler(response);
          return;
        }
        const pending = this.pending.get(response.id);
        if (pending) {
          this.pending.delete(response.id);
          pending(response);
        }
      } catch (error) {
        this.logger?.error("ipc.response.parse_failed", { line: line.slice(-4000) }, error);
      }
    });
    this.process.stderr.on("data", (chunk) => {
      process.stderr.write(chunk);
      this.logger?.warn("python.stderr", { text: chunk.toString("utf8").slice(-4000) });
    });
    this.process.on("error", (error) => this.logger?.error("python.process_error", {}, error));
    this.process.on("exit", (code, signal) => {
      this.logger?.warn("python.exit", { code, signal });
      for (const reject of this.pending.values()) reject(new Error("Python service exited"));
      this.pending.clear();
    });
  }

  onEvent(handler) {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  request(method, params = {}) {
    if (!this.process || this.process.killed) return Promise.reject(new Error("Python service is not running"));
    const id = String(++this.sequence);
    const started = Date.now();
    this.logger?.info("ipc.request.start", { request_id: id, method, params });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        this.logger?.error("ipc.request.timeout", { request_id: id, method, duration_ms: Date.now() - started });
        reject(new Error(`IPC timeout: ${method}`));
      }, 60000);
      this.pending.set(id, (response) => {
        clearTimeout(timer);
        if (response.ok) {
          this.logger?.info("ipc.request.end", { request_id: id, method, ok: true, duration_ms: Date.now() - started });
          resolve(response);
        } else {
          const error = Object.assign(new Error(response.error?.message || "IPC error"), response.error || {});
          this.logger?.error("ipc.request.end", { request_id: id, method, ok: false, duration_ms: Date.now() - started, error_code: error.code }, error);
          reject(error);
        }
      });
      try {
        this.process.stdin.write(`${JSON.stringify({ id, protocol: "m3.ipc.v1", method, params })}\n`);
      } catch (error) {
        this.pending.delete(id);
        this.logger?.error("ipc.request.write_failed", { request_id: id, method }, error);
        reject(error);
      }
    });
  }

  stop() {
    if (this.process && !this.process.killed) {
      this.logger?.info("python.stop");
      this.process.kill();
    }
  }
}

let appLogger;
const bridge = new PythonBridge(null);

const ALLOWED_REQUEST_METHODS = new Set([
  "ping", "connect", "import", "open", "state", "frame_window", "preview_frame", "add_cut", "move_cut", "delete_cut", "merge_segments", "set_segment_audio", "set_all_audio", "mark_cut_checked", "undo", "redo", "confirm_export", "start_export", "export_status", "pause_export", "resume_export", "confirm_recovery", "cancel_export", "retry_export",
  "projects.listRecent", "projects.open", "projects.rename", "projects.removeRecent", "projects.save", "projects.relocateSource", "media.probe", "analysis.start", "analysis.result", "analysis.cancel", "analysis.reanalyze", "preview.getSource", "preview.getFrame", "preview.releaseFrame", "timeline.apply", "timeline.undo", "timeline.redo", "export.preflight", "export.createBatch", "tasks.subscribe", "tasks.unsubscribe", "tasks.getBatch", "tasks.listBatches", "tasks.pauseQueue", "tasks.resumeQueue", "tasks.cancelJob", "tasks.stopBatch", "tasks.retryFailed", "recovery.inspect", "recovery.continueRemaining", "recovery.dismiss", "files.readReport", "files.openArtifact", "files.revealOutput", "files.pickOutputDir", "settings.get", "settings.update", "settings.cacheInfo", "settings.clearCache", "diagnostics.info", "diagnostics.logs", "diagnostics.exportBundle", "app.quit",
]);

function assertRequestAllowed(event, method, params) {
  if (!BrowserWindow.fromWebContents(event.sender)) throw new Error("IPC_SENDER_INVALID");
  if (!ALLOWED_REQUEST_METHODS.has(method)) throw new Error(`IPC_METHOD_NOT_ALLOWED: ${method}`);
  if (!params || typeof params !== "object" || Array.isArray(params)) throw new Error("IPC_PARAMS_INVALID");
}

function createWindow() {
  let allowClose = false;
  const win = new BrowserWindow({
    width: 1380,
    height: 900,
    minWidth: 1100,
    minHeight: 720,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.resolve(__dirname, "../dist/renderer/index.html"));
  win.webContents.on("render-process-gone", (_event, details) => appLogger?.error("renderer.process_gone", details));
  win.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => appLogger?.error("renderer.load_failed", { errorCode, errorDescription, validatedURL }));
  win.on("closed", () => appLogger?.info("window.closed"));
  win.on("close", (event) => {
    if (allowClose) return;
    event.preventDefault();
    win.webContents.send("m3:event", { event: "v2lp:app:close-requested", payload: {} });
  });
  appLogger?.info("window.created", { width: 1380, height: 900 });
  win.__allowClose = () => { allowClose = true; };
  return win;
}

app.whenReady().then(() => {
  const sessionId = crypto.randomUUID();
  try {
    appLogger = new SystemLogger({ logDir: app.getPath("logs"), sessionId });
  } catch (error) {
    process.stderr.write(`[Video2LivePhoto logging disabled] ${error.message}\n`);
    appLogger = {
      logDir: "",
      sessionId,
      info: () => {},
      warn: () => {},
      error: (_event, _fields, err) => { if (err) process.stderr.write(`${err.stack || err}\n`); },
    };
  }
  bridge.logger = appLogger;
  appLogger.info("app.ready", { version: app.getVersion(), platform: process.platform, arch: process.arch });
  process.on("uncaughtException", (error) => appLogger.error("process.uncaught_exception", {}, error));
  process.on("unhandledRejection", (reason) => appLogger.error("process.unhandled_rejection", { reason: String(reason) }));
  bridge.onEvent((event) => {
    for (const win of BrowserWindow.getAllWindows()) {
      if (!win.isDestroyed()) win.webContents.send("m3:event", event);
    }
  });
  bridge.start();
  ipcMain.handle("m3:request", (event, method, params = {}) => {
    assertRequestAllowed(event, method, params);
    return bridge.request(method, params);
  });
  ipcMain.handle("m3:pick-file", async (event, options = {}) => {
    if (!BrowserWindow.fromWebContents(event.sender)) throw new Error("IPC_SENDER_INVALID");
    if (!options || typeof options !== "object" || Array.isArray(options)) throw new Error("PICK_FILE_OPTIONS_INVALID");
    if (options.mode && !new Set(["open", "save", "directory"]).has(options.mode)) throw new Error("PICK_FILE_MODE_INVALID");
    if (options.mode === "directory") {
      const result = await dialog.showOpenDialog({
        title: options.title || "选择文件夹",
        properties: ["openDirectory", "createDirectory"],
      });
      return result.canceled ? null : result.filePaths[0] || null;
    }
    const mode = options.mode === "save" ? "save" : "open";
    if (mode === "save") {
      const result = await dialog.showSaveDialog({
        title: options.title || "选择项目文件",
        defaultPath: options.defaultPath || "video2livephoto-project.sqlite3",
        filters: options.filters || [{ name: "SQLite 项目", extensions: ["sqlite3", "db"] }],
      });
      return result.canceled ? null : result.filePath;
    }
    const result = await dialog.showOpenDialog({
      title: options.title || "选择源视频",
      properties: ["openFile"],
      filters: options.filters || [{ name: "视频文件", extensions: ["mp4", "mov", "m4v"] }],
    });
    return result.canceled ? null : result.filePaths[0] || null;
  });
  ipcMain.handle("m3:quit", (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (!win) throw new Error("IPC_SENDER_INVALID");
    win.__allowClose?.();
    app.quit();
  });
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  appLogger?.info("app.window_all_closed");
  bridge.stop();
  if (process.platform !== "darwin") app.quit();
});
