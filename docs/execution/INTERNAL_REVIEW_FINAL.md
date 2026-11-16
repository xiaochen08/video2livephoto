# V1.0 独立总审复审报告

审查提交：589c41750f7c3ac3c7216c22dd3632b7638ef318

审查对象：E:\LIVE\_audit\video2livephoto-v1-integration 当前固定集成工作树，工作区干净。原始 main、M0 审计克隆和远端未操作。

## 结论

代码层首轮 P0/P1 已修复并通过针对性回归；本复审未发现新的已确认 P0/P1 功能缺陷。结论为 **CONDITIONAL PASS / 外部交付仍 BLOCKED**。

条件通过只覆盖本次复审实际运行的源码和测试。V1.0 仍不能宣称完整产品验收，因为真实婚礼识别真值、真实复杂素材、Apple timed metadata/iPhone、M1 卷级故障矩阵、目标 Windows 安装/卸载和全流程界面证据尚未形成完整证据。

## 自动化检查

| 检查 | 命令 | 结果 |
|---|---|---|
| Python 全量回归 | py -3 -m pytest -q | PASS，71 passed in 15.31s |
| 关键复测 | 7 个源保护/事务/多流/取消/恢复/并发 gate 测试 | PASS，7 passed in 1.05s |
| Ruff | py -3 -m ruff check core desktop tests | PASS |
| Python 编译 | py -3 -m compileall -q core desktop tests | PASS |
| Electron/Vite/IPC | npm test | PASS，Vite build、M3 IPC selftest PASS m3-python |
| TypeScript | npx tsc --noEmit | PASS |
| npm 审计 | npm audit --audit-level=high | FAIL/OPEN，仍有 13 项漏洞（3 moderate、9 high、1 critical） |
| Runtime 侧车 | 直接运行 runtime/desktop-ipc-server.exe，发送 m3.ipc.v1 ping | PASS，返回 m3-python |
| 打包环境 | py -3 -m packaging.build_candidate inspect --project . | PASS，runtime sidecar 和 FFmpeg/FFprobe 均存在 |

## 首轮问题修复复核

### 源文件覆盖保护

core/media/encode.py 现调用 paths_refer_same_file()，同路径/同物理文件返回 PATH_CONFLICT。新增测试 test_encode_rejects_source_as_output_and_preserves_source 通过，源 SHA 未变化。

### 事务崩溃窗口

core/commit/transaction.py 先写入完整 committing journal 和 backup 映射，再移动旧文件。新增 test_recovery_restores_backup_from_committing_journal 通过。额外手工模拟旧文件已移入 backup、进程在发布前退出，recover_transaction() 返回 rolled_back，旧文件恢复，backup 消失。

### 多默认视频流

core/media/probe.py 对多个 default 非附图视频流返回 AMBIGUOUS_VIDEO_STREAM。真实构造的双 default 视频样片测试通过；attached_pic 流仍排除在主视频选择之外。

### 精确预览 PTS

desktop/service.py 改为 -copyts、指定视频流和 PTS select。新增 exact display PTS 测试通过。另用 F:\M1_samples\fmp4_av_1s.mp4 的第 0、1、10、29 帧独立解码核对，预览与目标帧像素差仅来自 JPEG 编码，未出现跳到相邻帧的证据。

### 音频包探测取消与大输出

core/media/normalize.py 使用后台 communicate 持续排水，并在取消/超时时终止子进程。预取消测试通过。额外构造 120 秒 AAC（约 1,065,457 字节、5,626 个音频包）运行 _read_audio_packets()，0.172 秒完成，没有 Windows pipe 堵塞。

### Live Photo still-image-time

非法 999 秒测试返回 STILL_IMAGE_TIME_OUT_OF_RANGE；实现还要求有限非负值并对齐 MOV 显示帧时间戳。正常 LIVP 内部资源 UUID、哈希和本地解码测试通过。timed_metadata_track 仍固定为 false，属于明确 BLOCKED，不得描述为完整 Apple Live Photo 或 iPhone 兼容通过。

### 队列恢复、去重和并发

- confirm_recovery IPC/UI 已接入，重启后的 interrupted 任务需要用户确认后才回到 pending。
- 重复 start_export 按不可变快照哈希复用既有任务。
- QueueRunner 先以一个 worker 运行；成功并通过容量 gate 后才可升至两个，失败/取消不会触发升级。新增成功/失败回归均通过。
- 当前容量 gate 以逻辑 CPU 和磁盘可用空间为初始保守条件，未形成长期吞吐量实测曲线。

## 当前仍 BLOCKED / OPEN

| 项目 | 状态 | 影响 |
|---|---|---|
| M2 真实婚礼样片与人工真值、召回率 ≥95% | BLOCKED | 合成样片不能代表实拍检测精度 |
| M4 4K/长短混合真实婚礼、音画同步和画质并排核对 | BLOCKED | 不能把合成编码测试推广到复杂素材 |
| M5 Apple timed metadata 轨、iPhone 真机和社交平台 | BLOCKED | 本地 UUID/哈希/解码不等于 Live Photo 设备兼容 |
| M1 负显示 PTS、真实 ENOSPC、ACL、外部强杀矩阵 | BLOCKED | 仍沿用 M1 报告中的诚实限制 |
| M7 NSIS 安装器、安装/卸载、Windows 11 离线实机 | BLOCKED | NSIS 候选已生成并有 SHA，但未在目标 Windows 实机完成安装、卸载和离线启动矩阵 |
| npm 依赖安全审计 | OPEN | 当前锁定 Electron/electron-builder 依赖存在高危/严重 advisories，需在正式发布前处理或签署风险接受 |
| 候选包与最终 SHA 绑定 | PASS（候选产物）/BLOCKED（实机） | 已生成 delivery/v1.0/Video2LivePhoto-1.0.0-final-candidate-win-unpacked.zip，SHA-256 为 B9470022CB68021F6634B63393DCCA75D066B25A06FF533397769B5BF83764CE；NSIS 安装器 delivery/v1.0/nsis-attempt/Video2LivePhoto Setup 1.0.0-candidate.exe，SHA-256 为 AEE9047007C424EEB14238FADECF66248DEDE9ED64642FE3650F93016D4B04E1；sidecar 为 2E8074C661DA460EB4DCF0E492A2FBFC02B1B3DEF5E3F8C7D1EA0AF366929668，FFmpeg/FFprobe 与冻结 SHA 一致。安装/卸载和目标 Windows 实机仍待外部验收 |
| 实际界面证据 | BLOCKED | 现有证据文件名为 m3-empty-import-screen.png，未覆盖导入、检测、编辑、导出、暂停/恢复全流程截图或录屏 |

## 外部交付判定

源码、自动化测试和本地候选产物：**CONDITIONAL PASS**。

产品完整性与正式发布：**BLOCKED**。候选 ZIP/NSIS 已按 589c417 重新生成并有指纹，但仍需目标 Windows 实机安装/卸载、离线启动和全流程界面验收；同时保持上述真实素材、设备和 M1 故障矩阵限制。当前不应把候选产物描述为 V1.0 已发布。

