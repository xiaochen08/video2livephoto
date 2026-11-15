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
PyInstaller 未安装（不作为 V1.0 路径）
当前 D worktree 没有 package.json，Electron candidate BLOCKED
```

因此本分支不输出 `.exe`。待主控集成 B 的 Electron 项目后，重新执行 inspect，再在隔离 delivery 目录构建并记录包 SHA-256、安装/卸载、中文路径、离线启动和无外部 Python 验证结果。未经过这些步骤不得标记 M7 PASS。
