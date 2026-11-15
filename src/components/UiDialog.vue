<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useApp } from '@/app/context'

/**
 * Modal dialog / drawer.
 *  - focus moves inside on open and returns to the trigger on close
 *  - Tab is trapped; Esc closes the top-most closable overlay (handled centrally in ui.escape)
 *  - header and footer stay visible; only the body scrolls
 */
const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    description?: string
    size?: 'sm' | 'md' | 'lg' | 'xl'
    placement?: 'center' | 'right'
    closable?: boolean
    dismissOnScrim?: boolean
    /** reason shown when closing is blocked (e.g. waiting for a safe point) */
    blockedReason?: string | null
  }>(),
  { size: 'md', placement: 'center', closable: true, dismissOnScrim: true },
)
const emit = defineEmits<{ close: [] }>()
const { ui } = useApp()
const panel = ref<HTMLElement>()
const id = `dlg-${Math.random().toString(36).slice(2, 8)}`
let returnTo: HTMLElement | null = null

const FOCUSABLE = 'button:not([disabled]):not([aria-disabled="true"]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function requestClose() {
  if (props.closable && !props.blockedReason) emit('close')
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      returnTo = document.activeElement as HTMLElement | null
      ui.pushOverlay({ id, close: requestClose, closable: () => props.closable && !props.blockedReason })
      await nextTick()
      const el = panel.value
      const af = el?.querySelector<HTMLElement>('[data-autofocus]')
      const afTarget = af ? (af.matches(FOCUSABLE) ? af : af.querySelector<HTMLElement>(FOCUSABLE)) : null
      const target = afTarget ?? el?.querySelector<HTMLElement>('.dlg__body ' + FOCUSABLE) ?? el
      target?.focus()
    } else {
      ui.popOverlay(id)
      if (returnTo && document.contains(returnTo)) returnTo.focus()
      returnTo = null
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  ui.popOverlay(id)
  if (props.open && returnTo && document.contains(returnTo)) returnTo.focus()
})

function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Tab' || !panel.value) return
  const items = [...panel.value.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => x.offsetParent !== null)
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="dlg">
      <div v-if="open" class="dlg-scrim" :class="`dlg-scrim--${placement}`" @mousedown.self="dismissOnScrim && requestClose()">
        <section
          ref="panel"
          class="dlg"
          :class="[`dlg--${size}`, `dlg--${placement}`]"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="`${id}-title`"
          :aria-describedby="description ? `${id}-desc` : undefined"
          tabindex="-1"
          @keydown="onKeydown"
        >
          <header class="dlg__header">
            <div class="dlg__heading">
              <h2 :id="`${id}-title`" class="dlg__title">{{ title }}</h2>
              <p v-if="description" :id="`${id}-desc`" class="dlg__desc">{{ description }}</p>
            </div>
            <slot name="header-extra" />
            <button
              v-if="closable"
              type="button"
              class="dlg__close"
              :aria-label="blockedReason ? `关闭（${blockedReason}）` : '关闭'"
              :aria-disabled="!!blockedReason || undefined"
              :title="blockedReason ?? '关闭 (Esc)'"
              @click="requestClose"
            >
              <X :size="16" :stroke-width="1.75" />
            </button>
          </header>
          <div class="dlg__body"><slot /></div>
          <footer v-if="$slots.footer" class="dlg__footer"><slot name="footer" /></footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dlg-scrim {
  position: fixed;
  inset: 0;
  z-index: var(--z-dialog);
  background: var(--bg-scrim);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.dlg-scrim--right {
  justify-content: flex-end;
  align-items: stretch;
  padding: 0;
  background: rgba(0, 0, 0, 0.4);
}
.dlg {
  display: flex;
  flex-direction: column;
  max-height: min(calc(100vh - 48px), 880px);
  width: 100%;
  background: var(--bg-overlay);
  border-radius: var(--r-4);
  box-shadow: var(--shadow-dialog);
  overflow: hidden;
}
.dlg--sm {
  max-width: 420px;
}
.dlg--md {
  max-width: 560px;
}
.dlg--lg {
  max-width: 760px;
}
.dlg--xl {
  max-width: 1040px;
}
.dlg--right {
  max-height: none;
  height: 100%;
  border-radius: 0;
  max-width: 480px;
}
.dlg__header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px 16px 12px 20px;
  border-bottom: 1px solid var(--line-subtle);
  flex: none;
}
.dlg__heading {
  flex: 1;
  min-width: 0;
}
.dlg__title {
  font-size: var(--fs-16);
  font-weight: var(--fw-semibold);
  line-height: 1.35;
}
.dlg__desc {
  margin-top: 4px;
  font-size: var(--fs-13);
  color: var(--text-3);
}
.dlg__close {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--r-2);
  color: var(--text-3);
  flex: none;
}
.dlg__close:hover:not([aria-disabled]) {
  background: var(--bg-control);
  color: var(--text-1);
}
.dlg__close[aria-disabled] {
  opacity: 0.4;
  cursor: not-allowed;
}
.dlg__body {
  flex: 1 1 auto;
  overflow: auto;
  padding: 16px 20px 20px;
  min-height: 0;
}
.dlg__footer {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px 12px 20px;
  border-top: 1px solid var(--line-subtle);
  background: var(--bg-panel);
  flex-wrap: wrap;
}

.dlg-enter-active,
.dlg-leave-active {
  transition: opacity var(--dur-panel) var(--ease-out);
}
.dlg-enter-active .dlg,
.dlg-leave-active .dlg {
  transition:
    transform var(--dur-panel) var(--ease-out),
    opacity var(--dur-panel) var(--ease-out);
}
.dlg-enter-from,
.dlg-leave-to {
  opacity: 0;
}
.dlg-enter-active .dlg--center {
  transition:
    transform var(--dur-spring) var(--ease-spring),
    opacity var(--dur-panel) var(--ease-out);
}
.dlg-enter-from .dlg--center {
  transform: translateY(10px) scale(0.97);
}
.dlg-enter-from .dlg--right,
.dlg-leave-to .dlg--right {
  transform: translateX(24px);
}
.dlg-leave-active {
  transition-duration: calc(var(--dur-panel) * 0.7);
}
</style>
