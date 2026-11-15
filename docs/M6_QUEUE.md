# M6 队列、恢复与安全提交

## 设计边界

`core.queue` 不依赖 UI、FFmpeg 或 Electron。编码器通过 `QueueRunner` 接收一个冻结的 `QueueJob.snapshot`，在独立受控 worker 中报告进度；SQLite 是唯一持久状态源。队列默认一个 worker，可显式设为两个，绝不会超过两个。

任务状态是版本化字符串：

| 状态 | 含义 |
|---|---|
| `pending` | 待执行 |
| `processing` | 处理中 |
| `validating` | 校验中 |
| `committing` | 提交中 |
| `succeeded` | 所有必需产物已校验并提交 |
| `failed` | 本次执行失败，可按重试上限重试 |
| `skipped` | 用户跳过或取消尚未开始的任务 |
| `stale` | 快照改变，需要重新确认 |
| `interrupted` | 程序退出或当前片段取消；重启后必须用户确认 |

`QueueStore.mark_interrupted_for_restart()` 只把活动任务标为 `interrupted`，不会启动编码。只有 `confirm_recovery(job_ids)` 后才回到 `pending`。成功任务不重跑，失败任务通过 `retry()` 单独重试；`snapshot_hash` 使用 UTF-8、排序键的 canonical JSON SHA-256。

## SQLite 字段

`queue_jobs` 保存任务 ID、稳定 `clip_id`、完整快照与哈希、状态、阶段、进度、尝试次数、临时/最终目录、源身份、worker PID、错误码、事务 ID、结果摘要及用户确认标志。数据库启用 WAL 和外键约束，独立连接用于每次写入，适合 UI 与 worker 并发访问。

## 安全提交

`core.commit.CommitTransaction` 要求待提交文件位于事务私有目录，拒绝 `.partial`、路径逃逸、重复目标、哈希/大小不匹配和源身份变化。它先写入 fsync 的事务日志，再将旧文件移至同盘 backup，最后发布所有新版文件；任何锁定、空间不足、源变化或异常都会回滚到完整旧版并保存日志。多文件提交不宣称文件系统原子替换，恢复以 `recover_transaction()` 的日志为准。

## 自动化证据

```text
py -3 -m pytest -q tests/queue tests/commit
8 passed
```

测试覆盖快照稳定性、恢复需确认、状态非法跳转、重试上限、暂停/恢复、取消不计成功、旧版备份、半成品拒绝和源文件变化拒绝。真实卷级 ENOSPC、ACL 和外部断电矩阵仍由最终 Windows 环境单独标记 BLOCKED。
