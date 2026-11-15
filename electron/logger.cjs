const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const MAX_BYTES = 10 * 1024 * 1024;
const BACKUP_COUNT = 5;
const PATH_KEYS = new Set(["path", "source_path", "project_path", "output_dir", "temp_dir", "file_path", "log_dir"]);
const SECRET_KEYS = new Set(["authorization", "cookie", "password", "secret", "token", "api_key", "private_key"]);
const WINDOWS_PATH_RE = /[A-Za-z]:\\[^\r\n"']+/g;

function safePath(value) {
  if (value === undefined || value === null) return value;
  const text = String(value);
  const base = path.win32.basename(text) || path.basename(text) || "<root>";
  const digest = crypto.createHash("sha256").update(text.toLowerCase(), "utf8").digest("hex").slice(0, 12);
  const drive = /^[A-Za-z]:/.test(text) ? text.slice(0, 2) : "";
  return `${drive}\\…\\${base}#${digest}`;
}

function redactText(value) {
  return String(value).replace(WINDOWS_PATH_RE, (match) => safePath(match));
}

function sanitize(value, key = "", depth = 0) {
  if (depth > 5) return "<depth-limit>";
  const normalized = String(key).toLowerCase();
  if (SECRET_KEYS.has(normalized) || [...SECRET_KEYS].some((item) => normalized.includes(item))) return "<redacted>";
  if (PATH_KEYS.has(normalized) || normalized.endsWith("_path") || normalized.endsWith("_dir")) return safePath(value);
  if (Array.isArray(value)) return value.map((item) => sanitize(item, "", depth + 1));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, sanitize(v, k, depth + 1)]));
  if (typeof value === "string") return redactText(value.length > 4000 ? `${value.slice(0, 4000)}…<truncated>` : value);
  return value;
}

class SystemLogger {
  constructor({ logDir, component = "electron", sessionId = crypto.randomUUID(), fileName = "electron.jsonl", maxBytes = MAX_BYTES, backupCount = BACKUP_COUNT } = {}) {
    this.logDir = path.resolve(logDir);
    this.component = component;
    this.sessionId = sessionId;
    this.filePath = path.join(this.logDir, fileName);
    this.maxBytes = maxBytes;
    this.backupCount = backupCount;
    this.disabled = false;
    try { fs.mkdirSync(this.logDir, { recursive: true }); } catch (error) {
      this.disabled = true;
      process.stderr.write(`[Video2LivePhoto logging degraded] ${error.message}\n`);
    }
  }

  bind(context = {}) {
    const parent = this;
    return {
      debug(event, fields) { parent.write("DEBUG", event, fields, context); },
      info(event, fields) { parent.write("INFO", event, fields, context); },
      warn(event, fields) { parent.write("WARN", event, fields, context); },
      error(event, fields, error) { parent.write("ERROR", event, fields, context, error); },
    };
  }

  debug(event, fields) { this.write("DEBUG", event, fields); }
  info(event, fields) { this.write("INFO", event, fields); }
  warn(event, fields) { this.write("WARN", event, fields); }
  error(event, fields, error) { this.write("ERROR", event, fields, {}, error); }

  rotateIfNeeded(nextBytes) {
    let stat;
    if (this.disabled) return;
    try { stat = fs.statSync(this.filePath); } catch (_) { return; }
    if (stat.size + nextBytes <= this.maxBytes) return;
    try { fs.rmSync(`${this.filePath}.${this.backupCount}`, { force: true }); } catch (_) { /* best effort */ }
    for (let index = this.backupCount - 1; index >= 1; index -= 1) {
      const from = `${this.filePath}.${index}`;
      const to = `${this.filePath}.${index + 1}`;
      if (fs.existsSync(from)) {
        try { fs.renameSync(from, to); } catch (_) { /* logging must never break the app */ }
      }
    }
    try { fs.renameSync(this.filePath, `${this.filePath}.1`); } catch (_) { /* best effort */ }
  }

  write(level, event, fields = {}, context = {}, error = undefined) {
    const payload = {
      schema_version: "video2livephoto.log.v1",
      timestamp: new Date().toISOString(),
      level,
      component: this.component,
      event,
      message: event,
      session_id: this.sessionId,
      process_id: process.pid,
      ...context,
      fields: sanitize(fields),
    };
    if (error) payload.exception = { type: error.name || "Error", message: redactText(String(error.message || error)), stack: redactText(String(error.stack || "").slice(-12000)) };
    const line = `${JSON.stringify(payload)}\n`;
    if (this.disabled) return;
    try {
      this.rotateIfNeeded(Buffer.byteLength(line, "utf8"));
      fs.appendFileSync(this.filePath, line, { encoding: "utf8" });
    } catch (loggingError) {
      process.stderr.write(`[Video2LivePhoto logging degraded] ${loggingError.message}\n`);
    }
  }
}

module.exports = { SystemLogger, sanitize, safePath };
