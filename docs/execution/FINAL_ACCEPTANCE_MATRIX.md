# V1.0 最终内部验收矩阵

源码当前绑定：`ed115dfbe4318a0b069f3d8a66a645cc559d8d96`；R 复审报告绑定前一稳定候选 `589c41750f7c3ac3c7216c22dd3632b7638ef318`，复审后功能补强见 `docs/execution/POST_REVIEW_FUNCTIONAL.md`。

| 项目 | 状态 | 证据 |
|---|---|---|
| M1 媒体探测/帧索引/缓存 | PASS（合成与既有 M1 样片）；真实负显示 PTS、ACL、卷级 ENOSPC、外部强杀仍 BLOCKED | `docs/M1_IMPLEMENTATION_REPORT.md`、`docs/M1_FIXTURE_MANIFEST.md`、77 项 Python 回归 |
| M2 硬切/黑场/叠化/短镜头 | PASS（合成回归）；真实婚礼 10 条人工真值和召回率目标 BLOCKED | `docs/M2_DETECTION_REPORT.md` |
| M3 导入/时间线/逐帧预览/审核 | PASS（Python/IPC/renderer build）；目标 Windows 原生窗口人工验收仍需外部执行 | `docs/M3_DESKTOP.md`、`delivery/v1.0/evidence/m3-empty-import-screen.png` |
| M4 精准编码/音频/色彩 | PASS（VFR、B 帧、音频开关、GPU 回退、HDR10 合成样片）；复杂婚礼长片 BLOCKED | `docs/M4_M5_MEDIA_EXPORT.md`、`tests/media/test_encode.py` |
| M5 JPG/MOV 配对和本地校验 | PASS（UUID、MakerNote、哈希、ffprobe、mebx timed metadata、still-image-time）；iPhone 真机 BLOCKED | `docs/M4_M5_MEDIA_EXPORT.md`、`tests/media/test_livephoto.py` |
| M6 队列/暂停/取消/重试/恢复/安全提交 | PASS（SQLite、快照去重、确认恢复、事务恢复回归）；真实断电、ACL、卷级空间不足 BLOCKED | `docs/M6_QUEUE.md`、`tests/queue/`、`tests/commit/`、`tests/desktop/test_ipc.py` |
| M7 Windows 候选 | PASS（NSIS、win-unpacked、ZIP、sidecar ping、许可证清单）；未签名、安装卸载需目标机外部验收 | `docs/M7_PACKAGING.md`、`docs/execution/POST_REVIEW_PACKAGING.md` |
| 独立复审 | `589c417` 首轮 CONDITIONAL PASS；`ed115df` 复审后功能补强无新 P0/P1，外部交付仍 BLOCKED | `docs/execution/INTERNAL_REVIEW_FINAL.md`、`docs/execution/INTERNAL_REVIEW_POST_FUNCTIONAL.md` |

## 固定执行结果

```text
py -3 -m pytest -q                         PASS  77 passed in 16.96s
py -3 -m compileall -q core desktop tests packaging  PASS
py -3 -m ruff check core desktop tests packaging    PASS
npm run build                              PASS
npm run selftest                           PASS  M3 IPC selftest PASS m3-python
npx tsc --noEmit                           PASS
py -3 -m packaging.build_candidate inspect --project .  PASS missing=[]
packaged sidecar JSONL ping                PASS {"ok":true,"protocol":"m3.ipc.v1","service":"m3-python"}
npm audit --audit-level=high               FAIL/OPEN 13 vulnerabilities (3 moderate, 9 high, 1 critical)
```

