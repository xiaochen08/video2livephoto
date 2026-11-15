<script setup lang="ts">
import { Download, RefreshCw } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { useApp } from '@/app/context'
import type { AppSettings, CacheInfo, DiagnosticsInfo } from '@/adapters/contract'
import ParamRow from '@/components/ParamRow.vue'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import UiCheckbox from '@/components/UiCheckbox.vue'
import UiSegmented from '@/components/UiSegmented.vue'
import UiSelect from '@/components/UiSelect.vue'
import UiTextField from '@/components/UiTextField.vue'
import { SHORTCUTS } from '@/app/shortcuts'
import { toAppError } from '@/domain/errors'
import { formatBytes, formatClock } from '@/domain/time'

const { ui, adapter, prefs, conn } = useApp()
const sections = [
  { id: 'export', label: '导出默认' },
  { id: 'preview', label: '预览与缓存' },
  { id: 'shortcuts', label: '快捷键' },
  { id: 'diagnostics', label: '诊断' },
  { id: 'about', label: '关于' },
] as const
const settings = ref<AppSettings | null>(null)
const cache = ref<CacheInfo | null>(null)
const diag = ref<DiagnosticsInfo | null>(null)
const logs = ref<string[]>([])
const clearSel = ref<string[]>([])
const busy = ref<string | null>(null)
const includePaths = ref(false)

async function load() {
  try {
    settings.value = await adapter.settings.get()
    cache.value = await adapter.settings.cacheInfo()
    diag.value = await adapter.diagnostics.info()
    logs.value = await adapter.diagnostics.logs(200)
  } catch (e) {
    ui.toast(toAppError(e).message, { tone: 'danger' })
  }
}
onMounted(load)
watch(() => ui.state.settingsSection, (s) => s === 'diagnostics' && load())

async function save(patch: Partial<AppSettings>) {
  busy.value = 'save'
  try {
    settings.value = await adapter.settings.update(patch)
  } catch (e) {
    ui.toast(toAppError(e).message, { tone: 'danger' })
  } finally {
    busy.value = null
  }
}
const clearBytes = computed(() => (cache.value?.items ?? []).filter((i) => clearSel.value.includes(i.id)).reduce((a, i) => a + Number(i.size_bytes), 0))
async function clear() {
  const ok = await ui.confirm({
    title: '清理所选缓存？',
    message: `将清理约 ${formatBytes(clearBytes.value)}。之后打开项目时会重新生成预览与缩略图。`,
    detail: '源视频、导出结果与正在被任务使用的临时文件不在清理范围内。',
    confirmLabel: '清理',
  })
  if (!ok) return
  busy.value = 'clear'
  try {
    const r = await adapter.settings.clearCache(clearSel.value)
    ui.toast(`已清理 ${formatBytes(r.freed_bytes)}${adapter.mode === 'demo' ? '（模拟）' : ''}`, { tone: 'success' })
    clearSel.value = []
    cache.value = await adapter.settings.cacheInfo()
  } finally {
    busy.value = null
  }
}
async function exportBundle() {
  busy.value = 'bundle'
  try {
    const r = await adapter.diagnostics.exportBundle({ include_paths: includePaths.value })
    ui.toast(`诊断包：${r.saved_to}`, { tone: 'success', timeout: 5000 })
  } catch (e) {
    ui.toast(toAppError(e).message, { tone: 'danger' })
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="set">
    <nav class="set__nav" aria-label="设置分类">
      <button v-for="s in sections" :key="s.id" type="button" class="set__nav-item" :aria-current="ui.state.settingsSection === s.id ? 'page' : undefined" @click="ui.state.settingsSection = s.id">{{ s.label }}</button>
    </nav>
    <div class="set__body">
      <section v-if="ui.state.settingsSection === 'export' && settings" class="set__sec">
        <h2>导出默认</h2>
        <p class="small muted">打开项目时使用这些默认值；每次导出时仍可在确认页修改。</p>
        <UiTextField :model-value="settings.default_output_dir" label="默认保存位置" mono commit-on-blur @commit="(v) => save({ default_output_dir: v })" />
        <div class="set__grid">
          <UiSelect :model-value="settings.default_quality" label="画质" :options="[{ value: 'source', label: '与源一致（推荐）' }, { value: 'high', label: '高画质' }, { value: 'compact', label: '节省空间' }]" @update:model-value="(v) => save({ default_quality: v })" />
          <UiSelect
            :model-value="settings.default_color"
            label="色彩"
            :options="[{ value: 'sdr_rec709', label: 'Rec.709 SDR（默认）' }, { value: 'hdr_keep', label: '保留 HDR（需后端支持）', disabled: !conn?.capabilities.hdr_output.supported }]"
            @update:model-value="(v) => save({ default_color: v })"
          />
        </div>
        <p class="small muted">每次导出会在此位置创建独立的“livephotos 项目名 时间戳”文件夹，内部包含 LivePhoto/（JPG + MOV）、视频片段/（MP4）、导出报告与版本化清单。</p>
      </section>

      <section v-else-if="ui.state.settingsSection === 'preview'" class="set__sec">
        <h2>预览与缓存</h2>
        <div class="set__grid" v-if="settings">
          <UiSelect :model-value="settings.proxy_resolution" label="预览代理分辨率" :options="[{ value: '540p', label: '540p（省空间）' }, { value: '720p', label: '720p（推荐）' }, { value: '1080p', label: '1080p' }]" @update:model-value="(v) => save({ proxy_resolution: v })" />
          <UiSelect :model-value="String(settings.cache_limit_gb)" label="缓存上限" :options="['10', '20', '50'].map((v) => ({ value: v, label: `${v} GB` }))" @update:model-value="(v) => save({ cache_limit_gb: Number(v) })" />
        </div>
        <div class="set__row">
          <span class="small">减少动态效果</span>
          <UiSegmented v-model="prefs.reduceMotion" size="sm" aria-label="减少动态效果" :options="[{ value: 'system', label: '跟随系统' }, { value: 'on', label: '开启' }, { value: 'off', label: '关闭' }]" />
        </div>
        <h3 class="section-title">清理缓存</h3>
        <ul v-if="cache" class="cache">
          <li v-for="i in cache.items" :key="i.id" class="cache__item">
            <UiCheckbox :checked="clearSel.includes(i.id)" :disabled="!i.clearable" :label="i.label" @change="(v) => (clearSel = v ? [...clearSel, i.id] : clearSel.filter((x) => x !== i.id))" />
            <span class="small muted num">{{ Number(i.size_bytes) ? formatBytes(i.size_bytes) : '' }}</span>
            <span v-if="i.protected_reason" class="small cache__lock">受保护：{{ i.protected_reason }}</span>
          </li>
        </ul>
        <UiButton :disabled="!clearSel.length" disabled-reason="请先勾选要清理的项目" :loading="busy === 'clear'" loading-label="正在清理…" @click="clear">清理所选（{{ formatBytes(clearBytes) }}）</UiButton>
      </section>

      <section v-else-if="ui.state.settingsSection === 'shortcuts'" class="set__sec">
        <h2>快捷键</h2>
        <dl class="set__keys">
          <div v-for="k in SHORTCUTS" :key="k.id"><dt class="small muted">{{ k.scope }}</dt><dd><span class="kbd">{{ k.keys }}</span> {{ k.label }}</dd></div>
        </dl>
      </section>

      <section v-else-if="ui.state.settingsSection === 'diagnostics'" class="set__sec">
        <h2>诊断</h2>
        <dl v-if="diag" class="set__dl">
          <ParamRow label="运行模式" :value="diag.mode === 'demo' ? '演示（所有后端能力为模拟）' : '桌面'" />
          <ParamRow label="应用版本" :value="diag.app_version" mono />
          <ParamRow label="后端版本" :value="diag.backend_version" mono />
          <ParamRow label="界面构建" :value="diag.ui_build" mono />
          <ParamRow label="精确帧预览" :value="diag.capabilities.frame_accurate_preview ? '后端提供' : '未提供（浏览器定位近似）'" />
          <ParamRow label="GPU 编码" :value="diag.capabilities.gpu.available ? diag.capabilities.gpu.verified_encoder : diag.capabilities.gpu.note" />
          <ParamRow label="HDR 输出" :value="diag.capabilities.hdr_output.note ?? (diag.capabilities.hdr_output.supported ? '支持' : '不支持')" />
          <ParamRow label="并行片段上限" :value="diag.capabilities.max_parallel_jobs" mono />
          <ParamRow v-for="w in diag.workers" :key="w.name" :label="w.name" :value="w.status" />
        </dl>
        <h3 class="section-title">最近错误</h3>
        <ul class="set__errs small">
          <li v-for="e in diag?.recent_errors ?? []" :key="e.at + e.code"><span class="mono">{{ e.code }}</span> {{ e.message }} <span class="muted">· {{ e.scope }} · {{ formatClock(e.at) }}</span></li>
          <li v-if="!diag?.recent_errors.length" class="muted">没有记录</li>
        </ul>
        <h3 class="section-title set__logs-title">日志（最近 200 行） <UiButton size="sm" variant="ghost" :icon="RefreshCw" @click="load">刷新</UiButton></h3>
        <pre class="set__logs mono small">{{ logs.join('\n') || '（空）' }}</pre>
        <UiBanner tone="info" compact>诊断包只保存在本机。默认不包含文件路径；上传或发送给他人需要你自己决定。</UiBanner>
        <div class="set__row">
          <UiCheckbox :checked="includePaths" label="包含文件路径（可能含客户姓名等信息）" @change="(v) => (includePaths = v)" />
          <UiButton :icon="Download" :loading="busy === 'bundle'" loading-label="正在导出…" @click="exportBundle">导出诊断包</UiButton>
        </div>
      </section>

      <section v-else-if="ui.state.settingsSection === 'about'" class="set__sec">
        <h2>关于</h2>
        <dl class="set__dl">
          <ParamRow label="产品" value="Video2LivePhoto · Windows 本地工具" />
          <ParamRow label="界面版本" value="0.1.0-ui" mono />
          <ParamRow label="后端" :value="conn?.backend_version ?? '未连接'" mono />
        </dl>
        <p class="small muted">核心流程离线可用；不会上传视频、文件路径或日志。演示素材照片来自 Unsplash（Unsplash License），见 src/assets/media/LICENSE.md。</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.set {
  height: 100%;
  display: grid;
  grid-template-columns: 210px minmax(0, 1fr);
  gap: var(--gap);
  padding: 0 var(--gap) var(--gap);
  min-height: 0;
}
.set__nav {
  padding: 14px 8px;
  border-radius: var(--r-4);
  box-shadow: var(--panel-edge);
  background: var(--bg-panel);
  display: grid;
  align-content: start;
  gap: 2px;
}
.set__nav-item {
  text-align: left;
  padding: 7px 12px;
  border-radius: var(--r-2);
  color: var(--text-2);
  font-size: var(--fs-13);
}
.set__nav-item:hover {
  background: var(--bg-raised);
  color: var(--text-1);
}
.set__nav-item[aria-current='page'] {
  background: var(--accent-soft);
  color: var(--text-1);
}
.set__body {
  overflow-y: auto;
  padding: 24px 32px;
  border-radius: var(--r-4);
  box-shadow: var(--panel-edge);
  background: var(--bg-panel);
}
.set__sec {
  max-width: 720px;
  display: grid;
  gap: 14px;
}
.set__sec h2 {
  font-size: var(--fs-16);
  font-weight: var(--fw-semibold);
}
.set__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.set__row {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: space-between;
}
.cache {
  display: grid;
  gap: 4px;
}
.cache__item {
  display: grid;
  grid-template-columns: 1fr 90px;
  gap: 4px 8px;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid var(--line-subtle);
}
.cache__lock {
  grid-column: 1 / -1;
  color: var(--text-3);
  padding-left: 24px;
}
.set__dl {
  display: grid;
  gap: 2px;
}
.set__keys div {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 8px;
  padding: 4px 0;
  font-size: var(--fs-13);
}
.set__errs {
  display: grid;
  gap: 4px;
}
.set__logs-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.set__logs {
  max-height: 240px;
  overflow: auto;
  padding: 10px;
  background: var(--bg-well);
  border: 1px solid var(--line-subtle);
  border-radius: var(--r-2);
  white-space: pre-wrap;
  user-select: text;
  color: var(--text-2);
}
</style>
