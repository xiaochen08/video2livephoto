# M3 桌面预览与编辑实现

## 实际技术边界

规格冻结为 Vue 3 + Electron + TypeScript。当前仓库原本没有前端工程，因此 M3 在不修改旧 `gui.py` 的前提下新增：

```text
Electron main.cjs
  └─ preload.cjs (contextBridge)
      └─ JSONL IPC：m3.ipc.v1
          └─ Python desktop.ipc_server
              └─ M3ProjectService / ProjectStore(SQLite)
                  └─ M1 probe_media + build_frame_index
```

Renderer 只发送版本化 IPC 请求，不直接读源视频，也不启动 FFmpeg。Python 服务通过 M1 的 FFprobe/FFmpeg 受控入口完成真实导入、源身份校验和显示帧索引；时间线按 SQLite 帧索引按需读取，不把整片媒体或所有高分辨率帧放入 UI 内存。

## M3 已实现

- 真实本地 MP4/MOV 导入，调用 M1 探测和帧索引。
- 逐帧显示窗口，保留整数 PTS、显示顺序和有理数时基。
- 切点增加、逐帧移动、删除、相邻片段合并。
- 左闭右开片段范围连续校验，禁止重叠和漏帧。
- 撤销/重做，SQLite 自动保存，项目重开时重新校验源文件身份。
- 单段音频开关、全部静音，合并音频设置不一致时要求用户选择。
- 待检查切点列表；未检查时导出确认会阻止，用户显式确认后只生成 M4 导出快照。
- Electron renderer 使用真实按钮和 IPC 服务；没有静态演示数据。

## M2/M4/M5/M6 接口状态

默认导入路径已调用 M2 `detect_shots()`；结果按候选帧边界持久化为待审核切点。`M3ProjectService.import_media(detector=...)` 仍保留可注入检测契约，便于回归和后续算法替换。

用户确认后 IPC `start_export` 将快照写入 M6 SQLite 队列；队列工作器调用 M4 `encode_segment()`、M5 `pack_live_photo()` 和安全提交事务，输出 MP4/JPG/MOV/manifest。未检查切点仍需显式确认，不能自动导出。

## 启动与测试

在 Windows PowerShell 中：

```text
npm install
npm run build
npm run selftest
py -3 -m pytest -q tests/desktop
py -3 -m ruff check desktop tests/desktop
```

本次实际环境：Node `v24.22.1`、npm `11.19.1`、Electron `31.7.7`、Vite `6.4.6`、Vue `3.5.x`。`npm run build` 和 `npm run selftest` 已通过；自测通过 JSONL ping 验证 Electron 使用的 Python IPC 服务协议和 renderer 构建产物存在。`npm start` 能启动 Electron 进程树；当前 CUA 环境未提供可绑定的 Windows 窗口句柄，因此无法取得可复核截图，界面截图验收标记 BLOCKED，不能把进程启动当作视觉验收。

## 已知限制

- 当前分支不包含 M2 检测实现；接入时只能通过注入 provider 或后续主控桥接，不应把完整时间线当作自动检测结果。
- M4 编码、HDR 转换、M5 Live Photo 封装和导出文件生成已由 M6 `start_export` 接通；Apple/iPhone 真机兼容仍按 M5 文档标记限制。
- Electron 候选包尚未打包为安装程序，M7 负责生产候选安装包。
- npm 安装报告了上游审计警告；依赖版本和再分发许可由 M7 统一审计，不能用 npm install 成功替代许可证验收。
