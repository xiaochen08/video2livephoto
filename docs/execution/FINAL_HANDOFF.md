# Video2LivePhoto V1.0 内部交付包

## 绑定版本

- 分支：`codex/v1-integration`
- 最终集成代码与测试提交：`589c41750f7c3ac3c7216c22dd3632b7638ef318`
- 原始 main：`e6231886298e0a4bccf0e6591784a2fdba736db6`
- M0/M1 承接：`a8dbc02bd56e63c0c71e9094858cc0e87611bdd6`
- 原始 main、M0 审计克隆、源视频均保留，未推送远端。

## Windows 候选

- NSIS：`delivery/v1.0/nsis-attempt/Video2LivePhoto Setup 1.0.0-candidate.exe`
  - SHA-256：`AEE9047007C424EEB14238FADECF66248DEDE9ED64642FE3650F93016D4B04E1`
- 离线解压候选：`delivery/v1.0/Video2LivePhoto-1.0.0-final-candidate-win-unpacked.zip`
  - SHA-256：`B9470022CB68021F6634B63393DCCA75D066B25A06FF533397769B5BF83764CE`
- Python sidecar：`2E8074C661DA460EB4DCF0E492A2FBFC02B1B3DEF5E3F8C7D1EA0AF366929668`
- bundled FFmpeg：`6632B01B7981092AF425787CD16DDF6449E7BD634AE756398BF4189DB8C42482`
- bundled FFprobe：`C2AD6060AE546E850E436A79786FDC68C8ACC623C283D38E225B0E13163B6446`

sidecar 直接以 JSONL `ping` 启动返回 `m3-python`；候选包包含 `THIRD_PARTY_LICENSES.json` 和 `CANDIDATE_SHA256.txt`。

## 真实样片与构造证据

样片路径、SHA-256 和构造方式见 `docs/M1_FIXTURE_MANIFEST.md`。其中包括 VFR、B 帧、负音频 PTS/edit list、fMP4、HDR10、0.2 秒短片、多视频/附图流以及 4 GiB 级文件。合成样片只证明对应媒体机制，不能替代复杂婚礼真值或 iPhone 真机验证。

## 审计与复审

- 首轮独立审查报告固定在 `E:\\LIVE\\_audit\\video2livephoto-review` 分支提交 `dde99d5`，发现的 P0/P1 已在后续提交修复；最终复审报告为 `c25cc115`，绑定 `589c417`，结论为源码/自动化 CONDITIONAL PASS、外部交付 BLOCKED。
- 复审后候选包补证见 `docs/execution/POST_REVIEW_PACKAGING.md`；安装器和 ZIP 都从 `589c417` 代码重新冻结，但尚未在独立目标 Windows 机完成安装/卸载全流程。
- 完整测试矩阵见 `docs/execution/FINAL_ACCEPTANCE_MATRIX.md`；限制和阻塞见 `docs/execution/KNOWN_LIMITATIONS.md`。

