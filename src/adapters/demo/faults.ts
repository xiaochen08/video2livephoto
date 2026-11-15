/** DEMO fault-injection switches (演示故障注入). Persisted in sessionStorage so resets are repeatable. */
export interface DemoFaults {
  frameLatency: boolean
  frameFail: boolean
  previewBroken: boolean
  saveFailNext: boolean
  saveSlow: boolean
  rejectNextMove: boolean
  analysisFail: boolean
  proxySlow: boolean
  previewPartial: boolean
  gpuFallback: boolean
  diskFull: boolean
  fileLocked: boolean
  commitInterrupt: boolean
  eventChaos: boolean
  preflightDiskFull: boolean
  recoveryInspectFail: boolean
  limitedCaps: boolean
  speed: number
}

export const DEFAULT_FAULTS: DemoFaults = {
  frameLatency: false,
  frameFail: false,
  previewBroken: false,
  saveFailNext: false,
  saveSlow: false,
  rejectNextMove: false,
  analysisFail: false,
  proxySlow: false,
  previewPartial: false,
  gpuFallback: true,
  diskFull: true,
  fileLocked: false,
  commitInterrupt: false,
  eventChaos: false,
  preflightDiskFull: false,
  recoveryInspectFail: false,
  limitedCaps: false,
  speed: 1,
}

export type BoolFault = Exclude<keyof DemoFaults, 'speed'>

export const FAULT_META: { key: BoolFault; label: string; group: string; hint: string }[] = [
  { key: 'frameLatency', group: '预览', label: '帧请求随机延迟 0–900ms', hint: '用于验证快速切换片段时旧请求不会覆盖当前画面' },
  { key: 'frameFail', group: '预览', label: '当前帧读取失败（30%）', hint: '显示具体重试入口' },
  { key: 'previewBroken', group: '预览', label: '预览代理失效', hint: '视频区域显示媒体失败状态' },
  { key: 'saveFailNext', group: '项目', label: '下一次保存失败', hint: '一次性' },
  { key: 'saveSlow', group: '项目', label: '保存回执随机延迟（乱序）', hint: '验证旧回执不会覆盖新编辑版本' },
  { key: 'rejectNextMove', group: '项目', label: '下一次移动切点被后端拒绝', hint: '一次性；列表/时间线/预览恢复到确认状态' },
  { key: 'analysisFail', group: '分析', label: '镜头分析工作进程退出', hint: '在 60% 处失败' },
  { key: 'proxySlow', group: '分析', label: '预览代理准备较慢', hint: '' },
  { key: 'previewPartial', group: '分析', label: '部分缩略图生成失败', hint: '' },
  { key: 'gpuFallback', group: '导出', label: 'GPU 失败回退 CPU（第 1 个较长片段）', hint: '' },
  { key: 'diskFull', group: '导出', label: '磁盘已满（第 3 个片段）', hint: '' },
  { key: 'fileLocked', group: '导出', label: '文件被占用（第 4 个片段，提交阶段）', hint: '' },
  { key: 'commitInterrupt', group: '导出', label: '提交阶段中断（第 5 个片段）', hint: '模拟提交时进程中断 → 待核查' },
  { key: 'eventChaos', group: '导出', label: '任务事件重复 / 乱序 / 丢失', hint: '验证序号过滤与快照重同步' },
  { key: 'preflightDiskFull', group: '导出', label: '预检：目标盘空间不足', hint: '' },
  { key: 'recoveryInspectFail', group: '恢复', label: '恢复检查读取失败', hint: '' },
  { key: 'limitedCaps', group: '能力', label: '能力不足：无 GPU 路径、无 HDR 输出', hint: '需刷新后生效' },
]

const KEY = 'v2lp.demo.faults'

export function loadFaults(): DemoFaults {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (raw) return { ...DEFAULT_FAULTS, ...JSON.parse(raw) }
  } catch {
    /* sessionStorage unavailable (tests) */
  }
  return { ...DEFAULT_FAULTS }
}

export function saveFaults(f: DemoFaults) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(f))
  } catch {
    /* ignore */
  }
}
