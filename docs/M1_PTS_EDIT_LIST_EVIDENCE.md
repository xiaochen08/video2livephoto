# M1 负 PTS、edit list 与 fMP4 时间映射证据

本记录只覆盖 M1 媒体基础层。它不证明 Live Photo 兼容性，也不替代真实复杂素材回归。

## 样片构造

`tests/conftest.py::negative_pts_edit_list_mp4` 在测试运行时用本机 `ffmpeg` 构造 H.264/AAC MP4：

```text
ffmpeg -f lavfi -i testsrc2=size=160x90:rate=30 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 -t 1 \
  -filter_complex "[1:a]adelay=500:all=1[a]" -map 0:v -map "[a]" \
  -c:v libx264 -bf 2 -pix_fmt yuv420p -c:a aac <temporary-file>.mp4
```

该样片的 MP4 盒中包含 `edts`/`elst`。AAC 编码器前置样本产生真实负音频 PTS，独立 FFprobe 的首个音频包为 `pts=-1024`、`dts=-1024`；这不是把视频 PTS 人为改成负数。

## 独立时间轴对照

测试命令：

```text
py -3 -m pytest -q tests/media/test_pts_edit_list.py
```

当前本地结果：`2 passed`。

`test_negative_pts_edit_list_display_timeline_matches_independent_decoders` 同时运行：

- FFprobe `-show_frames`，读取视频 `pts`、`best_effort_timestamp` 和显示顺序；
- FFmpeg `showinfo` 逐帧解码，读取输出帧 PTS；
- M1 SQLite 帧索引。

测试要求三者的帧数量、整数 PTS 和显示顺序完全一致，并单独核对负音频 PTS 与 edit list 盒标记。视频显示 PTS 当前从 0 开始，不能据此推断所有素材的负视频 PTS 均已覆盖。

## fMP4 `-c copy` 映射

`test_fmp4_copy_normalization_preserves_display_frames_and_reports_mapping` 使用 `fragmented_av_mp4`，执行 M1 的无重编码规范化，然后独立 FFprobe 对规范化前后的视频帧逐帧比较：

- 帧数必须相同；
- 每一帧的 PTS 差值必须是单一常数；
- 源与规范化视频时基必须相同；
- `NormalizedMediaRef.validation.source_to_normalized_pts_offset` 必须等于独立帧序列计算出的常数；
- 音频包数量和音频 PTS 偏移由现有 `audio_timeline` 校验记录。

在本机 FFmpeg `N-120646-g6711c6a89b-20250810` 的一次运行中，合成 fMP4 的视频 PTS 差值为 `-10`（时基 `1/15360`），音频包 PTS 偏移为 `0`。该数值是样片和工具版本相关的观测，不应替代真实相机素材的证据；若其他样片出现 `-1024`，应以同一方法保存并解释其所在流和时基。

## 尚未取得的证据

- **真实负视频显示 PTS：BLOCKED / UNVERIFIED。** 当前仓库没有可复核的相机样片；本机 FFmpeg 对 `setpts=PTS-…` 的 MP4 输出会通过 muxer/edit list 重新基准化，未得到保留负视频显示 PTS 的真实文件。不能把负音频 PTS 证据冒充负视频 PTS 通过。
- **真实 4 GiB 以上素材及复杂相机 edit list：** 由 M1 总验收矩阵另行登记；本测试文件只验证合成样片的时间轴关系。

