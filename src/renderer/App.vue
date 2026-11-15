<script setup lang="ts">
import { computed, ref } from "vue";

type Project = {
  project_id: string;
  source_path: string;
  frame_count: number;
  cuts: Array<{ cut_id: string; boundary_index: number; kind: string; needs_review: boolean; checked: boolean; confidence?: number }>;
  segments: Array<{ clip_id: string; start_index: number; end_index: number; audio_enabled: boolean; output_number: number }>;
  detector_status: string;
  pending_review_count: number;
  can_export: boolean;
};

const sourcePath = ref("");
const projectPath = ref("");
const project = ref<Project | null>(null);
const center = ref(0);
const frames = ref<any[]>([]);
const previewData = ref("");
const selectedCutId = ref("");
const selectedClipId = ref("");
const message = ref("先导入一条本地视频；M3 不会自动导出。\n");
const busy = ref(false);

const selectedCut = computed(() => project.value?.cuts.find((cut) => cut.cut_id === selectedCutId.value));
const selectedClip = computed(() => project.value?.segments.find((clip) => clip.clip_id === selectedClipId.value));

async function call(method: string, params: Record<string, unknown> = {}) {
  busy.value = true;
  try {
    const result = await window.m3.request(method, params);
    if (result.project) project.value = result.project;
    return result;
  } catch (error: any) {
    message.value = `${error.code || "ERROR"}: ${error.message || error}\n`;
    throw error;
  } finally {
    busy.value = false;
  }
}

async function loadWindow() {
  if (!project.value) return;
  const result = await call("frame_window", { center_index: center.value, radius: 4 });
  frames.value = result.frames;
  const preview = await call("preview_frame", { display_index: center.value, width: 720 });
  previewData.value = preview.preview.data_uri;
}

async function importProject() {
  if (!sourcePath.value || !projectPath.value) {
    message.value = "请输入源视频路径和项目 SQLite 路径。\n";
    return;
  }
  await call("import", { source_path: sourcePath.value, project_path: projectPath.value });
  center.value = 0;
  await loadWindow();
  message.value = "已通过 M1 完成真实探测与显示帧索引。请审核切点后再确认导出。\n";
}

async function openProject() {
  if (!projectPath.value) return;
  await call("open", { project_path: projectPath.value });
  await loadWindow();
  message.value = "项目已重开；源文件身份已重新核对。\n";
}

async function addCut() {
  if (!project.value || center.value <= 0 || center.value >= project.value.frame_count) return;
  await call("add_cut", { boundary_index: center.value, needs_review: true });
  await loadWindow();
}

async function moveCut(delta: number) {
  if (!selectedCut.value) return;
  await call("move_cut", { cut_id: selectedCut.value.cut_id, boundary_index: selectedCut.value.boundary_index + delta });
  await loadWindow();
}

async function deleteCut() {
  if (!selectedCut.value) return;
  await call("delete_cut", { cut_id: selectedCut.value.cut_id });
  selectedCutId.value = "";
  await loadWindow();
}

async function mergeSelected() {
  if (!project.value || !selectedClip.value) return;
  const index = project.value.segments.findIndex((clip) => clip.clip_id === selectedClip.value?.clip_id);
  const next = project.value.segments[index + 1];
  if (!next) return;
  const params: Record<string, unknown> = { left_clip_id: selectedClip.value.clip_id, right_clip_id: next.clip_id };
  if (selectedClip.value.audio_enabled !== next.audio_enabled) {
    const keepAudio = window.confirm("两个片段音频设置不同。合并后保留音频？取消则保留静音。\n");
    params.audio_enabled = keepAudio;
  }
  await call("merge_segments", params);
  await loadWindow();
}

async function toggleClipAudio() {
  if (!selectedClip.value) return;
  await call("set_segment_audio", { clip_id: selectedClip.value.clip_id, enabled: !selectedClip.value.audio_enabled });
}

async function muteAll() {
  if (!window.confirm("确认将全部片段设为静音？该操作可撤销。")) return;
  await call("set_all_audio", { enabled: false });
}

async function markChecked(cut: Project["cuts"][number]) {
  await call("mark_cut_checked", { cut_id: cut.cut_id, checked: !cut.checked });
}

async function undo() { await call("undo"); await loadWindow(); }
async function redo() { await call("redo"); await loadWindow(); }

async function confirmExport() {
  let allow = false;
  if (project.value?.pending_review_count) {
    allow = window.confirm(`仍有 ${project.value.pending_review_count} 个切点待检查。确认后将开始本地导出队列，是否继续？`);
    if (!allow) return;
  }
  const result = await call("start_export", { allow_unreviewed: allow });
  message.value = `已确认导出并加入本地队列（${result.jobs.length} 个片段）。编码、校验和安全提交已开始，源视频保持只读。\n`;
}
</script>

<template>
  <main class="shell">
    <header class="topbar">
      <div><span class="eyebrow">VIDEO2LIVEPHOTO / V1.0</span><h1>镜头审核工作台</h1></div>
      <span class="status" :class="{ live: project }">{{ project ? "项目已打开" : "等待导入" }}</span>
    </header>
    <section class="import-panel">
      <label>源视频路径<input v-model="sourcePath" placeholder="C:\\Videos\\wedding.mp4" /></label>
      <label>项目文件<input v-model="projectPath" placeholder="C:\\Projects\\wedding.m3.sqlite3" /></label>
      <button :disabled="busy" @click="importProject">导入并检测</button>
      <button class="secondary" :disabled="busy" @click="openProject">重开项目</button>
    </section>
    <section v-if="project" class="workspace">
      <aside class="rail">
        <div class="rail-title">检测与审核</div>
        <p class="muted">{{ project.detector_status === "not_connected" ? "M2 检测服务尚未接通；当前显示完整原始时间线。" : `检测：${project.detector_status}` }}</p>
        <div class="metric"><strong>{{ project.frame_count }}</strong><span>显示帧</span></div>
        <div class="metric"><strong>{{ project.segments.length }}</strong><span>片段</span></div>
        <div class="metric warn"><strong>{{ project.pending_review_count }}</strong><span>待检查切点</span></div>
        <h3>待检查列表</h3>
        <button v-for="cut in project.cuts.filter((item) => item.needs_review)" :key="cut.cut_id" class="review-item" :class="{ selected: cut.cut_id === selectedCutId }" @click="selectedCutId = cut.cut_id; center = cut.boundary_index; loadWindow()">
          帧 {{ cut.boundary_index }} · {{ cut.checked ? "已检查" : "待检查" }}
        </button>
      </aside>
      <section class="canvas">
        <div class="preview-card">
          <div class="preview-head"><span>逐帧预览窗口</span><span>当前帧 {{ center }} / {{ Math.max(0, project.frame_count - 1) }}</span></div>
          <div class="preview-image-wrap"><img v-if="previewData" class="preview-image" :src="previewData" alt="当前显示帧预览" /><span v-else class="muted">正在加载预览帧…</span></div>
          <div class="frame-strip"><button v-for="frame in frames" :key="frame.display_index" :class="{ active: frame.display_index === center }" @click="center = frame.display_index; loadWindow()">{{ frame.display_index }}<small>{{ frame.pict_type || "?" }}</small></button></div>
          <input class="scrub" type="range" :min="0" :max="Math.max(0, project.frame_count - 1)" v-model.number="center" @change="loadWindow" />
          <p class="muted">M1 PTS：{{ frames.find((frame) => frame.display_index === center)?.best_effort_pts ?? "—" }} · 时间基：{{ frames.find((frame) => frame.display_index === center)?.time_base_num ?? "—" }}/{{ frames.find((frame) => frame.display_index === center)?.time_base_den ?? "—" }}</p>
        </div>
        <div class="toolbar"><button @click="addCut">在当前帧增加切点</button><button :disabled="!selectedCut" @click="moveCut(-1)">切点 ←</button><button :disabled="!selectedCut" @click="moveCut(1)">切点 →</button><button :disabled="!selectedCut" @click="deleteCut">删除切点</button><button :disabled="!selectedClip" @click="mergeSelected">合并相邻片段</button><button @click="undo">撤销</button><button @click="redo">重做</button></div>
        <div class="timeline"><div v-for="segment in project.segments" :key="segment.clip_id" class="segment" :class="{ selected: segment.clip_id === selectedClipId }" @click="selectedClipId = segment.clip_id"><span>片段 {{ segment.output_number }}</span><strong>{{ segment.start_index }}–{{ segment.end_index }}</strong><small>{{ segment.end_index - segment.start_index }} 帧 · {{ segment.audio_enabled ? "保留音频" : "静音" }}</small></div></div>
      </section>
      <aside class="inspector"><div class="rail-title">片段设置</div><template v-if="selectedClip"><p><b>clip_id</b><br /><code>{{ selectedClip.clip_id }}</code></p><p><b>范围</b> {{ selectedClip.start_index }}–{{ selectedClip.end_index }}</p><button @click="toggleClipAudio">{{ selectedClip.audio_enabled ? "设为静音" : "恢复音频" }}</button><button class="secondary" @click="muteAll">全部静音</button></template><p v-else class="muted">点击时间线片段查看设置。</p><hr /><button class="primary" @click="confirmExport">确认并开始导出</button><p class="muted">确认后进入本地队列；失败、暂停和恢复由任务状态控制。</p></aside>
    </section>
    <pre class="log">{{ message }}</pre>
  </main>
</template>
