<script setup lang="ts">
import { defineAsyncComponent, onBeforeUnmount, onErrorCaptured, onMounted, ref } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import { useActions, useApp } from './context'
import { useGlobalKeys } from './keyboard'
import { SHOW_DEV_TOOLS } from './config'
import { toAppError } from '@/domain/errors'
import HomeView from '@/features/home/HomeView.vue'
import EditorView from '@/features/editor/EditorView.vue'
import TasksView from '@/features/tasks/TasksView.vue'
import SettingsView from '@/features/settings/SettingsView.vue'
import ConnectionError from '@/features/shell/ConnectionError.vue'
import AppTopBar from '@/features/shell/AppTopBar.vue'
import StatusBar from '@/features/shell/StatusBar.vue'
import ToastHost from '@/features/shell/ToastHost.vue'
import DialogsHost from '@/features/shell/DialogsHost.vue'
import SmallWindowNotice from '@/features/shell/SmallWindowNotice.vue'

// dev-only panel, loaded lazily so desktop builds never pull demo code into the main chunk
const DevPanel = import.meta.env.MODE === 'desktop' ? null : defineAsyncComponent(() => import('@/features/dev/DevPanel.vue'))
const ctx = useApp()
const actions = useActions()
const { ui, adapter, conn, home } = ctx
const connecting = ref(false)
/** Top-level error boundary: a failing page shows a recoverable panel instead of a blank window. */
const renderError = ref<string | null>(null)
onErrorCaptured((err: unknown) => {
  console.error('[v2lp] render error', err)
  renderError.value = err instanceof Error ? err.message : String(err)
  return false
})
function recoverFromRenderError() {
  renderError.value = null
  void actions.goHome()
}

async function connect() {
  connecting.value = true
  ui.state.connectionError = null
  try {
    conn.value = await adapter.connect()
    ui.state.route = 'home'
    void home.loadRecents()
  } catch (e) {
    // Production never falls back to demo data: show the connection error with diagnostics.
    ui.state.connectionError = toAppError(e)
    ui.state.route = 'connection_error'
  } finally {
    connecting.value = false
  }
}

useGlobalKeys(ctx, actions, { openPicker: () => ui.state.pickerRequest++ })

let offClose: (() => void) | null = null
function beforeUnload(e: BeforeUnloadEvent) {
  if (ctx.session.dirty.value || ctx.tasks.activeBatch.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}
onMounted(() => {
  void connect()
  offClose = adapter.app.onCloseRequested(() => void actions.requestClose())
  if (adapter.mode === 'demo') window.addEventListener('beforeunload', beforeUnload)
})
onBeforeUnmount(() => {
  offClose?.()
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<template>
  <div class="app" :data-route="ui.state.route">
    <div v-if="ui.state.route === 'boot'" class="boot" role="status">
      <Loader2 :size="18" class="boot__spin" aria-hidden="true" />
      <span>正在连接{{ adapter.mode === 'demo' ? '演示适配器' : '桌面后端' }}…</span>
    </div>
    <ConnectionError v-else-if="ui.state.route === 'connection_error'" :error="ui.state.connectionError" :retrying="connecting" @retry="connect" />
    <template v-else>
      <AppTopBar />
      <main class="app__main">
        <div v-if="renderError" class="boot boot--error" role="alert">
          <p>页面渲染出错：{{ renderError }}。项目数据与后台任务不受影响。</p>
          <button type="button" class="boot__btn" @click="recoverFromRenderError">返回首页</button>
        </div>
        <HomeView v-else-if="ui.state.route === 'home'" />
        <EditorView v-else-if="ui.state.route === 'editor'" />
        <TasksView v-else-if="ui.state.route === 'tasks'" />
        <SettingsView v-else-if="ui.state.route === 'settings'" />
      </main>
      <StatusBar />
    </template>
    <DialogsHost v-if="conn" />
    <ToastHost />
    <component :is="DevPanel" v-if="DevPanel && SHOW_DEV_TOOLS && adapter.mode === 'demo'" />
    <SmallWindowNotice />
  </div>
</template>

<style scoped>
.app {
  height: 100%;
  display: grid;
  grid-template-rows: var(--topbar-h) minmax(0, 1fr) var(--statusbar-h);
  background: var(--bg-app);
  min-width: 0;
}
.app[data-route='boot'],
.app[data-route='connection_error'] {
  grid-template-rows: 1fr;
}
.app__main {
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  position: relative;
}
.boot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-2);
}
.boot--error {
  height: 100%;
  flex-direction: column;
  color: var(--text-1);
}
.boot__btn {
  padding: 6px 12px;
  border-radius: var(--r-2);
  background: var(--bg-control);
  border: 1px solid var(--line-strong);
}
.boot__spin {
  animation: v2-spin 1s linear infinite;
}
</style>
