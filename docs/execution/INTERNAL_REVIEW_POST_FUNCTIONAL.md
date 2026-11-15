# V1.0 功能补强后独立复审记录

审查对象：integration 代码提交 ed115dfbe4318a0b069f3d8a66a645cc559d8d96

审查范围：e788871 之后的功能补强提交、M5 mebx timed metadata、M1 PTS/edit-list 与多流处理、M6 重试与导出报告状态路径，以及此前 581a230 的 stale report 修复。

审查方式：只读检查；未修改生产代码、未打包、未操作原始 main、M0 审计克隆或远端。

## 结果

结论：CONDITIONAL PASS。本轮没有发现新的已确认 P0/P1。

- Python 全量回归：77 passed。
- Ruff、compileall：PASS。
- M1 PTS/edit-list、fMP4 映射、负音频 PTS/视频 DTS、无默认多视频流歧义拒绝：PASS。
- M5 mebx timed metadata atom 重写、普通/非零 still-image-time/fMP4 remux、样本偏移和 edit list 校验：PASS。
- M6 失败任务显式重试、重试上限、报告 in_progress/complete/complete_with_errors 状态和 stale report 失效：PASS。
- retry_export 现先完成 retry admission，成功后才写 status=in_progress；重试次数耗尽不会污染既有报告。

针对性复测：

- tests/desktop/test_ipc.py::test_ipc_failed_export_can_be_retried_explicitly：PASS。
- 完整 py -3 -m pytest -q：77 passed。

## 仍然 BLOCKED

以下限制没有被本轮代码补强改变：

- 真实婚礼样片、人工切点真值和 M2 召回率目标。
- iPhone Photos/社交平台真机兼容性。
- M1 真实负显示 PTS、卷级 ENOSPC、ACL 拒绝、外部强杀矩阵。
- 目标 Windows 实机安装、卸载、离线全流程和完整 UI 录屏。
- npm 依赖安全审计仍有已知漏洞，FFmpeg 再分发义务仍需随候选包审查。

因此源码和自动化测试可标记为 CONDITIONAL PASS；不能据此宣称 V1.0 已完成外部兼容性或正式发布验收。

