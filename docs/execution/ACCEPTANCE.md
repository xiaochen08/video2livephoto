# V1.0 验收矩阵（初始）

| 阶段 | 目标 | 当前状态 | 证据 |
|---|---|---|---|
| M1 | 媒体基础层 | 已实现/部分 BLOCKED | `docs/M1_IMPLEMENTATION_REPORT.md`，原有证据保留，新增负 PTS/ACL/ENOSPC 等证据仍按清单区分 |
| M2 | 镜头检测与预览数据 | 已实现/真实婚礼真值 BLOCKED | `docs/M2_DETECTION_REPORT.md`，合成回归已集成 |
| M3 | 桌面导入、时间线和审核 | 已实现 | `docs/M3_DESKTOP.md`，Electron/Vue 构建、IPC、逐帧预览和审核/恢复控制 |
| M4 | 精准分段、音频、色彩、编码 | 已实现/复杂实拍待补 | `docs/M4_M5_MEDIA_EXPORT.md` |
| M5 | Live Photo 封装与校验 | 已实现/真机 BLOCKED | `docs/M4_M5_MEDIA_EXPORT.md`，timed metadata/iPhone 未宣称通过 |
| M6 | 队列、快照、恢复 | 已实现/真实断电矩阵待补 | `docs/M6_QUEUE.md`，去重、用户确认恢复、事务恢复 IPC 已接通 |
| M7 | Windows 候选打包 | 候选目录/ZIP PASS，NSIS BLOCKED | `docs/M7_PACKAGING.md`，NSIS 资源网络阻塞 |
| R | 独立总审 | 首轮 FAIL/BLOCKED；最终复审待完成 | 首轮报告 `dde99d5`；最终绑定 `282cb9a` |
