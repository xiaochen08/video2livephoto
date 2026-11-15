# 复审后功能补强

R 复审绑定的 `589c417` 之后，功能分支继续完成了以下源码补强；这些变更没有重新打包，需在后续候选包刷新时一并带入：

- `5e71b2a`：M1 负音频 PTS/edit list 与 fMP4 `-c copy` 独立 FFprobe/FFmpeg/SQLite 对照证据。
- `cfa24fb`：无默认视频流的多视频输入也返回 `AMBIGUOUS_VIDEO_STREAM`，避免静默选择最低索引。
- `d89e619`、`bdf32ee`、`0187413`：批次终态导出报告、renderer 自动轮询、失败任务显式重试。
- `6d7483b`：M5 注入并验证 `mebx` timed metadata 轨、样本 `-1`、`elst` 显示时间和非零 still-image-time；本地兼容性仍为 `local-validation-only`。

当前源码回归为 76 项 Python 测试通过。上述功能补强不改变“真实婚礼真值、iPhone Photos、Windows 安装实机和 M1 卷级故障矩阵仍需外部证据”的限制。

