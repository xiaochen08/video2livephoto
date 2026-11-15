# M4/M5 媒体导出与实况封装接口

本模块在 M1 `FrameRef` 显示帧契约上实现精准分段和本地 Live Photo 产物校验。视频处理始终通过参数数组调用冻结 FFmpeg/FFprobe，不把源媒体整体读入 Python 内存。

## M4 `encode_segment`

```python
from core.media.encode import SegmentEncodeResult, encode_segment

result = encode_segment(
    source_path,
    frames,                       # tuple[FrameRef, ...], display_index 连续
    start_display_index=0,
    end_display_index=30,         # 左闭右开
    output_path=output_mp4,
    audio_enabled=True,
    color_mode="auto",            # auto / sdr / hdr / warn
    prefer_gpu=True,
)
```

`FrameRef` 的 `best_effort_pts` 优先于 packet PTS，起止边界使用整数 time base。视频过滤器使用 `gte(pts,start)*lt(pts,end)`，输出验证会重新用 FFprobe 解码并比较帧数。音频使用独立的 `atrim`，不存在源音轨时保持静音输出；`audio_enabled=False` 时显式去除音轨。

GPU 编码器按 `h264_nvenc`、`h264_qsv`、`h264_amf` 顺序尝试，任何失败都会删除该临时结果并从源文件重新执行 CPU 编码（默认 `libx264`）。目标文件只在输出帧数、音轨和 FFprobe 解码检查通过后才发布；已有目标不会在失败路径被删除。

`color_mode="auto"` 对 HDR 元数据使用真实 `zscale + tonemap + format yuv420p` 转换为 Rec.709 SDR；未知 transfer/primaries 返回 `UNKNOWN_COLOR_METADATA`。`warn` 只用于人工确认的兼容路径并在结果中记录限制，不能视作已完成色彩验证。

## M5 `pack_live_photo`

```python
from core.livephoto.pack import pack_live_photo

result = pack_live_photo(
    segment_mp4,
    output_dir=output_dir,
    clip_id="clip-001",
    pairing_uuid="...",             # 可省略，自动生成 UUID
    still_image_time_seconds=0.0,
)
```

输出三件文件：`<base>.JPG`、`<base>.MOV`、`<base>.manifest.json`。JPG 封面从已编码片段第一显示帧提取，并写入原项目 Apple MakerNote `0x0011`。MOV 通过 FFmpeg `-c copy` 重封装，写入 `com.apple.quicktime.content.identifier` 与 `com.apple.quicktime.still-image-time` 的 QuickTime metadata。

manifest schema 版本为 `1`，至少包含：

- `clip_id`、大写 `pairing_uuid`、`still_image_time_seconds`；
- JPG/MOV 路径、字节数和 SHA-256；
- MOV 时长、视频帧数；
- `jpg_makernote_uuid`、`mov_content_identifier`、本地 FFprobe 流摘要；
- `timed_metadata_track` 与 `compatibility` 字段。

当前 `timed_metadata_track` 固定报告为 `false`：FFmpeg 写入的 moov metadata 与 JPEG MakerNote 已可由本地工具复核，但尚未证明 Apple `mebx` timed metadata 轨格式，也没有 iPhone 真机导入证据。因此不宣称 iPhone Photos、锁屏壁纸或社交平台兼容通过。

## 安全与失败语义

- 源视频只读；编码和封装均在 UUID 隔离 staging 目录完成。
- 源身份在编码前后复核，发现变化返回 `SOURCE_CHANGED`。
- 未通过验证时不发布任何目标文件；取消和 FFmpeg 失败保留旧产物。
- `replace=False` 是 M5 默认值，遇到同名 JPG/MOV/manifest 返回 `OUTPUT_EXISTS`。多文件安全替换由 M6 事务层负责。

## 已验证与待验证

已在本机验证 H.264 B 帧、VFR、无音轨/有音轨、GPU 编码器故障后 CPU 回退、HDR10→Rec.709 SDR、JPG/MOV 配对 UUID、哈希和 FFprobe 解码。100 段连续导出、复杂实拍婚礼素材、Apple timed metadata 轨和 iPhone 真机导入仍需由集成测试/外部设备验证。
