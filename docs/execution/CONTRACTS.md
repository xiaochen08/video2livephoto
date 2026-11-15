# V1.0 共享契约记录

| 契约 | 当前来源 | 责任人 | 兼容要求 |
|---|---|---|---|
| `MediaProbeResult` / `FrameIndexReport` / `NormalizedMediaRef` | `core/protocol/media.py` | 主控 + A | 保留 M1 字段，允许向后兼容扩展 |
| 镜头段/编辑快照/导出任务/恢复状态 | `desktop/models.py`、`core/queue/store.py` | 主控 | `m3.desktop.v1`、`snapshot_hash`、用户确认恢复 |
| UI IPC | `desktop/ipc_server.py` + `electron/preload.cjs` | 主控 + B | JSONL `m3.ipc.v1`；渲染进程不直接处理媒体或覆盖源 |
| 编码/封装结果 manifest | `core/media/encode.py`、`core/livephoto/pack.py` | 主控 + C | 每个输出文件 SHA-256、配对 UUID、本地 ffprobe 校验 |
| 队列事务状态 | `core/queue/*`、`core/commit/transaction.py` | 主控 + D | SQLite 状态机、事务日志、备份恢复、用户确认后继续 |

## 已集成接口

- `detect_shots()` → `m2.detection.v1`：M3 导入默认调用，候选切点以 `CutPoint` 持久化。
- `encode_segment()` → `SegmentEncodeResult`：M4 左闭右开显示帧范围、音频开关、GPU/CPU 回退和色彩路径。
- `pack_live_photo()` → `LivePhotoPackResult`：M5 JPG/MOV/manifest 本地校验，Apple timed metadata track 保持未验证声明。
- `JsonlIpcServer.start_export` → M6 `QueueStore`/`QueueRunner`：用户确认后创建快照任务，worker 完成编码、封装和 `CommitTransaction`。
- `packaging/sidecar_entry.py` + `runtime/`：候选包内置 Python sidecar 与冻结 FFmpeg/FFprobe；runtime 为构建产物，不提交二进制到源码分支。

共享文件变更先提交提案，由主控集成；代理不得互相覆盖未提交改动。
