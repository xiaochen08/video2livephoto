# Video2LivePhoto 本地日志

Video2LivePhoto 使用应用级结构化日志记录 Electron 主进程和 Python 媒体服务的运行事件。它不是 Windows Event Viewer，也不上传云端。

## 文件位置

打包应用使用 Electron 的 `app.getPath("logs")`，Windows 默认位于 Electron `userData` 目录下（通常是 `%APPDATA%\Video2LivePhoto`，实际路径以运行时返回值为准）。Python sidecar 从 Electron 接收同一个目录和 `session_id`，写入同目录的两个文件：

- `electron.jsonl`：窗口生命周期、Python 子进程、IPC 请求超时/失败、渲染进程退出。
- `python.jsonl`：IPC 请求、项目导入/打开、队列阶段、导出恢复和工作线程异常。

开发或测试时可以设置 `VIDEO2LIVEPHOTO_LOG_DIR` 覆盖目录。日志默认按单文件 10 MiB 轮转，保留 5 个备份；两个进程不共享同一个轮转文件，避免并发轮转损坏。

## 事件格式

每行都是一个 JSON 对象，`schema_version` 为 `video2livephoto.log.v1`。常用字段包括：

- `timestamp`：UTC ISO-8601 时间。
- `session_id`：一次 Electron 启动及其 Python sidecar 的关联标识。
- `request_id`：一次 renderer → Electron → Python 请求的标识。
- `job_id`、`project_id`、`clip_id`：队列和媒体对象的关联标识。
- `event`、`level`、`duration_ms`、`error_code`、`exception`：事件和故障信息。
- `fields`：经过脱敏的事件字段。

日志系统严禁写入完整媒体路径和凭据。路径保留文件名与稳定哈希，token、密码、cookie、密钥等字段写为 `<redacted>`；较长文本和异常栈会截断。stdout 始终保留给 JSONL IPC，Python 日志只写文件或 stderr 降级输出。

## 诊断方式

按 `session_id` 合并两个文件，再按 `request_id` 或 `job_id` 追踪一次导入、预览或导出流程。日志写入失败不会阻塞媒体服务：Python 会降级到 stderr，Electron 会在 stderr 输出降级提示。日志轮转失败也不会影响导出事务和 SQLite 队列状态。

当前日志记录的是应用运行链路和错误证据；`transaction.json`、队列 SQLite 和导出报告仍是各自的恢复/结果数据源，不应当被当作系统日志替代。

开发启动默认使用仓库内的 Python 源码 sidecar，以便日志实现可直接验证；打包启动才使用 `runtime/desktop-ipc-server.exe`。重新生成候选安装包前，需要重新构建该 runtime，才能把 Python 日志代码带入安装包。
