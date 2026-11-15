<script setup lang="ts">
import { CircleX, Copy } from 'lucide-vue-next'
import { ACTION_LABEL, errorToClipboardText } from '@/domain/errors'
import type { AppError, ErrorActionKind } from '@/domain/types'
import UiButton from './UiButton.vue'
import { useApp } from '@/app/context'

/** Structured error: where (project / clip / stage), what is preserved, what the user can do. */
const props = defineProps<{ error: AppError; context: string; where?: string; compact?: boolean; busyAction?: ErrorActionKind | null; hide?: ErrorActionKind[] }>()
const emit = defineEmits<{ action: [ErrorActionKind] }>()
const { ui } = useApp()

async function copy() {
  const text = errorToClipboardText(props.error, props.context)
  try {
    await navigator.clipboard.writeText(text)
    ui.toast('错误信息已复制', { tone: 'success', timeout: 2200 })
  } catch {
    ui.dialogs.report.value = { title: '错误信息', body: text }
  }
}
function act(a: ErrorActionKind) {
  if (a === 'copy_error') return copy()
  emit('action', a)
}
</script>

<template>
  <div class="err" :class="{ 'err--compact': compact }" role="alert">
    <div class="err__head">
      <CircleX :size="16" :stroke-width="1.75" class="err__icon" aria-hidden="true" />
      <div class="err__main">
        <p class="err__msg">{{ error.message }}</p>
        <p class="err__meta small">
          <span v-if="where">{{ where }} · </span><span v-if="error.scope.stage">阶段：{{ error.scope.stage }} · </span><span class="mono">{{ error.code }}</span>
        </p>
      </div>
    </div>
    <p v-if="error.preserved" class="err__preserved small"><strong>已保留：</strong>{{ error.preserved }}</p>
    <p v-if="error.detail && !compact" class="err__detail mono small">{{ error.detail }}</p>
    <div class="err__actions">
      <UiButton
        v-for="(a, i) in error.actions.filter((x) => x !== 'copy_error' && !hide?.includes(x))"
        :key="a"
        size="sm"
        :variant="i === 0 ? 'secondary' : 'ghost'"
        :loading="busyAction === a"
        @click="act(a)"
      >
        {{ ACTION_LABEL[a] }}
      </UiButton>
      <UiButton size="sm" variant="ghost" :icon="Copy" @click="copy">复制错误信息</UiButton>
    </div>
  </div>
</template>

<style scoped>
.err {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: var(--r-3);
  border: 1px solid rgba(255, 69, 58, 0.35);
  background: linear-gradient(0deg, var(--danger-soft), var(--danger-soft)), var(--bg-raised);
}
.err--compact {
  padding: 10px;
  gap: 6px;
}
.err__head {
  display: flex;
  gap: 10px;
}
.err__icon {
  color: var(--danger);
  margin-top: 2px;
  flex: none;
}
.err__main {
  min-width: 0;
}
.err__msg {
  font-size: var(--fs-13);
  font-weight: var(--fw-medium);
  line-height: 1.5;
}
.err__meta {
  color: var(--text-3);
}
.err__preserved {
  color: var(--text-2);
  padding-left: 26px;
}
.err__preserved strong {
  color: var(--success);
  font-weight: var(--fw-medium);
}
.err__detail {
  color: var(--text-3);
  padding-left: 26px;
  overflow-wrap: anywhere;
  user-select: text;
}
.err__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-left: 20px;
}
</style>
