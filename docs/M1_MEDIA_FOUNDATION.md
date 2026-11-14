# M1 媒体基础层接口

M1 只负责本地媒体探测、源身份、显示帧时间索引、受限 fMP4 检查/规范化和隔离缓存。它不实现镜头检测、视频分段、编码、HDR 转换、Live Photo 封装、队列、界面或安装包。

## 入口

```text
python -m core.media.diagnostic probe <path>
python -m core.media.diagnostic index <path> --cache-root <cache>
python -m core.media.diagnostic inspect-fragments <path>
python -m core.media.diagnostic normalize <path> --cache-root <cache>
```

所有命令可以附带成对的 `--ffmpeg` 与 `--ffprobe` 路径。路径通过参数数组传给子进程，扩展名只作为筛选信息，实际格式来自容器探测。

## 缓存

帧索引写入 SQLite，不写入巨大 JSON，也不把所有帧长期保存在 Python 列表。缓存键包含源身份、工具链版本、工具 SHA-256、模式和缓存 schema 版本。索引建立中、取消或失败时状态为 `incomplete`，不能复用为完成索引。

## 时间轴

`FrameRef` 使用整数 PTS、整数 duration 和有理数 `time_base`。显示顺序由 FFprobe 解码帧输出决定；B 帧的 DTS、keyframe、pict_type 和 packet position 按可用性保存。缺失或非单调时间戳会进入诊断字段，不会被浮点秒数静默修正。

## fMP4

盒检查识别 `mvex` 和任意 `moof`，并拒绝损坏、截断、越界或过深的盒结构。正常 fMP4 可直接用 FFprobe 建立索引；需要规范化时只在唯一缓存目录内使用 FFmpeg `-c copy`，完成流集合、帧数量、PTS 序列和源身份复核后才提交缓存文件。
