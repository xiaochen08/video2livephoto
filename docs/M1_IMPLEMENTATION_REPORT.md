# M1 媒体基础层实施报告

## 范围

本分支只实现 M1-A～M1-F：固定工具链诊断、源身份、FFprobe 媒体探测、受限 ISOBMFF/fMP4 检查、显示帧 PTS 索引、SQLite 分批缓存、fMP4 `-c copy` 隔离规范化、取消与结构化错误。没有实现 M2 镜头检测、M3 UI、M4 编码、M5 Live Photo 封装、M6 队列恢复或 M7 打包。

## 实际文件

- `core/protocol/media.py`：版本化数据契约与错误结构。
- `core/media/toolchain.py`：ffmpeg/ffprobe 自检、SHA-256、无 shell 子进程、进程内存采样。
- `core/media/process.py`：统一取消令牌和子进程回收。
- `core/media/source_identity.py`：规范化路径、文件身份、抽样/完整哈希、源变化检查和物理路径冲突检查。
- `core/media/fragment_inspector.py`：流式盒头检查、`moof`/`mvex` 检测、截断/越界拒绝。
- `core/media/probe.py`：FFprobe 流、容器、颜色/HDR、方向、音频和多流摘要。
- `core/media/frame_index.py`：显示顺序帧、整数 PTS、B 帧字段、VFR、取消、SQLite 分批写入。
- `core/media/cache.py`：包含源身份、工具链和 schema 的可复用索引缓存。
- `core/media/normalize.py`：缓存目录内的 fMP4 无重编码规范化和时间轴偏移验证。
- `core/media/diagnostic.py`：`probe`、`index`、`inspect-fragments`、`normalize` 诊断入口。
- `tests/`：17 个自动化测试；`docs/M1_MEDIA_FOUNDATION.md`、`docs/M1_TOOLCHAIN.md` 为接口和工具链记录。

## 自动化测试结果

| 项目 | 结果 | 证据 |
|---|---|---|
| 契约序列化、整数 PTS、错误码 | PASS | `21 passed` 中的契约测试 |
| Unicode/中文路径、源身份、变化检测 | PASS | `tests/media/test_source_identity.py` |
| 普通 MP4/MOV 容器探测、H.264/AAC、未知色彩 | PASS | 普通样片与改扩展名样片 |
| B 帧显示顺序 | PASS | H.264 `bf=2` fixture，缓存含 `pict_type=B` |
| VFR 非均匀 PTS | PASS | 与独立 FFprobe compact 输出逐项相同，36 帧 |
| 0.2 秒短视频 | PASS | 6 帧全部进入索引，无最短时长过滤 |
| HDR10 风格 HEVC 10-bit 元数据 | PASS | `yuv420p10le`、`bt2020`、`smpte2084` 被忠实记录，未执行色彩转换 |
| 正常 fMP4（`moov/mvex/moof`）直接索引 | PASS | 30 帧直接建立索引 |
| fMP4 `-c copy` 规范化 | PASS | 60 帧保持一致，PTS 偏移 `-1024` 被记录，源 SHA 不变 |
| `moof` 无 `mvex` 异常变体 | PASS | 盒检查识别；FFprobe 无法验证时返回 `FFPROBE_FAILED` |
| 截断/越界盒 | PASS | 返回 `MALFORMED_CONTAINER` |
| 取消和 incomplete 缓存 | PASS | 取消不生成 complete 状态 |
| 缓存复用和失效键 | PASS | 同源/同工具第二次 `cache_reused=true` |
| 源文件与缓存路径冲突 | PASS | 返回 `PATH_CONFLICT` |
| Ruff、Python 编译 | PASS | Ruff check 无错误，compileall 退出码 0 |

## 大文件证据

使用隔离目录 `F:\M1_samples` 生成合法可解码的 4,478,978,897 字节 rawvideo MOV。FFprobe 和 FFmpeg 解码均成功；M1 索引结果为 270 帧、9 秒、`time_base=1/15360`。

- 完整 SHA-256：`8C519A99FF4F2AE817E748ED18B5E5AFF4F262D391DEFF993B3E5C2F098D7D9F`
- 索引资源统计：FFprobe 峰值 PrivateUsage `53,579,776` 字节；Python 峰值约 `13,893,632` 字节；模块计时 `3.619` 秒，CLI 墙钟约 `6.783` 秒。
- 索引前后 SHA-256 相同；缓存复用后第二次不再启动 FFprobe。

另有 4,295,060,242 字节的 MP4 容器填充样片用于 64 位盒尺寸和随机访问压力，FFprobe 读到 60 帧/2 秒。它只用于容器尺寸测试，不作为高码率长片吞吐量证据。

## 工具链

M1 测试使用 FFmpeg/FFprobe `N-120646-g6711c6a89b-20250810`。具体 SHA-256、构建参数和许可证未决事项记录在 `docs/M1_TOOLCHAIN.md`。当前构建含 `--enable-gpl`，产品再分发许可审计仍未完成。

## 尚未闭环

- 尚未取得真实负时间戳/edit-list 样片，相关路径有整数 PTS 契约但标记为 `UNVERIFIED`。
- 尚未用真实多视频流、硬链接、junction 和权限拒绝样片完成 Windows 全矩阵回归。
- Dolby Vision、Log 和复杂 HDR side data 只实现检测字段，未验证完整样片覆盖。
- 中途强杀长时间 FFprobe/FFmpeg、磁盘满和进程树回收需要后续 Windows 专项回归。
- FFmpeg 二进制的最终再分发方式、许可证文本和构建来源尚未冻结。

这些事项不扩展为 M2 功能；它们必须在 M1 验收时继续标为 `UNVERIFIED` 或 `BLOCKED`，不能被测试数量掩盖。
