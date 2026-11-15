# V1.0 问题与证据登记

| ID | 严重度 | 状态 | 问题 | 负责人 |
|---|---|---|---|---|
| M1-NEG-DISPLAY-PTS | P1 | BLOCKED | 尚无真实负显示 PTS 样片 | A |
| M1-ENOSPC | P1 | BLOCKED | 尚无隔离卷级空间不足环境 | A/D |
| M1-ACL | P1 | BLOCKED | 尚未完成真实 Windows ACL 拒绝矩阵 | A/D |
| M1-KILL-MATRIX | P1 | BLOCKED | 尚未完成外部强杀长时 FFprobe/FFmpeg 矩阵 | A/D |
| M1-LICENSE | P1 | OPEN | GPL FFmpeg 再分发清单需绑定候选包 | 主控/D |
| M2-REAL-SAMPLES | P1 | BLOCKED | 实拍婚礼样片和人工切点对照待取得，不能宣称召回率达标 | A/主控 |
| M5-DEVICE | P1 | BLOCKED | Live Photo iPhone 真机兼容性必须外部验证 | C/主控 |
| M7-NSIS-NETWORK | P1 | RESOLVED | 本轮已成功下载并生成 NSIS 候选；安装/卸载和签名仍需目标 Windows 外部验收 | 主控/D |
| R-ENCODE-SOURCE-COLLISION | P0 | RESOLVED | `encode_segment()` 现在在编码前拒绝输出路径与源文件相同或同物理文件，并有 SHA-256 回归测试 | 主控/R |
| R-COMMIT-JOURNAL-WINDOW | P1 | RESOLVED | 提交前先写入完整 `committing` 文件计划，恢复测试覆盖备份已移动/目标缺失场景 | 主控/R |
| R-MULTI-DEFAULT-VIDEO | P1 | RESOLVED | 多个默认非附图视频流返回 `AMBIGUOUS_VIDEO_STREAM`，不再静默选择最低索引 | 主控/R |
| R-PREVIEW-PTS | P1 | RESOLVED | 预览改为 `-copyts` + PTS 精确 `select`，并与独立 FFmpeg 输出逐字节核对 | 主控/R |
| R-AUDIO-PROBE-CANCEL | P1 | RESOLVED | 音频包探测使用后台 `communicate` 排水并响应取消/超时，避免 Windows pipe 堵塞 | 主控/R |
| R-STILL-TIME | P1 | RESOLVED | still-image-time 必须在 MOV 时长内且对齐显示帧时间戳；999 秒回归测试拒绝 | 主控/R |
| R-QUEUE-RECOVERY-IPC | P1 | RESOLVED | 增加 `confirm_recovery` IPC/UI；恢复事务后才回到 pending，不自动启动 | 主控/R |
| R-QUEUE-DUPLICATE | P1 | RESOLVED | `start_export` 按不可变快照哈希去重，重复点击复用原任务 | 主控/R |
