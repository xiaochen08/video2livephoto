# V1.0 源码审查包

## 固定来源

- 原仓库：`https://github.com/969246694/video2livephoto`
- 原始 main / M0 审计克隆：`e6231886298e0a4bccf0e6591784a2fdba736db6`
- M1 承接基线：`a8dbc02bd56e63c0c71e9094858cc0e87611bdd6`
- V1.0 最终集成分支：`codex/v1-integration`

## 许可证

原项目根目录 `LICENSE` 为 MIT，版权行保留 `yiyangzai`。候选安装包同时生成 `THIRD_PARTY_LICENSES.json`；FFmpeg 为 GPL/LGPL 构建，编解码器及再分发义务仍需按实际二进制和发布渠道单独审查。

## 真实模块边界

- `core/media/`：FFprobe/FFmpeg 探测、fMP4 检查/规范化、显示帧索引、源身份、编码和取消。
- `core/analysis/`：M2 硬切、黑场、叠化候选和短镜头保留。
- `desktop/`：M3 项目 SQLite、时间线编辑、逐帧预览、JSONL IPC 和导出编排。
- `core/livephoto/`：M5 JPG MakerNote、MOV QuickTime metadata、manifest 和本地校验；Apple timed metadata 轨仍未宣称通过。
- `core/queue/` 与 `core/commit/`：M6 快照队列、用户确认恢复、事务日志、备份和安全提交。
- `electron/`、`src/renderer/`、`packaging/`：M3 桌面壳、Vue renderer、Python sidecar 和 Windows 候选构建。

## 保护边界

原始 main、M0 审计克隆和源视频未修改；所有媒体输出写入候选输出目录或事务私有临时目录。`encode_segment()`、规范化和提交层均检查源身份，源/目标同物理文件直接拒绝。

