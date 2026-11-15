import { createApp } from 'vue'
import './styles/base.css'
import App from './app/App.vue'
import ConfigError from './features/shell/ConfigError.vue'
import { RUN_MODE, VITE_MODE } from './app/config'
import { createAdapter } from './adapters'
import { APP_ACTIONS, APP_CONTEXT, createAppContext } from './app/context'
import { createActions } from './app/actions'
import { vTip } from './components/tooltip'

async function boot() {
  if (RUN_MODE === 'invalid') {
    createApp(ConfigError, { mode: VITE_MODE }).mount('#root')
    return
  }
  const adapter = await createAdapter(RUN_MODE)
  const ctx = createAppContext(adapter)
  const actions = createActions(ctx)
  const app = createApp(App)
  app.provide(APP_CONTEXT, ctx)
  app.provide(APP_ACTIONS, actions)
  app.directive('tip', vTip)
  app.config.errorHandler = (err, _instance, info) => {
    console.error('[v2lp] unhandled UI error', info, err)
    ctx.ui.toast(`界面发生未处理错误：${err instanceof Error ? err.message : String(err)}（详情见诊断）`, { tone: 'danger', timeout: 8000 })
  }
  app.mount('#root')
}

void boot()
