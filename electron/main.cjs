const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { spawn } = require("node:child_process");
const { existsSync } = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

class PythonBridge {
  constructor() {
    this.pending = new Map();
    this.sequence = 0;
    this.process = null;
  }

  start() {
    const root = path.resolve(__dirname, "..");
    const bundled = path.join(process.resourcesPath, "runtime", "desktop-ipc-server.exe");
    const command = existsSync(bundled)
      ? bundled
      : process.env.VIDEO2LIVEPHOTO_PYTHON || (process.platform === "win32" ? "C:\\Windows\\py.exe" : "python3");
    const args = existsSync(bundled)
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
        VIDEO2LIVEPHOTO_FFMPEG_DIR: existsSync(bundled)
          ? path.join(process.resourcesPath, "runtime", "ffmpeg")
          : process.env.VIDEO2LIVEPHOTO_FFMPEG_DIR,
      },
      stdio: ["pipe", "pipe", "pipe"],
    });
    const lines = readline.createInterface({ input: this.process.stdout });
    lines.on("line", (line) => {
      try {
        const response = JSON.parse(line);
        const pending = this.pending.get(response.id);
        if (pending) {
          this.pending.delete(response.id);
          pending(response);
        }
      } catch (_) {
        // Malformed worker output is reported through timeout/exit below.
      }
    });
    this.process.stderr.on("data", (chunk) => process.stderr.write(chunk));
    this.process.on("exit", () => {
      for (const reject of this.pending.values()) reject(new Error("Python service exited"));
      this.pending.clear();
    });
  }

  request(method, params = {}) {
    if (!this.process || this.process.killed) return Promise.reject(new Error("Python service is not running"));
    const id = String(++this.sequence);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`IPC timeout: ${method}`));
      }, 60000);
      this.pending.set(id, (response) => {
        clearTimeout(timer);
        if (response.ok) resolve(response);
        else reject(Object.assign(new Error(response.error?.message || "IPC error"), response.error || {}));
      });
      this.process.stdin.write(`${JSON.stringify({ id, protocol: "m3.ipc.v1", method, params })}\n`);
    });
  }

  stop() {
    if (this.process && !this.process.killed) this.process.kill();
  }
}

const bridge = new PythonBridge();

function createWindow() {
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
}

app.whenReady().then(() => {
  bridge.start();
  ipcMain.handle("m3:request", (_event, method, params) => bridge.request(method, params));
  ipcMain.handle("m3:pick-file", async (_event, options = {}) => {
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
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  bridge.stop();
  if (process.platform !== "darwin") app.quit();
});
