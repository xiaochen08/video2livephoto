<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import iconCircle from "./assets/figma/icon-circle.svg";
import iconCheck from "./assets/figma/icon-check.svg";
import iconFilm from "./assets/figma/icon-film.svg";
import iconFolder from "./assets/figma/icon-folder.svg";
import iconLayers from "./assets/figma/icon-layers.svg";
import iconLayersAlt from "./assets/figma/icon-layers-alt.svg";
import iconSliders from "./assets/figma/icon-sliders.svg";
import iconScissors from "./assets/figma/icon-scissors.svg";
import iconSound from "./assets/figma/icon-sound.svg";

type Cut = { cut_id: string; boundary_index: number; kind: string; needs_review: boolean; checked: boolean; confidence?: number };
type Segment = { clip_id: string; start_index: number; end_index: number; audio_enabled: boolean; output_number: number };
type Project = { project_id: string; source_path: string; frame_count: number; cuts: Cut[]; segments: Segment[]; detector_status: string; pending_review_count: number; can_export: boolean };
type ExportJob = { job_id: string; clip_id: string; state: string; progress: number; phase?: string; user_confirmation_required?: boolean; error_message?: string | null };
type Frame = { display_index: number; pts?: number | null; best_effort_pts?: number | null; time_base_num: number; time_base_den: number; pict_type?: string | null; keyframe?: boolean | null };
type RecentProject = { path: string; updatedAt: number };

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
const isDropActive = ref(false);
const leftCollapsed = ref(false);
const rightCollapsed = ref(false);
const showCutReview = ref(false);
const showExportDialog = ref(false);
const showTaskCenter = ref(false);
const reviewCut = ref<Cut | null>(null);
const reviewBeforeData = ref("");
const reviewAfterData = ref("");
const reviewBeforeFrame = ref<Frame | undefined>();
const reviewAfterFrame = ref<Frame | undefined>();
const reviewPreviewDelta = ref(0);
const allowUnreviewed = ref(false);
const exportLivePhoto = ref(true);
const exportVideo = ref(true);
const outputDir = ref("");
const colorMode = ref("sdr");
const recentProjects = ref<RecentProject[]>([]);
const timelineZoom = ref(1);
let queueTimer: number | undefined;

const selectedCut = computed(() => project.value?.cuts.find((cut) => cut.cut_id === selectedCutId.value));
const selectedClip = computed(() => project.value?.segments.find((clip) => clip.clip_id === selectedClipId.value));
const currentFrame = computed(() => frames.value.find((frame) => frame.display_index === center.value));
const checkedCuts = computed(() => project.value?.cuts.filter((cut) => cut.needs_review && cut.checked).length || 0);
const pendingJobs = computed(() => exportJobs.value.filter((job) => !["succeeded", "failed", "skipped", "stale", "interrupted"].includes(job.state)));

function fileName(path: string) { return path ? path.split(/[\\/]/).pop() || path : ""; }
function formatTime(frame: Frame | undefined) {
  if (!frame || frame.best_effort_pts == null) return "--:--.---";
  const seconds = frame.best_effort_pts * frame.time_base_num / frame.time_base_den;
  const sign = seconds < 0 ? "-" : "";
  const absolute = Math.abs(seconds);
  return `${sign}${String(Math.floor(absolute / 60)).padStart(2, "0")}:${(absolute % 60).toFixed(3).padStart(6, "0")}`;
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
  try { await call("import", { source_path: sourcePath.value, project_path: projectPath.value }); rememberProject(projectPath.value); selectedClipId.value = project.value?.segments[0]?.clip_id || ""; center.value = 0; await loadWindow(); await refreshQueue(); message.value = "素材已导入。先检查切点，再确认导出。"; } catch { /* structured message already shown */ }
}
async function openProject() {
  if (!projectPath.value) await pickProject("open");
  if (!projectPath.value) return;
  try { await call("open", { project_path: projectPath.value }); rememberProject(projectPath.value); selectedClipId.value = project.value?.segments[0]?.clip_id || ""; center.value = 0; await loadWindow(); await refreshQueue(); message.value = "项目已打开，源文件身份已重新核对。"; } catch { /* structured message already shown */ }
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
function rememberProject(path: string) {
  if (!path) return;
  recentProjects.value = [{ path, updatedAt: Date.now() }, ...recentProjects.value.filter((item) => item.path !== path)].slice(0, 5);
  localStorage.setItem("video2livephoto.recent-projects", JSON.stringify(recentProjects.value));
}
function handleDrop(event: DragEvent) {
  isDropActive.value = false;
  const file = event.dataTransfer?.files?.[0] as (File & { path?: string }) | undefined;
  if (!file?.path) { message.value = "无法读取拖入文件路径，请使用“选择视频文件”。"; return; }
  sourcePath.value = file.path;
  message.value = `已选择 ${fileName(file.path)}，点击导入并检测开始。`;
}
async function loadReviewFrames(boundaryIndex: number) {
  if (!project.value) return;
  const beforeIndex = Math.max(0, boundaryIndex - 1);
  const afterIndex = Math.min(project.value.frame_count - 1, boundaryIndex);
  const [before, after] = await Promise.all([
    call("preview_frame", { display_index: beforeIndex, width: 640 }),
    call("preview_frame", { display_index: afterIndex, width: 640 }),
  ]);
  reviewBeforeData.value = before.preview.data_uri;
  reviewAfterData.value = after.preview.data_uri;
  const timeBaseNum = currentFrame.value?.time_base_num || 1;
  const timeBaseDen = currentFrame.value?.time_base_den || 1;
  reviewBeforeFrame.value = frames.value.find((frame) => frame.display_index === beforeIndex) || { display_index: beforeIndex, pts: before.preview.pts, best_effort_pts: before.preview.pts, time_base_num: timeBaseNum, time_base_den: timeBaseDen };
  reviewAfterFrame.value = frames.value.find((frame) => frame.display_index === afterIndex) || { display_index: afterIndex, pts: after.preview.pts, best_effort_pts: after.preview.pts, time_base_num: timeBaseNum, time_base_den: timeBaseDen };
}
async function openCutReview(cut: Cut) {
  reviewCut.value = cut;
  reviewPreviewDelta.value = 0;
  showCutReview.value = true;
  try { await loadReviewFrames(cut.boundary_index); } catch { /* structured message already shown */ }
}
async function previewReviewOffset(delta: number) {
  if (!reviewCut.value) return;
  reviewPreviewDelta.value = delta;
  await loadReviewFrames(reviewCut.value.boundary_index + delta);
}
async function nudgeReview(delta: number) {
  if (!reviewCut.value) return;
  const nextIndex = reviewCut.value.boundary_index + delta;
  if (!project.value || nextIndex <= 0 || nextIndex >= project.value.frame_count) return;
  await call("move_cut", { cut_id: reviewCut.value.cut_id, boundary_index: nextIndex });
  const updated = project.value.cuts.find((cut) => cut.cut_id === reviewCut.value?.cut_id);
  if (updated) { reviewCut.value = updated; await loadReviewFrames(updated.boundary_index); }
  await loadWindow();
}
async function finishCutReview() {
  if (!reviewCut.value) return;
  await call("mark_cut_checked", { cut_id: reviewCut.value.cut_id, checked: true });
  const next = project.value?.cuts.find((cut) => cut.needs_review && !cut.checked);
  if (next) { await openCutReview(next); } else { showCutReview.value = false; }
}
function keepCutPending() { showCutReview.value = false; }
function openExportDialog() {
  outputDir.value = projectPath.value.replace(/[\\/][^\\/]+$/, "") + "\\导出";
  allowUnreviewed.value = false;
  showExportDialog.value = true;
}
async function submitExport() {
  if (!project.value) return;
  if (project.value.pending_review_count && !allowUnreviewed.value) { message.value = "请先检查待审核切点，或在确认框中明确允许继续。"; return; }
  const result = await call("start_export", { allow_unreviewed: allowUnreviewed.value, output_dir: outputDir.value, color_mode: colorMode.value });
  exportJobs.value = result.jobs || [];
  showExportDialog.value = false;
  showTaskCenter.value = true;
  activePanel.value = "queue";
  startQueuePolling();
  message.value = `已加入 ${result.jobs.length} 个片段。导出期间可以暂停、取消或重试。`;
}
async function pickOutputDir() {
  const picked = await window.m3.pickFile({ title: "选择导出文件夹", mode: "directory" });
  if (picked) outputDir.value = picked;
}
function closeDialogs() { showCutReview.value = false; showExportDialog.value = false; }
function onKeyDown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "o") { event.preventDefault(); void pickSource(); }
  if (event.key === "Escape") { closeDialogs(); showTaskCenter.value = false; }
}
onMounted(() => {
  try { recentProjects.value = JSON.parse(localStorage.getItem("video2livephoto.recent-projects") || "[]"); } catch { recentProjects.value = []; }
  window.addEventListener("keydown", onKeyDown);
});
onUnmounted(() => { stopQueuePolling(); window.removeEventListener("keydown", onKeyDown); });
</script>

<template>
  <main class="app-shell">
    <header class="app-titlebar">
      <div class="brand"><img class="brand-mark" :src="iconCircle" alt="" /><span class="brand-name">Video2LivePhoto</span><span v-if="project" class="brand-slash">/</span><span v-if="project" class="brand-project">{{ fileName(project.source_path) }}</span></div>
      <div class="titlebar-spacer"></div>
      <div v-if="project" class="save-status"><img class="save-icon" :src="iconCheck" alt="" /> 已保存到本地</div>
      <span class="system-label">本地处理 · Windows</span>
      <template v-if="project"><button class="titlebar-button" @click="rightCollapsed = !rightCollapsed">项目设置</button><button class="titlebar-primary" @click="openExportDialog">导出 {{ project.segments.length }} 个片段</button></template>
    </header>

    <section v-if="!project" class="import-page">
      <div class="import-heading"><h1>视频转实况</h1><p>导入完整成片，逐个检查镜头，再批量制作实况照片。</p></div>
      <section class="dropzone" :class="{ active: isDropActive }" @dragover.prevent="isDropActive = true" @dragleave.prevent="isDropActive = false" @drop.prevent="handleDrop">
        <div class="dropzone-main"><div class="media-icon">＋</div><div class="dropzone-copy"><h2>将视频拖到这里</h2><p>MP4 · MOV · M4V</p><small>保留长短镜头与原声，检测后先进入预览。</small><div class="dropzone-actions"><button class="titlebar-primary" :disabled="busy" @click="sourcePath ? importProject() : pickSource()">{{ sourcePath ? "导入并检测" : "选择视频文件" }}</button><span>或按 Ctrl + O</span></div><div v-if="sourcePath" class="selected-file">已选择 · {{ fileName(sourcePath) }}</div></div></div>
        <div class="dropzone-divider"></div><ol class="import-steps"><li><b>01</b><span>自动识别镜头</span></li><li><b>02</b><span>预览并调整切点</span></li><li><b>03</b><span>批量导出实况</span></li></ol>
      </section>
      <div v-if="message && message !== '选择一条视频开始。所有处理都在本机完成，源文件不会被覆盖。'" class="import-message"><span class="status-light"></span>{{ message }}</div>
      <section class="recent-section"><div class="section-heading"><h2>最近项目</h2><button class="text-link" @click="pickProject('open')">打开项目文件</button></div><div v-if="recentProjects.length" class="recent-list"><div v-for="item in recentProjects" :key="item.path" class="recent-row"><div class="recent-icon">▣</div><div class="recent-meta"><strong>{{ fileName(item.path) }}</strong><span>{{ item.path }}</span></div><time>{{ new Date(item.updatedAt).toLocaleDateString() }}</time><button class="row-button" @click="projectPath = item.path; void openProject()">打开项目</button></div></div><div v-else class="recent-empty"><span>○</span><p>还没有本地项目</p><small>导入并保存项目后，最近项目会出现在这里。</small></div></section>
      <footer class="import-footer"><span>所有素材在本地处理 · 源文件只读保护</span><span>Video2LivePhoto V1.0</span></footer>
    </section>

    <section v-else class="workspace-shell" :class="{ 'left-collapsed': leftCollapsed, 'right-collapsed': rightCollapsed }">
      <aside class="app-rail"><button class="rail-active" title="剪辑工作区"><img :src="iconFilm" alt="" /></button><button title="项目文件" @click="openProject"><img :src="iconFolder" alt="" /></button><button title="任务中心" @click="showTaskCenter = true; activePanel = 'queue'"><img :src="iconLayers" alt="" /></button><div class="rail-spacer"></div><button title="收起左侧栏" @click="leftCollapsed = !leftCollapsed">{{ leftCollapsed ? '»' : '«' }}</button><button title="收起右侧栏" @click="rightCollapsed = !rightCollapsed"><img :src="iconSliders" alt="" /></button></aside>
      <aside class="clips-sidebar"><div class="sidebar-title"><div><h2>镜头</h2><span>{{ project.segments.length }}</span></div><button class="sidebar-more">···</button></div><div class="filter-tabs"><button class="active">全部</button><button>待检查 {{ project.pending_review_count }}</button></div><div class="clip-list"><button v-for="segment in project.segments" :key="segment.clip_id" class="clip-item" :class="{ selected: segment.clip_id === selectedClipId }" @click="selectedClipId = segment.clip_id"><div class="clip-thumb"><span>{{ String(segment.output_number).padStart(2, '0') }}</span></div><div class="clip-details"><strong>镜头 {{ String(segment.output_number).padStart(2, '0') }}</strong><span>{{ segment.end_index - segment.start_index }} 帧</span><small>{{ segment.audio_enabled ? '原声保留' : '已静音' }}</small></div></button></div><div class="sidebar-review"><div class="review-heading"><span>切点审核</span><b>{{ checkedCuts }}/{{ project.cuts.filter((cut) => cut.needs_review).length }}</b></div><button v-for="cut in project.cuts.filter((item) => item.needs_review)" :key="cut.cut_id" class="review-row" :class="{ checked: cut.checked }" @click="selectedCutId = cut.cut_id; center = cut.boundary_index; void openCutReview(cut)"><span>{{ String(cut.boundary_index).padStart(4, '0') }}</span><strong>{{ cut.kind === 'dissolve' ? '叠化候选' : '镜头切点' }}</strong><em>{{ cut.checked ? '已检查' : '待检查' }}</em></button><div v-if="!project.cuts.filter((cut) => cut.needs_review).length" class="sidebar-empty">没有待检查切点</div></div><button class="sidebar-add" @click="addCut">＋ 在当前帧增加切点</button></aside>

      <main class="editor-main"><div class="editor-header"><div><span class="eyebrow">剪辑工作区 / FRAME {{ String(center).padStart(4, '0') }}</span><h1>镜头审核</h1></div><div class="editor-actions"><button class="ghost-button" @click="undo">↶</button><button class="ghost-button" @click="redo">↷</button><button class="titlebar-primary" @click="openExportDialog">确认并导出 <b>→</b></button></div></div><section class="viewer-card"><div class="viewer-top"><div class="viewer-title"><span class="camera-glyph">◉</span><span>逐帧预览</span><span class="viewer-divider"></span><span class="viewer-sub">{{ formatTime(currentFrame) }}</span></div><div class="viewer-tools"><button :disabled="center <= 0" @click="center -= 1; void loadWindow()">‹</button><span>{{ String(center + 1).padStart(4, '0') }} <small>/ {{ String(project.frame_count).padStart(4, '0') }}</small></span><button :disabled="center >= project.frame_count - 1" @click="center += 1; void loadWindow()">›</button></div></div><div class="viewer-stage"><img v-if="previewData" :src="previewData" alt="当前视频帧" /><div v-else class="stage-empty"><span>◌</span><p>正在解码当前帧</p></div><div class="stage-badge">PTS {{ currentFrame?.best_effort_pts ?? "—" }} · {{ currentFrame?.time_base_num ?? "—" }}/{{ currentFrame?.time_base_den ?? "—" }}</div></div><div class="scrub-row"><span>{{ formatTime(frames[0]) }}</span><input class="scrub" type="range" :min="0" :max="Math.max(0, project.frame_count - 1)" v-model.number="center" @change="loadWindow" /><span>{{ formatTime(frames[frames.length - 1]) }}</span></div><div class="frame-strip"><button v-for="frame in frames" :key="frame.display_index" :class="{ active: frame.display_index === center }" @click="center = frame.display_index; loadWindow()"><span>{{ String(frame.display_index).padStart(3, '0') }}</span><small>{{ frame.pict_type || '—' }}</small></button></div></section><section class="timeline-card"><div class="timeline-head"><div><span class="eyebrow">EDIT TIMELINE</span><strong>片段范围</strong></div><div class="timeline-toolbar"><button @click="addCut"><img :src="iconScissors" alt="" />分割</button><button @click="mergeSelected"><img :src="iconLayersAlt" alt="" />合并</button><button @click="timelineZoom = Math.max(.5, timelineZoom - .25)">−</button><button @click="timelineZoom = Math.min(2, timelineZoom + .25)">＋</button><button @click="timelineZoom = 1">适应全部</button></div><div class="timeline-legend"><span><i class="legend-cut"></i>检测切点</span><span><i class="legend-current"></i>当前帧</span></div></div><div class="timeline-track" :style="{ transform: `scaleX(${timelineZoom})`, transformOrigin: 'left center' }"><div v-for="segment in project.segments" :key="segment.clip_id" class="timeline-segment" :class="{ selected: segment.clip_id === selectedClipId }" :style="{ flex: `${Math.max(1, segment.end_index - segment.start_index)} 1 0` }" @click="selectedClipId = segment.clip_id"><span>镜头 {{ String(segment.output_number).padStart(2, '0') }}</span><strong>{{ segment.end_index - segment.start_index }} 帧</strong><small>{{ segment.audio_enabled ? '原声' : '静音' }}</small></div><button v-for="cut in project.cuts" :key="`marker-${cut.cut_id}`" class="cut-marker" :class="{ review: cut.needs_review, checked: cut.checked }" :style="{ left: `${(cut.boundary_index / Math.max(1, project.frame_count - 1)) * 100}%` }" @click.stop="openCutReview(cut)" :title="cut.checked ? '已检查切点' : '打开切点精查'"></button><div class="timeline-cursor" :style="{ left: `${(center / Math.max(1, project.frame_count - 1)) * 100}%` }"></div></div><div class="timeline-scale"><span>0</span><span>{{ Math.round(project.frame_count / 4) }}</span><span>{{ Math.round(project.frame_count / 2) }}</span><span>{{ Math.round(project.frame_count * .75) }}</span><span>{{ project.frame_count }}</span></div></section><footer class="editor-status"><span class="status-light active"></span>{{ message }}<span class="status-spacer"></span>源文件只读 · SQLite 已保存</footer></main>

      <aside class="inspector"><div class="panel-tabs"><button :class="{ active: activePanel === 'clip' }" @click="activePanel = 'clip'">片段设置</button><button :class="{ active: activePanel === 'queue' }" @click="activePanel = 'queue'">导出队列 <b v-if="pendingJobs.length">{{ pendingJobs.length }}</b></button></div><div v-if="activePanel === 'clip'" class="panel-content"><template v-if="selectedClip"><span class="eyebrow">SELECTED CLIP / {{ String(selectedClip.output_number).padStart(2, '0') }}</span><h2>镜头 {{ String(selectedClip.output_number).padStart(2, '0') }}</h2><div class="range-display"><span>{{ String(selectedClip.start_index).padStart(4, '0') }}</span><i></i><span>{{ String(selectedClip.end_index).padStart(4, '0') }}</span></div><p class="panel-caption">显示帧范围 · {{ selectedClip.end_index - selectedClip.start_index }} 帧</p><div class="setting-block"><span>音频</span><button class="setting-toggle" :class="{ on: selectedClip.audio_enabled }" @click="toggleClipAudio"><img :src="iconSound" alt="" /><span>{{ selectedClip.audio_enabled ? '保留原音频' : '当前为静音' }}</span><b>{{ selectedClip.audio_enabled ? 'ON' : 'OFF' }}</b></button><button class="wide-ghost" @click="muteAll">全部片段设为静音</button></div><div class="clip-actions"><button :disabled="!selectedCut" @click="moveCut(-1)">切点 ←</button><button :disabled="!selectedCut" @click="moveCut(1)">切点 →</button><button :disabled="!selectedCut" @click="deleteCut">删除切点</button></div><button class="inspect-button" v-if="selectedCut" @click="openCutReview(selectedCut)">打开切点精查 →</button></template><div v-else class="panel-empty"><span>⌁</span><h2>选择一个镜头</h2><p>点击左侧镜头或时间线中的片段，查看范围、音频和导出设置。</p></div></div><div v-else class="panel-content queue-content"><div class="queue-heading"><span class="eyebrow">EXPORT QUEUE</span><button class="refresh-button" @click="refreshQueue">刷新</button></div><h2>导出任务</h2><button v-if="exportJobs.some((job) => job.user_confirmation_required)" class="recovery-button" @click="confirmRecovery">确认恢复未完成任务</button><div class="queue-actions"><button @click="pauseExport">暂停领取</button><button @click="resumeExport">继续领取</button></div><div v-for="job in exportJobs" :key="job.job_id" class="queue-row"><div class="queue-row-top"><strong>{{ fileName(job.clip_id) }}</strong><span>{{ Math.round(job.progress * 100) }}%</span></div><div class="progress-line"><i :style="{ width: `${Math.round(job.progress * 100)}%` }"></i></div><div class="queue-row-bottom"><span>{{ jobStateLabel(job.state) }} · {{ phaseLabel(job.phase) }}</span><button v-if="['pending','processing','validating','committing'].includes(job.state)" @click="cancelExport(job)">取消</button><button v-if="job.state === 'failed'" @click="retryExport(job)">重试</button></div><small v-if="job.error_message">{{ job.error_message }}</small></div><div v-if="!exportJobs.length" class="queue-empty"><span>◷</span><p>还没有导出任务</p><small>确认审核后，导出任务会出现在这里。</small></div></div></aside>
    </section>

    <div v-if="showCutReview" class="modal-backdrop" @click.self="closeDialogs"><section class="review-modal"><header class="modal-header"><div><h2>检查切点</h2><span>{{ reviewCut ? String(reviewCut.boundary_index).padStart(4, '0') : '—' }} / {{ reviewCut?.kind === 'dissolve' ? '叠化候选' : '镜头切点' }}</span></div><button class="modal-close" @click="closeDialogs">关闭</button></header><div class="compare-grid"><figure><figcaption>前一帧 · {{ reviewBeforeFrame ? formatTime(reviewBeforeFrame) : '—' }}</figcaption><img v-if="reviewBeforeData" :src="reviewBeforeData" alt="切点前一帧" /><div v-else class="compare-empty">A</div></figure><figure><figcaption>后一帧 · {{ reviewAfterFrame ? formatTime(reviewAfterFrame) : '—' }}</figcaption><img v-if="reviewAfterData" :src="reviewAfterData" alt="切点后一帧" /><div v-else class="compare-empty">B</div></figure></div><div class="review-strip-label"><span>转场范围</span><b>逐帧调整会立即写入项目</b></div><div class="review-frame-strip"><button v-for="delta in [-3,-2,-1,0,1,2,3]" :key="delta" :class="{ active: delta === reviewPreviewDelta }" @click="previewReviewOffset(delta)">{{ reviewCut ? String(Math.max(0, reviewCut.boundary_index + delta)).padStart(4, '0') : '—' }}</button></div><footer class="modal-footer"><span>移动切点后会重新生成两侧预览。</span><div><button class="ghost-button" @click="nudgeReview(-1)">← 前移 1 帧</button><button class="ghost-button" @click="nudgeReview(1)">后移 1 帧 →</button><button class="ghost-button" @click="keepCutPending">保留待检查</button><button class="titlebar-primary" @click="finishCutReview">确认并下一处</button></div></footer></section></div>

    <div v-if="showExportDialog" class="modal-backdrop" @click.self="closeDialogs"><section class="export-modal"><header class="modal-header"><div><h2>导出实况片段</h2><span>{{ project.segments.length }} 个片段 · 完整时长保留</span></div><button class="modal-close" @click="closeDialogs">关闭</button></header><div class="modal-section"><h3>输出内容</h3><div class="option-grid"><label class="option-card"><input v-model="exportLivePhoto" type="checkbox" disabled /><span><b>✓</b><strong>Live Photo</strong><small>JPG + MOV 配对文件 · 当前管线固定输出</small></span></label><label class="option-card"><input v-model="exportVideo" type="checkbox" disabled /><span><b>✓</b><strong>独立视频</strong><small>每个镜头一个 MP4 · 当前管线固定输出</small></span></label></div></div><div class="modal-section"><h3>画质与色彩</h3><div class="summary-card"><div><strong>高画质 · 速度兼顾</strong><span>保留原分辨率 · H.264 · 默认 SDR</span><small>HDR 素材会按安全策略转为 SDR，导出前可复核。</small></div><select v-model="colorMode"><option value="sdr">默认 SDR</option><option value="hdr">尝试保留 HDR</option></select></div></div><div class="modal-section"><h3>保存位置</h3><div class="path-control"><span>{{ outputDir || '将保存到项目目录下的导出文件夹' }}</span><button @click="pickOutputDir">更改</button></div><small class="path-hint">同名输出先进入安全覆盖确认，不会直接覆盖原文件。</small></div><div v-if="project.pending_review_count" class="warning-box"><strong>还有 {{ project.pending_review_count }} 处切点待检查</strong><span>继续导出前请确认这些切点，或明确允许保留待审核状态。</span><label><input v-model="allowUnreviewed" type="checkbox" /> 我确认继续导出待审核片段</label></div><footer class="modal-footer"><button class="ghost-button" @click="closeDialogs">返回检查</button><button class="titlebar-primary" @click="submitExport">确认并导出 {{ project.segments.length }} 段</button></footer></section></div>

    <div v-if="showTaskCenter" class="modal-backdrop task-backdrop" @click.self="showTaskCenter = false"><section class="task-center"><header class="task-header"><div><span class="eyebrow">EXPORT QUEUE / LOCAL</span><h2>导出任务</h2><p>{{ fileName(project.source_path) }}</p></div><div><button class="ghost-button" @click="showTaskCenter = false">回到剪辑</button><button class="modal-close" @click="showTaskCenter = false">关闭</button></div></header><div v-if="exportJobs.some((job) => job.user_confirmation_required)" class="recovery-banner"><div><strong>上次任务已恢复，等待你的确认</strong><span>未确认的任务不会继续写入输出文件。</span></div><button class="titlebar-primary" @click="confirmRecovery">继续剩余任务</button></div><div class="task-summary"><div><strong>{{ exportJobs.filter((job) => job.state === 'succeeded').length }}</strong><span>已完成</span></div><div><strong>{{ exportJobs.filter((job) => !['succeeded','failed','skipped','stale','interrupted'].includes(job.state)).length }}</strong><span>待处理</span></div><div><strong>{{ exportJobs.filter((job) => job.state === 'failed').length }}</strong><span>失败</span></div><div><strong>1–2</strong><span>并发上限</span></div></div><div class="task-progress"><i :style="{ width: `${exportJobs.length ? (exportJobs.filter((job) => job.state === 'succeeded').length / exportJobs.length) * 100 : 0}%` }"></i></div><div class="task-list"><div v-for="job in exportJobs" :key="job.job_id" class="task-row"><div><strong>{{ fileName(job.clip_id) }}</strong><span>{{ jobStateLabel(job.state) }} · {{ phaseLabel(job.phase) }}</span></div><b>{{ Math.round(job.progress * 100) }}%</b><button v-if="['pending','processing','validating','committing'].includes(job.state)" @click="cancelExport(job)">取消</button><button v-if="job.state === 'failed'" @click="retryExport(job)">重试</button></div><div v-if="!exportJobs.length" class="task-empty">还没有导出任务</div></div><footer class="task-footer"><span>任务状态保存在本地 SQLite，程序中断后需要再次确认恢复。</span><button class="ghost-button" @click="pauseExport">暂停领取</button><button class="ghost-button" @click="resumeExport">继续领取</button></footer></section></div>
  </main>
</template>
