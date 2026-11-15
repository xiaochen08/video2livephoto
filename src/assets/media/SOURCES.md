# 演示媒体来源与授权

`demo-landscape.mp4`（640×360，25fps，1650 帧，66.00 秒，AAC 单声道合成音）与
`demo-portrait.mp4`（360×640，30000/1001 fps，420 帧，无音轨）由 `scripts/make-demo-media.sh`
用以下 Unsplash 照片经 ffmpeg 平移/裁切/叠化/闪光合成。音频为 ffmpeg `aevalsrc` 生成的正弦和弦，无第三方版权。

照片遵循 Unsplash License（https://unsplash.com/license）：可免费用于商业与非商业用途，无需署名（此处仍保留署名）。
不得将这些照片原样打包出售或用于建立竞争性图库服务。

| 用途 | 作者 | Unsplash 照片 ID |
| --- | --- | --- |
| 镜头 1 街景 | Jakob Owens | 1606217239582-d9f72323bcd7 |
| 镜头 2 走道 | Kari Bjorn Photography | 1731515672817-0491d19c9f19 |
| 镜头 3 牵手（0.2 秒） | Stacie Ong | 1672288336066-8cd91b57b510 |
| 镜头 4 戒指（黑白） | Cinematic Imagery | 1523369579000-4ec0fe04db44 |
| 镜头 5 捧花 | Naeem Ad | 1726751151542-1c578a3b68ae |
| 镜头 6 合影（0.8 秒） | Micah & Sammie Chaffin | 1740688055196-a836abca5518 |
| 镜头 7 新人（含闪光） | SB Film Studio | 1743684821666-05b9c5046937 |
| 镜头 8 合影 | Naeem Ad | 1726751151351-c27ac5ee81ed |
| 镜头 9 吊灯长镜头（31 秒） | Jennifer Kalenberg | 1723832347953-83c28e2d4dd2 |
| 镜头 10 草地 | Michael McAuliffe | 1631225893179-4d6e349189c2 |
| 竖屏 1 | Lori DeJong | 1679599441412-5e42d65e6c09 |
| 竖屏 2（0.4 秒） | Marius Muresan | 1671183384203-98c6af4f88f7 |
| 竖屏 3 | Taine Noble | 1632094883001-95d5e2e18d79 |
| 竖屏 4 | Michael McAuliffe | 1631225893179-4d6e349189c2 |

演示素材中「入场」「交换戒指」等片段名为示例命名（`name_origin: 'example'`），不代表真实分析结果。
正式交付若不希望携带演示素材，删除本目录并在 DemoAdapter 中改用替代帧即可（替代帧路径已实现，见 150 镜头项目）。
