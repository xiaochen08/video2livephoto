# M1 媒体基础层实施报告

## 范围

本分支只实现 M1-A～M1-F：固定工具链诊断、源身份、FFprobe 媒体探测、受限 ISOBMFF/fMP4 检查、显示帧 PTS 索引、SQLite 分批缓存、fMP4 `-c copy` 隔离规范化、取消与结构化错误。没有实现 M2 镜头检测、M3 UI、M4 编码、M5 Live Photo 封装、M6 队列恢复或 M7 打包。

## 实际文件

- `core/protocol/media.py`：版本化数据契约与错误结构。
- `core/media/toolchain.py`：ffmpeg/ffprobe 自检、SHA-256、无 shell 子进程、进程内存采样。
- `core/media/toolchain_manifest.py`：开发环境固定版本和 SHA-256 指纹。
- `core/media/process.py`：统一取消令牌和子进程回收。
- `core/media/source_identity.py`：规范化路径、文件身份、抽样/完整哈希、源变化检查和物理路径冲突检查。
- `core/media/fragment_inspector.py`：流式盒头检查、`moof`/`mvex` 检测、截断/越界拒绝。
- `core/media/probe.py`：FFprobe 流、容器、颜色/HDR、方向、音频和多流摘要。
- `core/media/frame_index.py`：显示顺序帧、整数 PTS、B 帧字段、VFR、取消、SQLite 分批写入。
- `core/media/cache.py`：包含源身份、工具链和 schema 的可复用索引缓存。
- `core/media/normalize.py`：缓存目录内的 fMP4 无重编码规范化和时间轴偏移验证。
- `core/media/diagnostic.py`：`probe`、`index`、`inspect-fragments`、`normalize` 诊断入口。
- `tests/`：28 个自动化测试；`docs/M1_MEDIA_FOUNDATION.md`、`docs/M1_TOOLCHAIN.md` 和 `docs/M1_FIXTURE_MANIFEST.md` 为接口、工具链和样片记录。

## 自动化测试结果

| 项目 | 结果 | 证据 |
|---|---|---|
| 契约序列化、整数 PTS、错误码 | PASS | `28 passed` 总体测试中的契约断言 |
| Unicode/中文路径、源身份、变化检测 | PASS | `tests/media/test_source_identity.py` |
| 普通 MP4/MOV 容器探测、H.264/AAC、未知色彩 | PASS | 普通样片与改扩展名样片 |
| B 帧显示顺序 | PASS | H.264 `bf=2` fixture，缓存含 `pict_type=B` |
| VFR 非均匀 PTS | PASS | 与独立 FFprobe compact 输出逐项相同，36 帧 |
| 0.2 秒短视频 | PASS | 6 帧全部进入索引，无最短时长过滤 |
| HDR10 风格 HEVC 10-bit 元数据 | PASS | `yuv420p10le`、`bt2020`、`smpte2084` 被忠实记录，未执行色彩转换 |
| 正常 fMP4（`moov/mvex/moof`）直接索引 | PASS | 30 帧直接建立索引 |
| fMP4 `-c copy` 规范化 | PASS | 60 帧保持一致，PTS 偏移 `-1024` 被记录，源 SHA 不变 |
| 负音频 PTS、负视频 DTS 与 edit list | PASS（范围限定） | 独立 FFprobe 读到音频 PTS `-1024`、视频 DTS `-1024`；文件含 `edts/elst`；显示帧 best-effort PTS 与 SQLite 逐项一致。负显示 PTS 本身没有在样片中出现，见 BLOCKED |
| 多视频流与封面附图流 | PASS | 真实三流样片选择默认视频流 0，排除 `attached_pic` 流 2，并保留附图流摘要 |
| fMP4 音频包时间轴 | PASS | `-c copy` 前后音频包数量与 PTS 偏移均经独立 FFprobe 核对，时基保持 `1/48000` |
| `moof` 无 `mvex` 异常变体 | PASS | 盒检查识别；FFprobe 无法验证时返回 `FFPROBE_FAILED` |
| 截断/越界盒 | PASS | 返回 `MALFORMED_CONTAINER` |
| 取消和 incomplete 缓存 | PASS | 取消不生成 complete 状态 |
| 缓存根路径不可用 | PASS | 根路径为已有文件时返回结构化 `CACHE_PATH_UNAVAILABLE`，不抛裸 `OSError` |
| 子进程强制终止 | PASS（辅助层） | `kill_process` 真实终止运行中的 Python 子进程；M1 FFprobe/FFmpeg 长时中途外部强杀矩阵仍 BLOCKED |
| 缓存复用和失效键 | PASS | 同源/同工具第二次 `cache_reused=true` |
| 源文件与缓存路径冲突 | PASS | 返回 `PATH_CONFLICT` |
| Ruff、Python 编译 | PASS | Ruff check 无错误，compileall 退出码 0 |

## 大文件证据

使用隔离目录 `F:\M1_samples` 生成合法可解码的 4,478,978,897 字节 rawvideo MOV。FFprobe 和 FFmpeg 解码均成功；M1 索引结果为 270 帧、9 秒、`time_base=1/15360`。

- 完整 SHA-256：`8C519A99FF4F2AE817E748ED18B5E5AFF4F262D391DEFF993B3E5C2F098D7D9F`
- 本轮复测资源统计：FFprobe 峰值 PrivateUsage `53,624,832` 字节；Python 峰值约 `13,934,592` 字节；模块计时 `1.833` 秒，CLI 墙钟 `2.488` 秒。第二次运行命中 SQLite 缓存（`cache_reused=true`），未重新启动 FFprobe。
- 索引前后 SHA-256 相同；缓存复用后第二次不再启动 FFprobe。

另有 4,295,060,242 字节的 MP4 容器填充样片用于 64 位盒尺寸和随机访问压力，FFprobe 读到 60 帧/2 秒。它只用于容器尺寸测试，不作为高码率长片吞吐量证据。

## 工具链

M1 测试使用 FFmpeg/FFprobe `N-120646-g6711c6a89b-20250810`。具体 SHA-256、构建参数和许可证未决事项记录在 `docs/M1_TOOLCHAIN.md`。当前构建含 `--enable-gpl`，产品再分发许可审计仍未完成。

## 时间轴与 fMP4 对照证据

- `F:\M1_samples\neg_tests\edit_audio_offset.mp4`：音频首包 `pts=dts=-1024`（音频时基 `1/48000`），视频首包 `pts=0,dts=-1024`（视频时基 `1/15360`），显示帧首 6 个 best-effort PTS 为 `0,512,1024,1536,2048,2560`。独立 FFmpeg `showinfo` 逐帧解码输出与 SQLite 索引逐项相同。这说明 DTS 可以为负而显示时间轴仍从 0 开始；不能把负 DTS 当作负显示 PTS。
- `F:\M1_samples\fmp4_av_1s.mp4`：源视频首帧 PTS `1024`，规范化后首帧 PTS `1014`，恒定偏移 `-10`，两侧均为 30 帧、时基 `1/15360`；音频两侧均 48 包、时基 `1/48000`、PTS 偏移 `0`，前 5 个包均为 `0,3200,4224,5248,6272`。偏移来自封装起始时间戳重写，不是重编码；M1 将其作为显式映射返回，不能直接把规范化 PTS 当作源 PTS。
- `E:\LIVE\_audit\fixtures\frag_h264_2s.mp4` 的既有证据仍保留：视频恒定偏移 `-1024`。不同 fMP4 样片出现 `-1024` 与 `-10` 是允许的封装起点差异，必须按每个结果的映射消费。

## 异常恢复与资源保护

- 磁盘满：真实卷级 ENOSPC 未执行。向测试卷填满空间会改变用户环境，当前没有隔离配额卷，因此标记 BLOCKED；缓存创建路径已经把 `OSError`（包括 ENOSPC）转换为 `CACHE_PATH_UNAVAILABLE`。
- 权限拒绝：未修改 ACL 或系统权限来制造拒绝，标记 BLOCKED；已有文件占用缓存根路径的拒绝路径自动化 PASS，覆盖路径冲突但不等同于 Windows ACL 回归。
- 强制终止：`tests/media/test_process.py` 已真实终止运行中的子进程；M1 的取消路径会杀掉 FFprobe/FFmpeg、标记 SQLite 为 incomplete 并删除规范化 partial 文件。外部工具在任意帧中间被任务管理器强杀的 Windows 进程树矩阵未完成，标记 BLOCKED。
- 源保护：fMP4 规范化前后源 SHA-256 相同，输出只写入唯一缓存目录；测试确认没有残留 `*.partial.mp4`。
- 内存：4 GiB rawvideo MOV 索引峰值 FFprobe PrivateUsage `53,579,776` 字节，Python 峰值约 `13,893,632` 字节；没有整文件读入内存。

## 尚未闭环

- 没有取得显示帧本身为负 PTS 的真实样片；当前只有负音频 PTS 和负视频 DTS 证据，负显示 PTS 处理标记为 BLOCKED。
- 尚未用硬链接、junction 和 Windows ACL 拒绝样片完成全矩阵回归。
- Dolby Vision、Log 和复杂 HDR side data 只实现检测字段，未验证完整样片覆盖。
- 中途强杀长时间 FFprobe/FFmpeg、磁盘满和进程树回收需要后续 Windows 专项回归。
- FFmpeg 二进制的最终再分发方式、许可证文本和构建来源尚未冻结。

## M1 最终验收状态

| 状态 | 项目 |
|---|---|
| PASS | 28 项自动化测试、Ruff、Python 编译；普通媒体、B 帧、VFR、短视频、HDR 元数据、fMP4 直接索引和受控 `-c copy` 规范化；真实多视频/附图流；负音频 PTS/edit list；源 SHA、缓存和辅助子进程终止 |
| FAIL | 无已确认的 M1 功能性 FAIL |
| BLOCKED | 真实负显示 PTS 样片；真实卷级磁盘满；真实 Windows ACL 权限拒绝；外部强杀长时 FFprobe/FFmpeg 的完整进程树矩阵；4 GiB 样片生成脚本未纳入仓库导致的可复现性缺口 |

这些 BLOCKED 项不应被描述为已兼容；它们不阻止 M2 读取已冻结的数据契约，但会影响 M2 对异常素材的产品化提示和验收范围。

## M2 可使用的数据接口

- `probe_media()` 返回 `MediaProbeResult`：`selected_video_stream`、`video_stream`、`audio_streams`、`attached_picture_streams`、`color`、`fragment`、`diagnostics` 和 `SourceIdentity`。
- `build_frame_index()` 返回 `FrameIndexReport`，SQLite `frames` 表提供 `display_index`、`pts`、`best_effort_pts`、`duration`、`dts`、`pict_type` 和 `time_base`；M2 应按显示顺序消费，不按文件偏移猜帧。
- `normalize_fragmented()` 返回 `NormalizedMediaRef`；`validation.video_timeline` 提供规范化前后首尾 PTS、帧数和时基，`source_to_normalized_pts_offset` 提供恒定视频映射，`audio_timeline` 提供每条音频流包数和 PTS 偏移，`audio_time_bases` 提供音频时基。
- `MediaError` 统一携带 `code`、`stage`、`retryable` 和脱敏后的诊断字段；M2 不应绕过这些错误直接覆盖源文件。

这些事项不扩展为 M2 功能；它们必须在 M1 验收时继续标为 `UNVERIFIED` 或 `BLOCKED`，不能被测试数量掩盖。
