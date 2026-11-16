# V1.0 独立总审报告（固定集成提交）

审查提交：f53a2f4f167f8cf070a36a26b0ff15d6f7ca7a61

审查分支：codex/v1-review

审查范围：冻结开发规格、并行执行授权、M1～M7 文档、core/、desktop/、Electron renderer/main、队列/事务、打包脚本和固定提交上的自动化测试。审查会话没有修改生产源码，也没有操作原始 main、M0 审计克隆或远端。

## 结论

结论为 FAIL / BLOCKED，不能交付外部终审。固定提交存在一个已复现的 P0 源文件覆盖缺陷，及一个已复现的 P1 事务恢复窗口缺陷。两项缺陷直接违反源文件保护和安全替换要求。另有队列恢复确认 IPC 缺失、多个默认视频流未拒绝歧义、Live Photo 时间轨未验证、真实婚礼精度和 NSIS 安装器证据缺失。

自动化基础检查通过不能覆盖上述安全问题。

## 已执行检查

| 检查 | 命令 | 结果 |
|---|---|---|
| Python 回归 | py -3 -m pytest -q | PASS，62 passed in 12.73s |
| Ruff | py -3 -m ruff check core desktop tests | PASS，All checks passed! |
| Python 编译 | py -3 -m compileall -q core desktop tests | PASS，退出码 0 |
| Renderer/IPC | npm test | PASS，Vite build + M3 IPC selftest PASS m3-python |
| TypeScript | npx tsc --noEmit | PASS |
| npm 依赖审计 | npm audit --audit-level=high | FAIL/OPEN，13 项漏洞（3 moderate、9 high、1 critical），修复会升级 Electron/electron-builder，需单独评估 |
| 打包环境 | py -3 -m packaging.build_candidate inspect --project . | BLOCKED，固定工作树没有 runtime/desktop-ipc-server.exe 和冻结 FFmpeg/FFprobe |

原始日志：

- docs/execution/review_pytest.log
- docs/execution/review_ruff_compile.log
- docs/execution/review_npm.log
- docs/execution/review_packaging_inspect.log

## P0/P1 发现

### R-P0-001：M4 编码可覆盖源文件

- 严重度：P0
- 文件：core/media/encode.py:349-395, 495-497
- 规则：R09、M4 源文件只读、M6 安全提交前不得覆盖旧文件。
- 复现：调用 encode_segment(source_path, ..., output_path=source_path)。函数没有调用 paths_refer_same_file() 检查，验证通过后执行 os.replace(partial, destination)。
- 实际证据：以 F:\M1_samples\short_0_2s.mp4 的临时副本复现。编码返回 complete；源 SHA-256 从 d6bcd067b54a825b6dd9497c484aef3005fa4ab80e2fe4b332de4538b56eb771 变为 dbc3f789cc6e9eae2eda04c3a8e68955a81533c5cfe72c7188bbc2e44f91f238。
- 影响：M4/M6 上游若传入同一物理路径会直接破坏用户源视频，属于必须立即停止导出路径的 P0。
- 修复建议：在建立 staging 前拒绝源/目标同物理文件（大小写、相对路径、硬链接、符号链接、junction），返回结构化 PATH_CONFLICT；补充成功和失败路径的 SHA-256 回归测试。

### R-P1-002：事务日志写入顺序无法保证崩溃恢复

- 严重度：P1（安全替换阻断）
- 文件：core/commit/transaction.py:213-237, 291-328
- 规则：R13、R15；多文件替换中断后必须恢复完整旧版或新版。
- 复现：完成 state=verified 日志后手动执行旧目标到 backup 的 os.replace，模拟在写入 state=committing 前进程退出，再调用 recover_transaction()。
- 实际输出：before recovery target_exists=False backup_exists=True journal_state=verified；recover=rolled_back；after recovery target_exists=False backup_exists=True。
- 影响：旧文件已被移走但 journal 的 files 仍为空，恢复函数返回名义上的 rolled_back，却不恢复旧文件，导致输出缺失。
- 修复建议：在任何旧目标移动前写入包含完整 files/backup 映射的 committing journal 并 fsync；或在 recover 中扫描 backup 并按 artifacts 恢复；补充模拟进程退出窗口的回归测试。

### R-P1-003：重启后没有用户确认恢复 IPC

- 严重度：P1
- 文件：desktop/ipc_server.py:39-53, 208-216；src/renderer/App.vue
- 规则：R14、M6；异常退出后必须用户确认后继续，不得自动恢复。
- 证据：启动项目时 _configure_queue() 调用 mark_interrupted_for_restart()；代码没有暴露 QueueStore.confirm_recovery() 的 IPC 方法，renderer 也没有恢复确认/任务恢复控件。resume_export 只会 pump pending，interrupted 任务不会变回 pending。
- 影响：重启后的中断任务会永久停留 interrupted，用户无法通过产品界面确认后继续。
- 修复建议：增加版本化 confirm_recovery IPC 和明确的恢复确认视图；确认前不启动编码，确认后仅恢复选定任务；补充 Electron/IPC 重启回归。

### R-P1-004：多个默认视频流被静默选择

- 严重度：P1
- 文件：core/media/probe.py:267-275
- 规则：M1 多流安全选择；无法安全确定时必须结构化歧义。
- 证据：当存在多条 default 视频流时，defaults 仍被作为 candidates，随后按最低 stream_index 选择，并只追加诊断字符串。真实多视频/附图样片只证明排除 attached_pic，没有证明两个默认主视频流可安全选择。
- 影响：可能把错误的视频流送入检测、预览和导出，且下游看到的是 complete 结果。
- 修复建议：多个同等候选默认返回 AMBIGUOUS_VIDEO_STREAM 或要求显式 stream 选择；测试应覆盖两个 default 主视频流。

### R-P1-005：规范化音频时间轴校验不响应取消

- 严重度：P1
- 文件：core/media/normalize.py:49-95, 328-330, 443-445
- 规则：M1 probe/index/normalize 可取消、取消后无残留进程。
- 证据：_read_audio_packets() 使用 subprocess.run(... timeout=...)，没有接收 CancellationToken。normalize 在源/输出音频包扫描期间无法及时响应取消，超时也只能等待 subprocess 的 timeout 路径。
- 影响：大文件或异常媒体上用户取消可能被阻塞，且无法确认子进程树已回收。
- 修复建议：改为与其他媒体阶段一致的 Popen + 并发读取 + token/timeout 监控；取消时使用统一进程树终止函数并清理 partial。

### R-P1-006：Live Photo 的 still-image-time 只做字符串存在性检查

- 严重度：P1
- 文件：core/livephoto/pack.py:268-307, 466-473
- 规则：M5 封面和时间元数据必须与 MOV 时间轴一致。
- 证据：_validate_pair() 只检查 raw_has_still_key，不校验数值范围、是否落在 MOV 时长内或是否对应实际视频帧。对 0.2 秒 MOV 传入 still_image_time_seconds=999 仍返回 complete，manifest 记录 mov_still_image_time_tag=999。
- 影响：非法时间轨数据会被标记为本地校验通过。
- 修复建议：要求值为有限数、0 <= still_image_time < duration，并映射到合法显示帧；验证失败不得发布任何产物。

### R-P1-007：Live Photo timed metadata track 未实现/未验证

- 严重度：P1 / BLOCKED
- 文件：core/livephoto/pack.py:298, 327；docs/M4_M5_MEDIA_EXPORT.md
- 规则：M5 必须生成并校验必要元数据；iPhone 兼容性另行标记。
- 证据：实现明确固定 timed_metadata_track=false，只写 moov metadata 与 JPEG MakerNote。文档诚实保留 iPhone 未验证状态，但这意味着 M5 完整验收尚未达到。
- 影响：不能把本地生成的 LIVP 视为已通过 iPhone 真机验收，也不能申请 V1.0 外部终审通过。
- 修复建议：接入可复核的 Apple timed metadata 轨生成/外部解析；在此之前维持 BLOCKED，不得改写为 PASS。

### R-P1-008：重复 start_export 没有去重或快照锁

- 严重度：P1
- 文件：desktop/ipc_server.py:156-200；core/queue/store.py:185-226
- 规则：重复继续/导出不能创建重复工作进程或覆盖竞争。
- 证据：每次 start_export 都为所有片段无条件 enqueue；没有已有活动快照检测、幂等请求 ID 或 clip/snapshot 唯一约束。
- 影响：重复点击会重复编码并再次替换同一路径的结果，增加覆盖竞争和状态歧义。
- 修复建议：以 project/snapshot hash/clip 建立幂等键；活动或成功任务重复请求应返回现有任务，或要求显式新 export version。

## 需求与证据状态

| 需求组 | 状态 | 说明 |
|---|---|---|
| M1 基础 28 项及当前 Python 回归 | PASS | 固定提交实际为 62 项全通过；M1 BLOCKED 项仍诚实记录 |
| M2 真实婚礼 10 条人工真值、召回率 ≥95% | BLOCKED | 只有合成样片，不能推出实拍精度 |
| M2 短镜头保留、黑场、叠化候选 | PASS（合成）/BLOCKED（实拍） | 算法测试通过，真实复杂素材未验证 |
| M3 真实导入、时间线、编辑、音频冲突 | PASS（Python/IPC）/BLOCKED（视觉） | build/selftest/IPC 通过；固定审查工作树无真实安装窗口截图，renderer 没有切点 checked 操作按钮，也没有队列恢复 UI |
| M4 精准帧范围、GPU→CPU、HDR→SDR | PASS（合成）/BLOCKED（复杂实拍） | 测试覆盖 VFR/GPU fallback/HDR10；无婚礼 4K/长短混合真实回归 |
| M5 LIVP UUID、哈希、本地解码 | PASS（本地） | 真实 iPhone/Apple timed metadata track 未验证，仍 BLOCKED |
| M6 队列、恢复、事务 | FAIL/BLOCKED | 发现 R-P0-001、R-P1-002、R-P1-003、R-P1-008；不可交付 |
| M7 离线候选目录/ZIP | BLOCKED（固定提交证据） | sibling worktree 有 ZIP，但 runtime/delivery 不在固定提交，需在修复后重新生成并绑定 SHA |
| NSIS 安装器/安装卸载 | BLOCKED | 文档记录 NSIS resources 网络阻塞；未完成实机安装矩阵 |
| iPhone/社交平台兼容 | BLOCKED | 按冻结要求不得宣称通过 |
| 无 iPhone App/云/账号/收费 | PASS | 未发现 V1.0 新增此类产品模块；旧 update.py 仍保留原仓库更新地址，但未纳入 Electron 候选 files，需在交付包审查时确认不被调用 |

## 候选包核对

固定审查 worktree 没有 runtime/、delivery/，所以 packaging.build_candidate inspect 返回缺少 bundled sidecar/FFmpeg。另一个集成工作树存在离线 ZIP，SHA-256 为 18A6659471C6EFD9F42C98180400589A36CCD3C670BC1BF1169145EBC9B0E095，但该文件是工作树产物而非固定提交内容；修复 P0/P1 后必须重新构建并重新计算指纹。现有文档中的 ZIP SHA 不能作为最终集成版本证据。

## 交付判定

当前固定提交：FAIL，发布阻塞，不能交付外部终审。

最低解除条件：

1. 修复并回归 R-P0-001 源/目标同文件保护。
2. 修复并回归 R-P1-002 事务 journal 窗口和崩溃恢复。
3. 提供用户确认恢复 IPC/UI，并完成重启后队列证据。
4. 对多默认主视频流做结构化歧义处理。
5. 重新执行完整 Python、Ruff、compileall、npm build/selftest/tsc，并绑定最终提交。
6. 重新生成候选包、许可证清单和实际安装/卸载记录；维持 Live Photo timed metadata、真实婚礼精度、ENOSPC/ACL/外部强杀等 BLOCKED 事实。

