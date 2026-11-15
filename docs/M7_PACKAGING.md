# M7 Windows 候选打包

## 采用 Electron 路径

`packaging/build_candidate.py` 只接受包含 `package.json` 的 Electron 项目，并调用项目锁定的 `electron-builder` 生成 Windows NSIS `.exe`。不再把旧 Tkinter/PyInstaller 产物冒充 V1.0 Electron 安装包。构建目录、依赖锁和候选包由调用者显式指定。

检查环境：

```powershell
py -3 -m packaging.build_candidate inspect --project <electron-project>
```

候选构建（仅在已核对 package-lock 和依赖来源后）：

```powershell
py -3 -m packaging.build_candidate build --project <electron-project> --output <delivery\v1.0> --install-deps
```

脚本使用 `shell=False`，构建失败或缺少 Electron 项目、Node/npm、`electron-builder` 时返回 `blocked`，不会创建伪造安装包。成功后输出 `THIRD_PARTY_LICENSES.json` 和 `CANDIDATE_SHA256.txt`。包默认未签名，FFmpeg 的 GPL/LGPL、编解码器和源代码提供义务必须在交付前绑定到实际二进制。

## 当前环境证据

```text
Python 3.12.10
Node v24.22.1
npm 11.19.1
PyInstaller 6.11.1 已用于生成 bundled `runtime/desktop-ipc-server.exe`
Electron 31.7.7 使用本地 `electronDist`，无需重新下载 Electron 压缩包
FFmpeg/FFprobe 使用冻结构建，复制到 `runtime/ffmpeg/`
```

已生成并验证 Windows `win-unpacked` 候选目录和 NSIS 安装器，均包含 Electron、Python sidecar 和 FFmpeg/FFprobe；sidecar JSONL `ping` 返回 `m3-python`。

- 候选目录：`delivery/v1.0/installer/win-unpacked/`
- 离线候选 ZIP：`delivery/v1.0/Video2LivePhoto-1.0.0-final-candidate-win-unpacked.zip`
- ZIP SHA-256：`B9470022CB68021F6634B63393DCCA75D066B25A06FF533397769B5BF83764CE`
- NSIS 安装器：`delivery/v1.0/nsis-attempt/Video2LivePhoto Setup 1.0.0-candidate.exe`
- NSIS SHA-256：`AEE9047007C424EEB14238FADECF66248DEDE9ED64642FE3650F93016D4B04E1`
- Python sidecar SHA-256：`2E8074C661DA460EB4DCF0E492A2FBFC02B1B3DEF5E3F8C7D1EA0AF366929668`
- FFmpeg SHA-256：`6632B01B7981092AF425787CD16DDF6449E7BD634AE756398BF4189DB8C42482`
- FFprobe SHA-256：`C2AD6060AE546E850E436A79786FDC68C8ACC623C283D38E225B0E13163B6446`

本次网络环境已成功取得 electron-builder 的 `nsis-3.0.4.1` 与 `nsis-resources-3.4.1`，NSIS 候选已生成并有 SHA-256。安装/卸载、签名、iPhone Photos 兼容性仍不等同于发布批准，需在目标 Windows 机器执行外部验收。
