# M1 媒体工具链冻结记录

本文件只记录 M1 开发与测试环境，不把开发机路径当作产品发布依赖。

| 工具 | 版本首行 | SHA-256 | 当前来源 | 许可证状态 |
|---|---|---|---|---|
| `ffmpeg.exe` | `N-120646-g6711c6a89b-20250810` | `6632B01B7981092AF425787CD16DDF6449E7BD634AE756398BF4189DB8C42482` | `F:\DY60\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe` | 构建参数含 `--enable-gpl`；发布再分发清单尚未完成 |
| `ffprobe.exe` | `N-120646-g6711c6a89b-20250810` | `C2AD6060AE546E850E436A79786FDC68C8ACC623C283D38E225B0E13163B6446` | `F:\DY60\ffmpeg-master-latest-win64-gpl-shared\bin\ffprobe.exe` | 与同构建 FFmpeg 一并审计 |

M1 通过 `Toolchain.from_paths()` 记录版本和 SHA-256，并且默认诊断入口通过 `toolchain_manifest.py` 强制匹配上述 SHA-256。所有外部调用使用参数数组、`shell=False`、无自动联网。缺失工具、版本自检失败和 SHA-256 不匹配会返回结构化错误。

产品打包前仍需冻结可再分发的 FFmpeg 构建、对应 GPL/LGPL 选择、编解码器许可、源代码提供义务和第三方许可证清单。M1 不打包二进制，也不宣称已完成发布许可审计。
