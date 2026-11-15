# M2 镜头检测模块（A 代理）

## 范围与基线

本分支基于 `9ed1115e40b43c29dfa599ceb3bb8812d35386e9`，保留 M1 媒体基础层及原有 28 项测试。M2 只读取 M1 的 SQLite 显示帧索引，不修改源视频、不实现 UI、精准分段、编码、Live Photo、队列或安装包。

新增入口：

```python
from core.analysis.shot_detection import detect_shots

result = detect_shots(
    source_path,
    frame_index_report=m1_report,
    toolchain=toolchain,
)
```

检测结果版本为 `m2.detection.v1`，配置版本为 `m2.config.v1`。每个候选切点携带 `frame_index`、整数 `pts`、`time_base`、类型、置信度、转场区间和 `review_required`；每个片段使用左闭右开 `[start_frame,end_frame)`，并记录起止 PTS 和 `short_shot`。候选与片段 ID 根据源抽样指纹、类型和帧边界派生，可在相同源和配置下复现。

## 算法边界

- FFmpeg 以参数数组、无 shell 的方式解码所选视频流，输出 `16x16` 灰度 rawvideo；读取过程不把原始帧长期保留在内存中，只保留每帧亮度和 16 个块特征。
- 硬切使用相邻显示帧的局部 SAD 阈值；黑场使用连续低亮度帧并分别产生进入/离开候选。黑场不会被删除，候选始终要求人工检查。
- 叠化候选使用连续中等变化区间，切点吸附到真实显示帧索引的区间中点，并标记 `review_required=true`。该结果是候选，不代表已完成最终人工审核。
- 短镜头不使用最短时长过滤；`short_shot=true` 仅为下游提示，段仍完整保留。默认阈值为 1 秒，实际切点仍由用户审核。
- 不依赖 PySceneDetect，也不宣称对真实婚礼素材达到目标召回率；真实实拍样片和人工真值尚未提供。

## 自动化测试

执行命令：

```text
py -3 -m ruff check core tests
py -3 -m pytest -q
py -3 -m compileall -q core tests
```

实际结果：

```text
All checks passed!
35 passed in 5.48s
compileall exit 0
```

新增 `tests/media/test_detection.py` 的 7 项测试覆盖：硬切帧边界、黑场进出与人工审核标记、叠化中点吸附、0.2 秒短镜头保留、VFR/B 帧索引消费、版本化 JSON、无视频流结构化失败。样片由测试内 FFmpeg lavfi 生成，仅作为可重复算法回归，不等同于真实复杂素材通过。

## M1 补强状态

M1 原有 28 项测试全部保留并通过。负显示 PTS、卷级 ENOSPC、真实 Windows ACL 拒绝、长时 FFprobe/FFmpeg 外部强杀矩阵仍按 `docs/execution/ISSUES.md` 标记 BLOCKED；本次没有填满工作盘、修改系统 ACL 或删除原始媒体。现有 M1 取消令牌和子进程回收路径继续由原测试覆盖。

## 未解决事项

1. 没有真实婚礼样片和人工逐帧真值，无法报告冻结规格要求的硬切召回率、±1 帧定位率、闪光/摇镜误切率；该项 BLOCKED，不得在外部报告中写成 PASS。
2. 叠化/闪光/快速摇镜仅有低分辨率候选分类，最终仍需 M3 预览人工检查；若源流解码帧数与 M1 索引不一致，返回 `DETECTION_FRAME_MISMATCH` 并拒绝继续。
3. 叠化候选的 `review_required` 与黑场候选必须由 M3 持久化到编辑快照，重新检测不能覆盖用户已确认切点。

## 交给主控的契约提案

主控可直接集成 `detect_shots()` 和本模块 dataclasses；无需修改 `core/protocol/media.py`。若统一放入共享协议，建议迁移以下字段并保持 `m2.detection.v1`：`CutCandidate`、`ShotSegment`、`DetectionResult`、`DetectionConfig`，以及候选的 `review_required`、`transition_start_frame`、`transition_end_frame`。M3 应将 `DetectionResult.segments` 作为只读初始快照，用户确认/修改另存版本，不覆盖 M1 源身份和帧索引。
