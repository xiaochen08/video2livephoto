# 复审后候选包补证

R 复审绑定源码提交 `589c41750f7c3ac3c7216c22dd3632b7638ef318`。复审报告指出的旧 ZIP 指纹问题随后已在同一源码提交上重新冻结 sidecar、Electron 目录和安装器；以下是实际补证，不能与旧 ZIP 混用。

| 产物 | 路径 | SHA-256 | 结果 |
|---|---|---|---|
| NSIS 安装器 | `delivery/v1.0/nsis-attempt/Video2LivePhoto Setup 1.0.0-candidate.exe` | `AEE9047007C424EEB14238FADECF66248DEDE9ED64642FE3650F93016D4B04E1` | PASS：electron-builder 24.13.3 生成 |
| 离线解压 ZIP | `delivery/v1.0/Video2LivePhoto-1.0.0-final-candidate-win-unpacked.zip` | `B9470022CB68021F6634B63393DCCA75D066B25A06FF533397769B5BF83764CE` | PASS：从重新构建的 win-unpacked 压缩 |
| Python sidecar | `runtime/desktop-ipc-server.exe` | `2E8074C661DA460EB4DCF0E492A2FBFC02B1B3DEF5E3F8C7D1EA0AF366929668` | PASS：重新 PyInstaller 冻结 |
| bundled FFmpeg | `runtime/ffmpeg/ffmpeg.exe` | `6632B01B7981092AF425787CD16DDF6449E7BD634AE756398BF4189DB8C42482` | PASS：冻结构建 |
| bundled FFprobe | `runtime/ffmpeg/ffprobe.exe` | `C2AD6060AE546E850E436A79786FDC68C8ACC623C283D38E225B0E13163B6446` | PASS：冻结构建 |

验证：`py -3 -m packaging.build_candidate inspect --project .` 返回 `missing=[]`；直接启动 sidecar 并发送 `m3.ipc.v1/ping` 返回 `{"ok": true, "protocol": "m3.ipc.v1", "service": "m3-python"}`。安装器尚未在独立 Windows 目标机执行安装/卸载和离线全流程，因此保留 R 报告中的外部 BLOCKED 限制。

