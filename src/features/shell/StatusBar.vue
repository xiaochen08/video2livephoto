<script setup lang="ts">
import { computed } from 'vue'
import { FlaskConical } from 'lucide-vue-next'
import { useApp } from '@/app/context'
import { rateToString } from '@/domain/time'
import { colorSummary } from '@/features/editor/mediaText'

const { session, conn, adapter, tasks, ui } = useApp()
const s = session.stream
const caps = computed(() => conn.value?.capabilities)
const versions = computed(() => {
  const p = session.project.value
  if (!p) return null
  return { edit: p.edit_version, run: tasks.runningVersion.value?.edit_version ?? null, last: tasks.lastSuccessVersion.value?.edit_version ?? null }
})
</script>

<template>
  <footer class="statusbar small">
    <button v-if="adapter.mode === 'demo'" type="button" class="statusbar__demo" :aria-expanded="ui.state.devPanelOpen" v-tip="'演示场景与故障注入（仅开发可见）'" @click="ui.state.devPanelOpen = !ui.state.devPanelOpen">
      <FlaskConical :size="11" aria-hidden="true" /> 演示数据 · 结果均为模拟 · 场景面板
    </button>
    <template v-if="s && session.project.value">
      <span class="num">{{ s.width }}×{{ s.height }}</span>
      <span class="num">{{ rateToString(s.frame_rate) }} fps{{ s.vfr ? ' · VFR' : '' }}</span>
      <span>{{ colorSummary(s.color) }}</span>
      <span>{{ session.hasAudio.value ? '有音轨' : '源视频无音轨' }}</span>
      <span v-if="versions" class="num" v-tip="'当前编辑版本 / 正在运行导出所用版本 / 最近成功导出的版本'">
        编辑 v{{ versions.edit }}<template v-if="versions.run !== null"> · 运行 v{{ versions.run }}</template><template v-if="versions.last !== null"> · 最近成功 v{{ versions.last }}</template>
      </span>
    </template>
    <span class="grow"></span>
    <span v-if="caps" v-tip="caps.gpu.note ?? '经过验证的 GPU 编码路径'">编码：{{ caps.gpu.available ? `GPU 优先（${caps.gpu.verified_encoder}）` : 'CPU' }}</span>
    <span>{{ conn?.backend_version ?? '未连接' }}</span>
  </footer>
</template>

<style scoped>
.statusbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 12px;
  background: var(--bg-app);
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  font-size: var(--fs-11);
}
.statusbar__demo {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--demo);
  font-size: var(--fs-11);
  padding: 1px 6px;
  border: 1px dashed rgba(201, 154, 90, 0.45);
  border-radius: var(--r-1);
}
.statusbar__demo:hover {
  background: rgba(201, 154, 90, 0.1);
}
</style>
