<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";

type Cut = { cut_id: string; boundary_index: number; kind: string; needs_review: boolean; checked: boolean; confidence?: number };
type Segment = { clip_id: string; start_index: number; end_index: number; audio_enabled: boolean; output_number: number };
type Project = { project_id: string; source_path: string; frame_count: number; cuts: Cut[]; segments: Segment[]; detector_status: string; pending_review_count: number; can_export: boolean };
type ExportJob = { job_id: string; clip_id: string; state: string; progress: number; phase?: string; user_confirmation_required?: boolean; error_message?: string | null };
type Frame = { display_index: number; pts?: number | null; best_effort_pts?: number | null; time_base_num: number; time_base_den: number; pict_type?: string | null; keyframe?: boolean | null };

const sourcePath = ref("");
const projectPath = ref("");
const project = ref<Project | null>(null);
const center = ref(0);
const frames = ref<Frame[]>([]);
const previewData = ref("");
const selectedCutId = ref("");
const selectedClipId = ref("");
const message = ref("选择一条视频开始。所有处理都在本机完成，源文件不会被覆盖。");
const busy = ref(false);
const exportJobs = ref<ExportJob[]>([]);
const activePanel = ref<"clip" | "queue">("clip");
let queueTimer: number | undefined;

const selectedCut = computed(() => project.value?.cuts.find((cut) => cut.cut_id === selectedCutId.value));
const selectedClip = computed(() => project.value?.segments.find((clip) => clip.clip_id === selectedClipId.value));
const currentFrame = computed(() => frames.value.find((frame) => frame.display_index === center.value));
const checkedCuts = computed(() => project.value?.cuts.filter((cut) => cut.needs_review && cut.checked).length || 0);
const pendingJobs = computed(() => exportJobs.value.filter((job) => !["succeeded", "failed", "skipped", "stale", "interrupted"].includes(job.state)));

function fileName(path: string) { return path ? path.split(/[\\/]/).pop() || path : ""; }
function formatTime(frame: Frame | undefined) {
  if (!frame || frame.best_effort_pts == null) return "--:--.---";
  const seconds = Math.max(0, frame.best_effort_pts * frame.time_base_num / frame.time_base_den);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${(seconds % 60).toFixed(3).padStart(6, "0")}`;
}
function phaseLabel(phase?: string) { return ({ encoding: "编码中", packaging: "封装中", validating: "校验中", committing: "提交中", succeeded: "已完成", failed: "失败", cancelled: "已取消" } as Record<string, string>)[phase || ""] || "等待中"; }
function jobStateLabel(state: string) { return ({ pending: "待执行", processing: "处理中", validating: "校验中", committing: "提交中", succeeded: "完成", failed: "失败", skipped: "已跳过", interrupted: "待确认恢复", stale: "需重新确认" } as Record<string, string>)[state] || state; }

async function call(method: string, params: Record<string, unknown> = {}) {
  busy.value = true;
  try { const result = await window.m3.request(method, params); if (result.project) project.value = result.project; return result; }
  catch (error: any) { message.value = `${error.code || "操作失败"} · ${error.message || error}`; throw error; }
  finally { busy.value = false; }
}

async function pickSource() {
  const picked = await window.m3.pickFile({ title: "选择源视频", mode: "open", filters: [{ name: "视频文件", extensions: ["mp4", "mov", "m4v"] }] });
  if (picked) sourcePath.value = picked;
}
async function pickProject(mode: "open" | "save") {
  const picked = await window.m3.pickFile({ title: mode === "save" ? "保存项目文件" : "打开项目文件", mode, defaultPath: projectPath.value || "video2livephoto-project.sqlite3", filters: [{ name: "SQLite 项目", extensions: ["sqlite3", "db"] }] });
  if (picked) projectPath.value = picked;
}
async function loadWindow() {
  if (!project.value) return;
  const result = await call("frame_window", { center_index: center.value, radius: 4 });
  frames.value = result.frames;
  const preview = await call("preview_frame", { display_index: center.value, width: 960 });
  previewData.value = preview.preview.data_uri;
}
async function importProject() {
  if (!sourcePath.value) { message.value = "先选择一条 MP4 或 MOV 视频。"; return; }
  if (!projectPath.value) await pickProject("save");
  if (!projectPath.value) return;
  try { await call("import", { source_path: sourcePath.value, project_path: projectPath.value }); center.value = 0; await loadWindow(); await refreshQueue(); message.value = "素材已导入。左侧是待审核切点，中间是逐帧预览，右侧可设置片段和导出。"; } catch { /* structured message already shown */ }
}
async function openProject() {
  if (!projectPath.value) await pickProject("open");
  if (!projectPath.value) return;
  try { await call("open", { project_path: projectPath.value }); center.value = 0; await loadWindow(); await refreshQueue(); message.value = "项目已打开，源文件身份已重新核对。"; } catch { /* structured message already shown */ }
}
async function addCut() { if (project.value && center.value > 0 && center.value < project.value.frame_count) { await call("add_cut", { boundary_index: center.value, needs_review: true }); await loadWindow(); } }
async function moveCut(delta: number) { if (selectedCut.value) { await call("move_cut", { cut_id: selectedCut.value.cut_id, boundary_index: selectedCut.value.boundary_index + delta }); await loadWindow(); } }
async function deleteCut() { if (selectedCut.value) { await call("delete_cut", { cut_id: selectedCut.value.cut_id }); selectedCutId.value = ""; await loadWindow(); } }
async function mergeSelected() {
  if (!project.value || !selectedClip.value) return;
  const index = project.value.segments.findIndex((clip) => clip.clip_id === selectedClip.value?.clip_id);
  const next = project.value.segments[index + 1]; if (!next) return;
  const params: Record<string, unknown> = { left_clip_id: selectedClip.value.clip_id, right_clip_id: next.clip_id };
  if (selectedClip.value.audio_enabled !== next.audio_enabled) params.audio_enabled = window.confirm("相邻片段的音频设置不同。合并后保留音频吗？");
  await call("merge_segments", params); await loadWindow();
}
async function toggleClipAudio() { if (selectedClip.value) await call("set_segment_audio", { clip_id: selectedClip.value.clip_id, enabled: !selectedClip.value.audio_enabled }); }
async function muteAll() { if (window.confirm("确认把所有片段设为静音？这个操作可以撤销。")) await call("set_all_audio", { enabled: false }); }
async function markChecked(cut: Cut) { await call("mark_cut_checked", { cut_id: cut.cut_id, checked: !cut.checked }); }
async function undo() { await call("undo"); await loadWindow(); }
async function redo() { await call("redo"); await loadWindow(); }
async function refreshQueue() {
  if (!project.value || busy.value) return;
  const result = await call("export_status"); exportJobs.value = result.jobs || [];
  if (exportJobs.value.length && exportJobs.value.every((job) => ["succeeded", "failed", "skipped", "stale", "interrupted"].includes(job.state))) stopQueuePolling();
}
function stopQueuePolling() { if (queueTimer !== undefined) { window.clearInterval(queueTimer); queueTimer = undefined; } }
function startQueuePolling() { stopQueuePolling(); queueTimer = window.setInterval(() => { void refreshQueue(); }, 1000); }
async function confirmRecovery() { const ids = exportJobs.value.filter((job) => job.user_confirmation_required).map((job) => job.job_id); if (ids.length && window.confirm("程序上次退出时有未完成任务。确认恢复后继续导出吗？")) { await call("confirm_recovery", { job_ids: ids }); startQueuePolling(); await refreshQueue(); } }
async function pauseExport() { await call("pause_export"); await refreshQueue(); }
async function resumeExport() { await call("resume_export"); startQueuePolling(); await refreshQueue(); }
async function cancelExport(job: ExportJob) { if (window.confirm(`确认取消片段 ${job.clip_id}？`)) { await call("cancel_export", { job_id: job.job_id }); await refreshQueue(); } }
async function retryExport(job: ExportJob) { if (window.confirm(`确认重试片段 ${job.clip_id}？`)) { await call("retry_export", { job_id: job.job_id }); startQueuePolling(); await refreshQueue(); } }
async function confirmExport() {
  let allow = false;
  if (project.value?.pending_review_count) { allow = window.confirm(`还有 ${project.value.pending_review_count} 个切点未检查。确认后继续导出吗？`); if (!allow) return; }
  const result = await call("start_export", { allow_unreviewed: allow }); exportJobs.value = result.jobs || []; activePanel.value = "queue"; startQueuePolling(); message.value = `已加入 ${result.jobs.length} 个片段。导出期间可以暂停领取、取消或重试失败任务。`;
}
onUnmounted(stopQueuePolling);
</script>

<template>
  <main class="app-shell">
    <header class="app-bar"><div class="brand"><span class="brand-mark">◒</span><span class="brand-name">VIDEO2LIVEPHOTO</span><span class="brand-version">V1.0</span></div><div class="bar-context" v-if="project"><span class="live-dot"></span><span>{{ fileName(project.source_path) }}</span><span class="context-divider">/</span><span>{{ project.frame_count }} 帧</span></div><div class="bar-actions"><span class="system-label">本地工作区</span><span class="status-pill" :class="{ ready: project }"><i></i>{{ project ? "已连接" : "等待导入" }}</span></div></header>
    <section v-if="!project" class="welcome-screen"><div class="welcome-copy"><span class="eyebrow">LOCAL MEDIA EDITING SUITE · WINDOWS</span><h1>把一条成片，<br /><em>拆成可审核的实况镜头。</em></h1><p class="welcome-lede">从真实显示帧开始。逐帧检查切点，独立控制音频，再把每个镜头导出为 MP4 与 Live Photo 文件对。</p><div class="promise-row"><span><b>01</b> 真实 PTS 时间线</span><span><b>02</b> 用户确认后导出</span><span><b>03</b> 源文件只读保护</span></div></div><div class="import-card"><div class="card-kicker"><span>开始一个项目</span><span class="card-step">01 / 01</span></div><h2>导入素材</h2><p class="card-description">选择一条已剪辑完成的 MP4 或 MOV。项目文件会保存审核状态和切点修改。</p><div class="file-picker" :class="{ filled: sourcePath }"><div class="file-icon video-icon">▶</div><div class="file-meta"><span>源视频</span><strong>{{ sourcePath ? fileName(sourcePath) : "尚未选择视频" }}</strong><small>{{ sourcePath || "MP4 / MOV · 本地文件" }}</small></div><button class="pick-button" @click="pickSource">选择</button></div><div class="file-picker" :class="{ filled: projectPath }"><div class="file-icon project-icon">▦</div><div class="file-meta"><span>项目文件</span><strong>{{ projectPath ? fileName(projectPath) : "自动创建或打开项目" }}</strong><small>{{ projectPath || "SQLite · 可恢复 · 可再次打开" }}</small></div><button class="pick-button" @click="pickProject(projectPath ? 'open' : 'save')">{{ projectPath ? "更换" : "选择" }}</button></div><div class="import-actions"><button class="action-primary" :disabled="busy" @click="importProject"><span>{{ busy ? "正在连接媒体服务…" : "导入并检测" }}</span><b>→</b></button><button class="action-secondary" :disabled="busy" @click="openProject">打开已有项目</button></div><p class="card-footnote"><span class="shield">⌁</span> 源视频永不覆盖 · 所有中间文件写入隔离缓存</p></div><div class="welcome-note"><span class="note-line"></span><span>{{ message }}</span></div></section>
    <section v-else class="studio-shell"><aside class="left-rail"><div class="rail-heading"><span class="eyebrow">PROJECT / REVIEW</span><button class="rail-icon" title="重新打开项目" @click="openProject">↗</button></div><div class="project-name">{{ fileName(project.source_path) }}</div><div class="project-path">{{ project.source_path }}</div><div class="rail-stats"><div><strong>{{ project.segments.length }}</strong><span>片段</span></div><div><strong>{{ project.frame_count }}</strong><span>显示帧</span></div><div class="warn-stat"><strong>{{ project.pending_review_count }}</strong><span>待审核</span></div></div><div class="review-head"><span>切点审核</span><span>{{ checkedCuts }}/{{ project.cuts.filter((cut) => cut.needs_review).length }}</span></div><div class="review-list" v-if="project.cuts.filter((cut) => cut.needs_review).length"><div v-for="cut in project.cuts.filter((item) => item.needs_review)" :key="cut.cut_id" class="review-card" :class="{ selected: cut.cut_id === selectedCutId, checked: cut.checked }" @click="selectedCutId = cut.cut_id; center = cut.boundary_index; void loadWindow()"><div class="review-frame">{{ String(cut.boundary_index).padStart(4, '0') }}</div><div class="review-info"><strong>{{ cut.kind === 'dissolve' ? '叠化候选' : cut.kind === 'black' ? '黑场切点' : '镜头切点' }}</strong><span>{{ cut.checked ? '已检查' : '需要确认' }}</span></div><button class="check-button" @click.stop="markChecked(cut)">{{ cut.checked ? "✓" : "" }}</button></div></div><div class="review-empty" v-else><span>✓</span><p>当前没有待审核切点</p><small>你可以在时间线上手动增加切点。</small></div><div class="rail-bottom"><button class="text-button" @click="addCut">＋ 在当前帧增加切点</button><span class="detector-tag">M2 {{ project.detector_status === 'complete' ? '已完成' : project.detector_status }}</span></div></aside><main class="studio-main"><div class="studio-header"><div><span class="eyebrow">FRAME REVIEW / {{ String(center).padStart(4, '0') }}</span><h1>镜头审核工作台</h1></div><div class="studio-actions"><button class="ghost-button" @click="undo">↶ 撤销</button><button class="ghost-button" @click="redo">重做 ↷</button><button class="export-button" @click="confirmExport">确认并导出 <b>→</b></button></div></div><section class="viewer-card"><div class="viewer-top"><div class="viewer-title"><span class="camera-glyph">◉</span><span>逐帧预览</span><span class="viewer-divider"></span><span class="viewer-sub">{{ formatTime(currentFrame) }}</span></div><div class="viewer-tools"><button :disabled="center <= 0" @click="center -= 1; void loadWindow()">‹</button><span>{{ String(center + 1).padStart(4, '0') }} <small>/ {{ String(project.frame_count).padStart(4, '0') }}</small></span><button :disabled="center >= project.frame_count - 1" @click="center += 1; void loadWindow()">›</button></div></div><div class="viewer-stage"><img v-if="previewData" :src="previewData" alt="当前视频帧" /><div v-else class="stage-empty"><span>◌</span><p>正在解码当前帧</p></div><div class="stage-badge">PTS {{ currentFrame?.best_effort_pts ?? "—" }} · {{ currentFrame?.time_base_num ?? "—" }}/{{ currentFrame?.time_base_den ?? "—" }}</div></div><div class="scrub-row"><span>00:00</span><input class="scrub" type="range" :min="0" :max="Math.max(0, project.frame_count - 1)" v-model.number="center" @change="loadWindow" /><span>{{ formatTime(frames[frames.length - 1]) }}</span></div><div class="frame-strip"><button v-for="frame in frames" :key="frame.display_index" :class="{ active: frame.display_index === center }" @click="center = frame.display_index; loadWindow()"><span>{{ String(frame.display_index).padStart(3, '0') }}</span><small>{{ frame.pict_type || '—' }}</small></button></div></section><section class="timeline-card"><div class="timeline-head"><div><span class="eyebrow">EDIT TIMELINE</span><strong>片段范围</strong></div><div class="timeline-legend"><span><i class="legend-cut"></i>检测切点</span><span><i class="legend-current"></i>当前帧</span></div></div><div class="timeline-track"><div v-for="segment in project.segments" :key="segment.clip_id" class="timeline-segment" :class="{ selected: segment.clip_id === selectedClipId }" :style="{ flex: `${Math.max(1, segment.end_index - segment.start_index)} 1 0` }" @click="selectedClipId = segment.clip_id"><span>镜头 {{ String(segment.output_number).padStart(2, '0') }}</span><strong>{{ segment.end_index - segment.start_index }} 帧</strong><small>{{ segment.audio_enabled ? '音频' : '静音' }}</small></div><div class="timeline-cursor" :style="{ left: `${(center / Math.max(1, project.frame_count - 1)) * 100}%` }"></div></div><div class="timeline-scale"><span>0</span><span>{{ Math.round(project.frame_count / 4) }}</span><span>{{ Math.round(project.frame_count / 2) }}</span><span>{{ Math.round(project.frame_count * .75) }}</span><span>{{ project.frame_count }}</span></div></section></main><aside class="right-panel"><div class="panel-tabs"><button :class="{ active: activePanel === 'clip' }" @click="activePanel = 'clip'">片段设置</button><button :class="{ active: activePanel === 'queue' }" @click="activePanel = 'queue'">导出队列 <b v-if="pendingJobs.length">{{ pendingJobs.length }}</b></button></div><div v-if="activePanel === 'clip'" class="panel-content"><template v-if="selectedClip"><span class="eyebrow">SELECTED CLIP / {{ String(selectedClip.output_number).padStart(2, '0') }}</span><h2>片段 {{ String(selectedClip.output_number).padStart(2, '0') }}</h2><div class="range-display"><span>{{ String(selectedClip.start_index).padStart(4, '0') }}</span><i></i><span>{{ String(selectedClip.end_index).padStart(4, '0') }}</span></div><p class="panel-caption">显示帧范围 · {{ selectedClip.end_index - selectedClip.start_index }} 帧</p><div class="setting-block"><span>音频</span><button class="setting-toggle" :class="{ on: selectedClip.audio_enabled }" @click="toggleClipAudio"><i></i>{{ selectedClip.audio_enabled ? '保留原音频' : '当前为静音' }}<b>{{ selectedClip.audio_enabled ? 'ON' : 'OFF' }}</b></button><button class="wide-ghost" @click="muteAll">全部片段设为静音</button></div><div class="clip-actions"><button :disabled="!selectedCut" @click="moveCut(-1)">切点 ←</button><button :disabled="!selectedCut" @click="moveCut(1)">切点 →</button><button :disabled="!selectedCut" @click="deleteCut">删除切点</button></div></template><div v-else class="panel-empty"><span>⌁</span><h2>选择一个片段</h2><p>点击时间线中的镜头，查看范围、音频和导出设置。</p></div></div><div v-else class="panel-content queue-content"><div class="queue-heading"><span class="eyebrow">EXPORT QUEUE</span><button class="refresh-button" @click="refreshQueue">刷新</button></div><h2>导出任务</h2><button v-if="exportJobs.some((job) => job.user_confirmation_required)" class="recovery-button" @click="confirmRecovery">确认恢复未完成任务</button><div class="queue-actions"><button @click="pauseExport">暂停领取</button><button @click="resumeExport">继续领取</button></div><div v-for="job in exportJobs" :key="job.job_id" class="queue-row"><div class="queue-row-top"><strong>{{ fileName(job.clip_id) }}</strong><span>{{ Math.round(job.progress * 100) }}%</span></div><div class="progress-line"><i :style="{ width: `${Math.round(job.progress * 100)}%` }"></i></div><div class="queue-row-bottom"><span>{{ jobStateLabel(job.state) }} · {{ phaseLabel(job.phase) }}</span><button v-if="['pending','processing','validating','committing'].includes(job.state)" @click="cancelExport(job)">取消</button><button v-if="job.state === 'failed'" @click="retryExport(job)">重试</button></div><small v-if="job.error_message">{{ job.error_message }}</small></div><div v-if="!exportJobs.length" class="queue-empty"><span>◷</span><p>还没有导出任务</p><small>确认审核后，导出任务会出现在这里。</small></div></div></aside></section>
    <footer class="status-bar"><span class="status-light" :class="{ active: project }"></span><span>{{ message }}</span><span class="status-spacer"></span><span v-if="project">源文件只读 · SQLite 已保存</span><span v-else>Video2LivePhoto V1.0 · Offline first</span></footer>
  </main>
</template>
