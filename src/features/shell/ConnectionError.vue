<script setup lang="ts">
import { PlugZap, RotateCcw } from 'lucide-vue-next'
import { ref } from 'vue'
import UiButton from '@/components/UiButton.vue'
import type { AppError } from '@/domain/types'
import { VITE_MODE } from '@/app/config'

defineProps<{ error: AppError | null; retrying: boolean }>()
defineEmits<{ retry: [] }>()
const showDiag = ref(false)
const ua = navigator.userAgent
const bridged = 'v2lpBridge' in window
</script>

<template>
  <main class="conn">
    <div class="conn__card">
      <PlugZap :size="28" :stroke-width="1.5" class="conn__icon" aria-hidden="true" />
      <h1>无法连接桌面后端</h1>
      <p class="secondary">{{ error?.message ?? '连接失败。' }}</p>
      <p v-if="error?.detail" class="small muted">{{ error.detail }}</p>
      <p class="small muted">生产模式不会改用演示数据。界面在连接成功前不显示任何项目或任务结果。</p>
      <div class="row conn__actions">
        <UiButton variant="primary" :icon="RotateCcw" :loading="retrying" loading-label="正在重新连接…" @click="$emit('retry')">重新连接</UiButton>
        <UiButton variant="ghost" @click="showDiag = !showDiag">{{ showDiag ? '隐藏诊断信息' : '查看诊断信息' }}</UiButton>
      </div>
      <dl v-if="showDiag" class="conn__diag small mono">
        <div><dt>错误码</dt><dd>{{ error?.code ?? '—' }}</dd></div>
        <div><dt>构建模式</dt><dd>{{ VITE_MODE }}</dd></div>
        <div><dt>桌面桥接</dt><dd>{{ bridged ? '已注入' : '未注入 (window.v2lpBridge)' }}</dd></div>
        <div><dt>界面构建</dt><dd>{{ ua }}</dd></div>
      </dl>
    </div>
  </main>
</template>

<style scoped>
.conn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.conn__card {
  max-width: 520px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.conn__icon {
  color: var(--danger);
}
h1 {
  font-size: var(--fs-18);
}
.conn__actions {
  margin-top: 8px;
}
.conn__diag {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: var(--r-2);
  display: grid;
  gap: 4px;
  user-select: text;
}
.conn__diag div {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 8px;
}
.conn__diag dt {
  color: var(--text-3);
}
.conn__diag dd {
  overflow-wrap: anywhere;
}
</style>
