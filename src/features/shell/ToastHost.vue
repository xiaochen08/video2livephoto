<script setup lang="ts">
import { AlertTriangle, Check, Info, X } from 'lucide-vue-next'
import { useApp } from '@/app/context'
const { ui } = useApp()
</script>

<template>
  <div class="toasts" aria-live="polite" aria-atomic="false">
    <TransitionGroup name="toast">
      <div v-for="t in ui.state.toasts" :key="t.id" class="toast" :class="`toast--${t.tone}`" role="status">
        <span class="toast__ic" aria-hidden="true">
          <Check v-if="t.tone === 'success'" :size="13" :stroke-width="3" />
          <AlertTriangle v-else-if="t.tone === 'warning'" :size="13" :stroke-width="2.6" />
          <X v-else-if="t.tone === 'danger'" :size="13" :stroke-width="3" />
          <Info v-else :size="13" :stroke-width="2.6" />
        </span>
        <span class="toast__msg">{{ t.message }}</span>
        <button
          v-if="t.action"
          type="button"
          class="toast__action"
          @click="
            () => {
              t.action!.run()
              ui.dismissToast(t.id)
            }
          "
        >
          {{ t.action.label }}
        </button>
        <button type="button" class="toast__close" aria-label="关闭通知" @click="ui.dismissToast(t.id)"><X :size="14" /></button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  left: 50%;
  bottom: calc(var(--statusbar-h) + 16px);
  transform: translateX(-50%);
  z-index: var(--z-toast);
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  pointer-events: none;
  width: min(560px, calc(100vw - 32px));
}
.toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 8px 7px 8px;
  min-height: 40px;
  background: var(--bg-raised);
  border-radius: var(--r-3);
  box-shadow: var(--shadow-pop);
  font-size: var(--fs-13);
  max-width: 100%;
}
.toast__ic {
  width: 24px;
  height: 24px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex: none;
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-1);
  animation: toast-pop var(--dur-spring) var(--ease-spring);
}
.toast--success .toast__ic {
  background: var(--success);
  color: #04200a;
}
.toast--warning .toast__ic {
  background: var(--warning);
  color: #1f1a00;
}
.toast--danger .toast__ic {
  background: var(--danger);
  color: #fff;
}
@keyframes toast-pop {
  from {
    transform: scale(0.3);
  }
}
.toast__msg {
  flex: 1;
  min-width: 0;
}
.toast__action {
  color: var(--text-1);
  font-weight: var(--fw-semibold);
  padding: 4px 8px;
  border-radius: var(--r-1);
}
.toast__action:hover {
  background: var(--bg-control-hover);
}
.toast__close {
  color: var(--text-3);
  padding: 4px;
  border-radius: var(--r-1);
}
.toast__close:hover {
  color: var(--text-1);
  background: var(--bg-control);
}
.toast-enter-active {
  transition:
    opacity var(--dur-select) var(--ease-out),
    transform var(--dur-spring) var(--ease-spring);
}
.toast-leave-active {
  transition:
    opacity var(--dur-select) var(--ease-out),
    transform var(--dur-select) var(--ease-out);
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(14px) scale(0.94);
}
.toast-leave-to {
  opacity: 0;
  transform: scale(0.96);
}
</style>
