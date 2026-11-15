# V1.0 已知限制与阻塞项

- M2 没有真实婚礼样片和人工真值，不能宣称召回率 ≥95% 或复杂闪光/摇镜误切已通过。
- M1 的真实负显示 PTS、Windows ACL 拒绝、卷级磁盘满和外部强杀长时媒体进程矩阵缺少隔离环境，保持 BLOCKED。
- M5 当前会生成并校验本地 `mebx` timed metadata 轨、QuickTime metadata 与 JPEG MakerNote；`compatibility=local-validation-only`。没有 iPhone Photos 真机验证，不能宣称 Live Photo 平台兼容。
- M7 候选为未签名 Windows 安装器；安装、卸载、升级和目标机离线启动需在目标 Windows 机器复验。
- `npm audit --audit-level=high` 报告 13 项依赖漏洞（3 moderate、9 high、1 critical）。自动修复会升级 Electron/electron-builder，当前未在冻结范围内擅自升级；候选包不应视为安全发布版本。
- Electron renderer 的实际原生窗口录屏和真实婚礼端到端导出尚未在本机完成；现有截图是 Vite renderer 的实际空导入页，不等同于安装后全流程验收。
- FFmpeg/FFprobe 的许可证和编解码器再分发义务必须随具体发布包再次审查。

