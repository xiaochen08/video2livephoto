/** Demo metadata without media imports, so desktop builds never pull in the DemoAdapter or sample videos. */
export const DEMO_SCENARIOS = [
  { id: 'full', label: '完整演示（全部示例项目）' },
  { id: 'first_run', label: '首次使用 / 无最近项目' },
] as const
export type DemoScenarioId = (typeof DEMO_SCENARIOS)[number]['id']

export const DEMO_SAMPLES = [
  { ref_id: 'sample:landscape', name: '婚礼成片_示例.mp4', note: '横屏 25fps · 多镜头' },
  { ref_id: 'sample:single', name: '酒店外景_单镜头.mp4', note: '无切点' },
  { ref_id: 'sample:portrait', name: '花絮_竖屏.mov', note: '竖屏 · 无音轨' },
  { ref_id: 'sample:hdr', name: 'HLG_测试片.mov', note: 'HDR / 未知色彩' },
  { ref_id: 'sample:multistream', name: '双视频流_相机原片.mov', note: '需选择视频流' },
] as const
