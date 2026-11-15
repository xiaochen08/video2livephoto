import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const command = process.env.VIDEO2LIVEPHOTO_PYTHON || (process.platform === "win32" ? "C:\\Windows\\py.exe" : "python3");
const args = command === "py" || command.toLowerCase().endsWith("py.exe") ? ["-3", "-u", "-m", "desktop.ipc_server"] : ["-u", "-m", "desktop.ipc_server"];
const worker = spawn(command, args, { cwd: root, env: { ...process.env, PYTHONPATH: root }, windowsHide: true });
let buffer = "";
const response = new Promise((resolveResponse, reject) => {
  worker.stdout.on("data", (chunk) => {
    buffer += chunk.toString("utf8");
    const newline = buffer.indexOf("\n");
    if (newline >= 0) {
      try { resolveResponse(JSON.parse(buffer.slice(0, newline))); } catch (error) { reject(error); }
      worker.kill();
    }
  });
  worker.stderr.on("data", (chunk) => process.stderr.write(chunk));
  worker.on("error", reject);
});
worker.stdin.write(JSON.stringify({ id: "selftest", protocol: "m3.ipc.v1", method: "ping", params: {}}) + "\n");
const result = await response;
if (!result.ok || result.protocol !== "m3.ipc.v1") throw new Error(`IPC selftest failed: ${JSON.stringify(result)}`);
if (!existsSync(resolve(root, "dist/renderer/index.html"))) throw new Error("renderer build output is missing");
console.log("M3 IPC selftest PASS", result.service);
