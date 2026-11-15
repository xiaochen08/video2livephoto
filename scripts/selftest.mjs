import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { SystemLogger } from "../electron/logger.cjs";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const command = process.env.VIDEO2LIVEPHOTO_PYTHON || (process.platform === "win32" ? "C:\\Windows\\py.exe" : "python3");
const args = command === "py" || command.toLowerCase().endsWith("py.exe") ? ["-3", "-u", "-m", "desktop.ipc_server"] : ["-u", "-m", "desktop.ipc_server"];
const pythonLogDir = mkdtempSync(resolve(tmpdir(), "video2livephoto-python-log-selftest-"));
process.on("exit", () => { try { rmSync(pythonLogDir, { recursive: true, force: true }); } catch (_) { /* best effort */ } });
const worker = spawn(command, args, { cwd: root, env: { ...process.env, PYTHONPATH: root, VIDEO2LIVEPHOTO_LOG_DIR: pythonLogDir, VIDEO2LIVEPHOTO_SESSION_ID: "selftest-session" }, windowsHide: true });
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
if (worker.exitCode === null) await new Promise((resolveClose) => worker.once("close", resolveClose));
if (!result.ok || result.protocol !== "m3.ipc.v1") throw new Error(`IPC selftest failed: ${JSON.stringify(result)}`);
if (!existsSync(resolve(root, "dist/renderer/index.html"))) throw new Error("renderer build output is missing");
console.log("M3 IPC selftest PASS", result.service);
const pythonLogPath = resolve(pythonLogDir, "python.jsonl");
if (!existsSync(pythonLogPath)) throw new Error("python structured log output is missing");
const pythonRecords = readFileSync(pythonLogPath, "utf8").trim().split("\n").map((line) => JSON.parse(line));
if (!pythonRecords.some((record) => record.event === "ipc.request.start" && record.request_id === "selftest" && record.session_id === "selftest-session")) throw new Error("python structured log correlation failed");
rmSync(pythonLogDir, { recursive: true, force: true });

const logDir = mkdtempSync(resolve(tmpdir(), "video2livephoto-log-selftest-"));
try {
  const logger = new SystemLogger({ logDir, sessionId: "selftest-session", fileName: "electron.jsonl" });
  logger.info("selftest.event", { source_path: "E:\\private\\sample.mp4", token: "secret" });
  const record = JSON.parse(readFileSync(resolve(logDir, "electron.jsonl"), "utf8").trim());
  if (record.schema_version !== "video2livephoto.log.v1" || record.session_id !== "selftest-session") throw new Error("structured logger schema failed");
  if (record.fields.token !== "<redacted>" || String(record.fields.source_path).includes("E:\\private")) throw new Error("structured logger redaction failed");
  const rotating = new SystemLogger({ logDir, sessionId: "selftest-session", fileName: "rotation.jsonl", maxBytes: 250, backupCount: 2 });
  for (let index = 0; index < 20; index += 1) rotating.info("selftest.rotation", { index, payload: "x".repeat(80) });
  if (!existsSync(resolve(logDir, "rotation.jsonl.1"))) throw new Error("structured logger rotation failed");
  console.log("System logger selftest PASS", record.component);
} finally {
  rmSync(logDir, { recursive: true, force: true });
}
