# M1 验收样片清单

以下路径位于隔离的 `F:\M1_samples` 或审计 fixture 目录。样片只读使用，M1 不覆盖源文件。

| 样片 | SHA-256 | 构造方式与用途 |
|---|---|---|
| `F:\M1_samples\neg_tests\edit_audio_offset.mp4` | `B8AEF8EF5456F3D01C148DE2E0ECC990DFC0AFBB43B0C6869CAF4DFC281276F1` | FFmpeg `testsrc2` 160x90/30fps + 48 kHz sine；音频 `adelay=500:all=1`；H.264 `-bf 2`、AAC。用于 `edts/elst`、负音频 PTS、负视频 DTS 和显示帧时间轴对照。 |
| `F:\M1_samples\multi\multi_video_attached_pic.mp4` | `50749A210DD348023119D98BDA055AFFB37FC412E806C2855822381B8B0AF957` | 两条默认 H.264 视频流加一条 JPEG/MJPEG `attached_pic` 流；用于主视频选择、附图流排除和歧义诊断。 |
| `F:\M1_samples\fmp4_av_1s.mp4` | `6A60AD77DE8D0E692AFC628DDE728C25075DD234882C868C0A4CDAD405EA08CD` | `testsrc2` + sine，`-movflags +frag_keyframe+empty_moov+default_base_moof`；用于 fMP4 `-c copy` 前后视频/音频时间映射。 |
| `E:\LIVE\_audit\fixtures\frag_h264_2s.mp4` | `6636B58B25662EBB9576074A67429A3AB210358C53FE961C2F2872D9281BDB31` | 既有 2 秒 H.264 fMP4；记录过视频 PTS 偏移 `-1024`。 |
| `F:\M1_samples\valid_4GiB_rawvideo.mov` | `8C519A99FF4F2AE817E748ED18B5E5AFF4F262D391DEFF993B3E5C2F098D7D9F` | 合法可解码 rawvideo MOV，4,478,978,897 字节、270 帧/9 秒；用于 4 GiB 级索引内存和源保护证据。原始生成脚本未纳入仓库。 |
| `F:\M1_samples\valid_4GiB_padded.mp4` | `21A1DB9595D8A543CB486FEF0E9463DD92CFBFF6636FA177EEF05B10F87846BB` | 4,295,060,242 字节的 MP4 容器填充样片；只证明 64 位盒尺寸/随机访问压力，不代表长片吞吐量。原始生成脚本未纳入仓库。 |
| `F:\M1_samples\hdr10_hevc_1s_v2.mp4` | `8D10CCBAF940AFB14EBEC51E8554224D33AFF261A48BA4992DC3685511E4C1C9` | HEVC Main10、`yuv420p10le`、BT.2020、SMPTE 2084；用于 HDR 元数据保留。 |
| `F:\M1_samples\short_0_2s.mp4` | `D6BCD067B54A825B6DD9497C484AEF3005FA4AB80E2FE4B332DE4538B56EB771` | 约 0.2 秒短片；用于短视频不被最短时长过滤。 |
| `F:\M1_samples\moof_without_mvex.mp4` | `80F7BCE27D5B22F7C781C23792FB7A5CF74F20D74BF583D50C961816B054E2F9` | 从合法 fMP4 将首个 `mvex` 标记替换为 `free`；用于 `moof`/`mvex` 不一致拒绝。 |

独立对照命令统一使用冻结 FFprobe：

```powershell
F:\DY60\ffmpeg-master-latest-win64-gpl-shared\bin\ffprobe.exe -v error -show_streams -show_frames -show_packets -of json <sample>
```

该命令只读样片；输出中的 PTS/DTS、`time_base`、包数和流 disposition 才是验收证据，构建成功本身不构成视频回归通过。
