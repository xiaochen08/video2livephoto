<script setup lang="ts">
import { FolderOpen, RotateCcw, ShieldCheck, Upload, Folder, FileText, FileJson } from 'lucide-vue-next'
import { computed, reactive, ref, watch } from 'vue'
import { useActions, useApp } from '@/app/context'
import type { PreflightResult } from '@/adapters/contract'
import UiBanner from '@/components/UiBanner.vue'
import UiButton from '@/components/UiButton.vue'
import UiCheckbox from '@/components/UiCheckbox.vue'
import UiDialog from '@/components/UiDialog.vue'
import UiSelect from '@/components/UiSelect.vue'
import UiSpinner from '@/components/UiSpinner.vue'
import UiTextField from '@/components/UiTextField.vue'
import { CUT_KIND_LABEL } from '@/domain/clipHints'
import { isAbort, toAppError } from '@/domain/errors'
import { requestId } from '@/domain/ids'
import { checkNameBase, checkOutputPath, fileStem, sanitizeForFileName } from '@/domain/naming'
import { formatBytes } from '@/domain/time'
import type { ExportColor, ExportQuality } from '@/domain/types'
import { colorLimitNote, colorSummary, isHdr } from '@/features/editor/mediaText'

const { ui, session, tasks, adapter, conn } = useApp()
const actions = useActions()
const open = ui.dialogs.exportConfirm
const p = session.project
const s = session.stream
const caps = computed(() => conn.value?.capabilities)

const form = reactive({ output_dir: '', name_base: '', quality: 'source' as ExportQuality, color: 'sdr_rec709' as ExportColor })
const folderTimestamp = ref('')
const ack = reactive({ unreviewed: false, modified: false })
const preflight = ref<PreflightResult | null>(null)
const preflightError = ref<string | null>(null)
const checking = ref(false)
const submitting = ref(false)
const submitError = ref<string | null>(null)
let rid = requestId('export')
let ctrl: AbortController | null = null
let seq = 0
let debounce: ReturnType<typeof setTimeout> | null = null

const clips = computed(() => (session.timeline.value?.clips ?? []).filter((c) => c.export_selected))
const total = computed(() => session.timeline.value?.clips.length ?? 0)
const ids = computed(() => clips.value.map((c) => c.clip_id))
const pendingCuts = session.pendingCuts
const pendingByKind = computed(() => {
  const m = new Map<string, number>()
  for (const c of pendingCuts.value) m.set(CUT_KIND_LABEL[c.kind], (m.get(CUT_KIND_LABEL[c.kind]) ?? 0) + 1)
  return [...m.entries()].map(([k, v]) => `${k} ${v}`).join('、')
})
const affectedByPending = computed(() => clips.value.filter((c) => (session.hints.value.get(c.clip_id) ?? []).includes('review')).length)
const hintCounts = computed(() => {
  let short = 0
  let long = 0
  for (const c of clips.value) {
    const h = session.hints.value.get(c.clip_id) ?? []
    if (h.includes('short')) short++
    if (h.includes('long')) long++
  }
  return { short, long }
})
const coverIssues = computed(() => clips.value.filter((c) => c.cover.status === 'out_of_range').length)
const muted = computed(() => clips.value.filter((c) => c.audio === 'muted').length)

const stems = computed(() => clips.value.map((c) => fileStem(form.name_base || '未命名', c.display_index)))
const nameIssues = computed(() => checkNameBase(form.name_base))
const longest = computed(() => stems.value.reduce((a, b) => (b.length > a.length ? b : a), '') + '.mov')
const batchFolder = computed(() => `livephotos ${sanitizeForFileName(p.value?.name || '项目')} ${folderTimestamp.value || '时间戳'}`)
const pathIssues = computed(() => checkOutputPath(form.output_dir, longest.value, batchFolder.value))
const localErrors = computed(() => [...nameIssues.value, ...pathIssues.value].filter((i) => i.level === 'error'))
const backendErrors = computed(() => preflight.value?.issues.filter((i) => i.level === 'error') ?? [])
const needsModifiedAck = computed(() => (preflight.value?.existing_outputs.externally_modified ?? 0) > 0)
const hdrSource = computed(() => !!s.value && isHdr(s.value.color))

const blockReason = computed(() => {
  if (!clips.value.length) return '没有参与导出的片段'
  if (localErrors.value.length) return localErrors.value[0].message
  if (checking.value) return '正在检查目标位置'
  if (preflightError.value) return '预检失败，请重试检查'
  if (backendErrors.value.length) return backendErrors.value[0].message
  if (pendingCuts.value.length && !ack.unreviewed) return '请先返回检查，或确认继续导出未检查的切点'
  if (needsModifiedAck.value && !ack.modified) return '请确认如何处理被外部修改的旧输出'
  if (tasks.busy(`export:${p.value?.project_id}`)) return '导出请求处理中'
  return null
})

watch(open, (v) => {
  if (!v || !p.value) return
  const now = new Date()
  folderTimestamp.value = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('') + '_' + [String(now.getHours()).padStart(2, '0'), String(now.getMinutes()).padStart(2, '0'), String(now.getSeconds()).padStart(2, '0')].join('')
  const es = p.value.export_settings
  Object.assign(form, { output_dir: es.output_dir, name_base: es.name_base, quality: es.quality, color: es.color })
  ack.unreviewed = false
  ack.modified = false
  submitError.value = null
  rid = requestId('export')
  runPreflight(0)
})
watch(
  () => [form.output_dir, form.name_base, form.quality, form.color, p.value?.edit_version],
  () => {
    if (!open.value) return
    rid = requestId('export') // a changed request is a new intent
    runPreflight(400)
  },
)

function runPreflight(delay: number) {
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(async () => {
    if (!p.value || localErrors.value.length) {
      preflight.value = null
      return
    }
    ctrl?.abort()
    const c = (ctrl = new AbortController())
    const mine = ++seq
    checking.value = true
    preflightError.value = null
    try {
      const res = await adapter.export.preflight(p.value.project_id, p.value.edit_version, ids.value, { ...p.value.export_settings, ...form }, c.signal)
      if (mine !== seq) return // an older check finishing late never replaces a newer one
      preflight.value = res
    } catch (e) {
      if (mine !== seq || isAbort(e)) return
      preflightError.value = toAppError(e).message
    } finally {
      if (mine === seq) checking.value = false
    }
  }, delay)
}

async function browse() {
  const dir = await adapter.files.pickOutputDir()
  if (dir) form.output_dir = dir
}

async function submit() {
  const proj = p.value
  if (!proj || blockReason.value) return
  submitting.value = true
  submitError.value = null
  try {
    const res = await tasks.once(`export:${proj.project_id}`, () =>
      tasks.createBatch(
        {
          project_id: proj.project_id,
          edit_version: proj.edit_version,
          clip_ids: ids.value,
          settings: { ...proj.export_settings, ...form },
          acknowledged: { unreviewed_cuts: ack.unreviewed, livephoto_hints: true, replace_existing: true },
        },
        rid,
      ),
    )
    if (!res) return // duplicate click while in flight
    session.project.value = { ...session.project.value!, export_settings: { ...proj.export_settings, ...form } }
    open.value = false
    ui.state.tasksTab = 'queue'
    ui.state.route = 'tasks'
    ui.toast(`已创建导出批次：${ids.value.length} 个片段，使用编辑快照 v${proj.edit_version}${res.deduplicated ? '（重复请求已合并）' : ''}`, { tone: 'success' })
  } catch (e) {
    submitError.value = toAppError(e).message
  } finally {
    submitting.value = false
  }
}

function backToReview() {
  open.value = false
  actions.startReview()
}
</script>

<template>
  <UiDialog :open="open" title="确认导出" :description="p ? `${p.name} · 编辑版本 v${p.edit_version}` : undefined" size="lg" :blocked-reason="submitting ? '正在提交导出请求' : null" @close="open = false">
    <div v-if="p && s" class="exp">
      <section class="exp__sec exp__summary">
        <div class="exp__big">
          <span class="num exp__count">{{ clips.length }}</span>
          <span>个片段参与导出 <span class="muted small">/ 共 {{ total }} 个</span></span>
        </div>
        <p class="small secondary">
          每个片段生成完整 <strong>MP4</strong>，以及同名配对的 <strong>JPG + MOV</strong> 实况，共 <span class="num">{{ clips.length * 3 }}</span> 个文件，另附导出报告与版本化清单。导出范围按片段勾选，时间线内容不变。
        </p>
      </section>

      <section class="exp__sec">
        <h3 class="section-title">保存位置与命名</h3>
        <div class="exp__grid">
          <UiTextField v-model="form.output_dir" label="保存位置" mono :error="pathIssues.find((i) => i.level === 'error')?.message" :warning="pathIssues.find((i) => i.level === 'warning')?.message">
            <template #suffix><UiButton size="sm" variant="ghost" :icon="FolderOpen" @click="browse">浏览…</UiButton></template>
          </UiTextField>
          <UiTextField v-model="form.name_base" label="文件名前缀" :maxlength="80" :error="nameIssues.find((i) => i.level === 'error')?.message" :warning="nameIssues.find((i) => i.level === 'warning')?.message" hint="支持中文与空格；编号按片段显示顺序，配对与任务定位使用稳定片段 ID。" />
        </div>
        <div class="tree small mono" aria-label="文件组织预览">
          <div class="tree__row"><Folder :size="13" /> {{ form.output_dir || '（未选择）' }}</div>
          <div class="tree__row tree__l1"><Folder :size="13" /> {{ batchFolder }}\</div>
          <div class="tree__row tree__l2"><Folder :size="13" /> LivePhoto\</div>
          <div v-for="st in stems.slice(0, 2)" :key="'lp' + st" class="tree__row tree__l3">{{ st }}.jpg <span class="muted">+</span> {{ st }}.mov</div>
          <div v-if="stems.length > 3" class="tree__row tree__l3 muted">… 共 {{ stems.length }} 对</div>
          <div v-if="stems.length > 2" class="tree__row tree__l3">{{ stems[stems.length - 1] }}.jpg <span class="muted">+</span> {{ stems[stems.length - 1] }}.mov</div>
          <div class="tree__row tree__l2"><Folder :size="13" /> 视频片段\</div>
          <div v-for="st in stems.slice(0, 2)" :key="'mp' + st" class="tree__row tree__l3">{{ st }}.mp4</div>
          <div v-if="stems.length > 2" class="tree__row tree__l3 muted">… 共 {{ stems.length }} 个</div>
          <div class="tree__row tree__l2"><FileText :size="13" /> 导出报告_v{{ p.edit_version }}.html</div>
          <div class="tree__row tree__l2"><FileJson :size="13" /> manifest_v{{ p.edit_version }}.json</div>
        </div>
      </section>

      <section class="exp__sec">
        <h3 class="section-title">画质、色彩与音频</h3>
        <div class="exp__grid">
          <UiSelect
            v-model="form.quality"
            label="画质"
            :options="[
              { value: 'source', label: '与源一致（推荐）' },
              { value: 'high', label: '高画质（体积较大）' },
              { value: 'compact', label: '节省空间' },
            ]"
          />
          <UiSelect
            v-model="form.color"
            label="色彩"
            :options="[
              { value: 'sdr_rec709', label: 'Rec.709 SDR（默认）' },
              { value: 'hdr_keep', label: caps?.hdr_output.supported && hdrSource ? '保留 HDR（验证范围内）' : '保留 HDR（不可用）', disabled: !(caps?.hdr_output.supported && hdrSource) },
            ]"
          />
        </div>
        <p class="small secondary">
          保持源分辨率 {{ s.width }}×{{ s.height }}、方向、显示比例与帧率。源色彩：{{ colorSummary(s.color) }}。
          {{ session.hasAudio.value ? `音频：${clips.length - muted} 个保留原声，${muted} 个静音。` : '源视频无音轨，导出不含音频。' }}
        </p>
        <p v-if="colorLimitNote(s.color, !!caps?.hdr_output.supported)" class="small exp__note">{{ colorLimitNote(s.color, !!caps?.hdr_output.supported) }}</p>
        <p v-if="caps?.hdr_output.note && hdrSource" class="small muted">{{ caps.hdr_output.note }}</p>
        <p class="small muted">编码：{{ caps?.gpu.available ? `优先使用已验证的 GPU 路径（${caps.gpu.verified_encoder}），失败时该片段从头用 CPU 重试` : 'CPU 编码' }}；同时最多处理 {{ caps?.max_parallel_jobs ?? 2 }} 个片段，由后端资源管理器决定。</p>
      </section>

      <section v-if="pendingCuts.length" class="exp__sec">
        <UiBanner tone="warning" :title="`还有 ${pendingCuts.length} 处切点未检查`">
          {{ pendingByKind }}，涉及本次导出的 {{ affectedByPending }} 个片段。未检查的切点会按当前位置导出。
          <template #actions>
            <UiButton size="sm" @click="backToReview">返回检查</UiButton>
          </template>
        </UiBanner>
        <UiCheckbox :checked="ack.unreviewed" label="我已阅读摘要，确认继续导出未检查的切点" @change="(v) => (ack.unreviewed = v)" />
      </section>

      <section v-if="hintCounts.short || hintCounts.long || coverIssues" class="exp__sec">
        <UiBanner tone="info" title="实况兼容性提醒（不影响导出）">
          <template v-if="hintCounts.short">{{ hintCounts.short }} 个超短片段可能不被识别为实况；</template>
          <template v-if="hintCounts.long">{{ hintCounts.long }} 个超长片段可能被平台截断；</template>
          原帧范围都会完整保留，不会补帧、冻结末帧、延长或缩短。
          <template v-if="coverIssues"> {{ coverIssues }} 个片段的封面越界，将由后端重新生成清晰帧。</template>
        </UiBanner>
      </section>

      <section class="exp__sec">
        <h3 class="section-title exp__pf-title">
          目标位置检查
          <span v-if="checking" class="small muted exp__checking"><UiSpinner :size="10" /> 正在检查…</span>
          <button v-else type="button" class="exp__recheck small" @click="runPreflight(0)"><RotateCcw :size="11" /> 重新检查</button>
        </h3>
        <p class="small muted">前端只做命名与路径格式检查；目录权限、文件占用、磁盘空间与路径安全由桌面后端确认。</p>
        <UiBanner v-if="preflightError" tone="danger" compact>{{ preflightError }}</UiBanner>
        <template v-if="preflight">
          <p class="small secondary num">预计占用 {{ formatBytes(preflight.estimated_bytes) }} · 可用空间 {{ formatBytes(preflight.free_space_bytes) }}</p>
          <UiBanner
            v-for="i in preflight.issues"
            :key="i.code"
            :tone="i.level === 'error' ? 'danger' : i.level === 'warning' ? 'warning' : 'info'"
            compact
          >
            {{ i.message }}
            <template v-if="i.action === 'choose_output_dir' || i.action === 'close_other_program'" #actions>
              <UiButton v-if="i.action === 'choose_output_dir'" size="sm" @click="browse">更换位置</UiButton>
              <UiButton v-else size="sm" @click="runPreflight(0)">已关闭，重新检查</UiButton>
            </template>
          </UiBanner>
          <UiCheckbox v-if="needsModifiedAck" :checked="ack.modified" label="仍以新版替换（被修改的旧文件先移入备份目录）" @change="(v) => (ack.modified = v)" />
          <p v-if="!preflight.issues.length" class="small exp__ok"><ShieldCheck :size="13" /> 未发现问题</p>
        </template>
      </section>
      <UiBanner v-if="submitError" tone="danger" compact>{{ submitError }}</UiBanner>
      <p v-if="adapter.mode === 'demo'" class="small muted">演示模式：不会写入任何文件，导出进度与校验结果均为模拟。</p>
    </div>
    <template #footer>
      <span v-if="blockReason && !submitting" class="small muted grow exp__block">{{ blockReason }}</span>
      <UiButton variant="ghost" :disabled="submitting" @click="open = false">取消</UiButton>
      <UiButton variant="primary" :icon="Upload" :loading="submitting" loading-label="正在提交导出请求…" :disabled="!!blockReason" :disabled-reason="blockReason" @click="submit">
        开始导出 {{ clips.length }} 个片段
      </UiButton>
    </template>
  </UiDialog>
</template>

<style scoped>
.exp {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.exp__sec {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 0;
  border-bottom: 1px solid var(--line-subtle);
}
.exp__sec:last-of-type {
  border-bottom: 0;
}
.exp__summary {
  padding-top: 0;
}
.exp__big {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: var(--fs-14);
}
.exp__count {
  font-size: var(--fs-22);
  font-weight: var(--fw-semibold);
}
.exp__grid {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 12px;
}
.tree {
  padding: 8px 10px;
  background: var(--bg-well);
  border: 1px solid var(--line-subtle);
  border-radius: var(--r-2);
  display: grid;
  gap: 2px;
  color: var(--text-2);
  overflow-x: auto;
  user-select: text;
}
.tree__row {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.tree__l1 {
  padding-left: 16px;
}
.tree__l2 {
  padding-left: 38px;
}
.tree__l3 {
  padding-left: 60px;
}
.exp__note {
  color: var(--warning);
}
.exp__pf-title {
  display: flex;
  align-items: center;
  gap: 10px;
}
.exp__checking {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: var(--fw-regular);
}
.exp__recheck {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--accent-hover);
  font-weight: var(--fw-regular);
}
.exp__ok {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--success);
}
.exp__block {
  color: var(--warning);
  min-width: 0;
}
</style>
