import type { ColorInfo, VideoStreamInfo } from '@/domain/types'
import { rateToString } from '@/domain/time'

export function colorSummary(c: ColorInfo): string {
  if (c.dolby_vision) return 'Dolby Vision'
  switch (c.transfer) {
    case 'bt709':
      return 'SDR Rec.709'
    case 'hlg':
      return 'HDR HLG'
    case 'pq':
      return 'HDR PQ'
    case 'log':
      return `Log${c.log_profile ? ` (${c.log_profile})` : ''}`
    default:
      return '色彩信息未知'
  }
}

export function isHdr(c: ColorInfo) {
  return c.transfer === 'hlg' || c.transfer === 'pq' || c.dolby_vision
}

/** Plain-language colour limits shown next to quality settings. */
export function colorLimitNote(c: ColorInfo, hdrSupported: boolean): string | null {
  if (c.dolby_vision) return 'Dolby Vision 元数据不会保留；默认转换为 Rec.709 SDR。'
  if (c.transfer === 'pq' || c.transfer === 'hlg') {
    return hdrSupported ? `源为 ${c.transfer.toUpperCase()} HDR。默认转换为 Rec.709 SDR；手动保留 HDR 仅限后端已验证的范围。` : `源为 ${c.transfer.toUpperCase()} HDR。当前后端不支持 HDR 输出，将转换为 Rec.709 SDR。`
  }
  if (c.transfer === 'log') return 'Log 素材不会自动套用 LUT，输出保持源画面的 Log 观感。'
  if (c.transfer === 'unknown') return '源视频未标注色彩信息，按 Rec.709 处理。若画面偏色，请在剪辑软件中补充色彩标记后重新导入。'
  return null
}

export function streamSummary(s: VideoStreamInfo): string {
  return `${s.width}×${s.height} · ${rateToString(s.frame_rate)} fps · ${s.codec.toUpperCase()}`
}
