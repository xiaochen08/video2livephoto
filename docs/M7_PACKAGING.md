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

已生成并验证 Windows `win-unpacked` 候选目录，包含 Electron、Python sidecar 和 FFmpeg/FFprobe；sidecar JSONL `ping` 返回 `m3-python`。

- 候选目录：`delivery/v1.0/win-unpacked/`
- 离线候选 ZIP：`delivery/v1.0/Video2LivePhoto-1.0.0-candidate-win-unpacked.zip`
- ZIP SHA-256：`18A6659471C6EFD9F42C98180400589A36CCD3C670BC1BF1169145EBC9B0E095`
- Python sidecar SHA-256：`BFC78B484358D79288D809063AB8C1B233D200FE9F4FF563B4ADBE688FEF4CA3`
- FFmpeg SHA-256：`6632B01B7981092AF425787CD16DDF6449E7BD634AE756398BF4189DB8C42482`
- FFprobe SHA-256：`C2AD6060AE546E850E436A79786FDC68C8ACC623C283D38E225B0E13163B6446`

NSIS 安装器仍为 BLOCKED：electron-builder 在生成 `.exe` 安装器时需要从 GitHub 下载 `nsis-resources`，当前网络无法连接该地址。不能把 `win-unpacked` 或 ZIP 标记为 NSIS 安装器通过；安装/卸载、无外部 Python 和离线启动需在取得 NSIS 资源后复测。
