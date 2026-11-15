<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { useApp } from '@/app/context'

import type { MenuItem } from './menu'
defineProps<{ items: MenuItem[]; label: string; align?: 'left' | 'right' }>()
const { ui } = useApp()
const open = ref(false)
const root = ref<HTMLElement>()
const list = ref<HTMLElement>()
const oid = `menu-${Math.random().toString(36).slice(2, 8)}`
let trigger: HTMLElement | null = null

function onDoc(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) close()
}
async function toggle(e: MouseEvent) {
  if (open.value) return close()
  trigger = e.currentTarget as HTMLElement
  open.value = true
  ui.pushOverlay({ id: oid, close, closable: () => true })
  document.addEventListener('mousedown', onDoc)
  await nextTick()
  list.value?.querySelector<HTMLElement>('[role="menuitem"]:not([aria-disabled])')?.focus()
}
function close() {
  if (!open.value) return
  open.value = false
  ui.popOverlay(oid)
  document.removeEventListener('mousedown', onDoc)
  trigger?.focus()
}
function pick(item: MenuItem) {
  if (item.disabled) return
  close()
  item.run()
}
function onKey(e: KeyboardEvent) {
  const items = [...(list.value?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled])') ?? [])]
  const i = items.indexOf(document.activeElement as HTMLElement)
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    items[(i + 1) % items.length]?.focus()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    items[(i - 1 + items.length) % items.length]?.focus()
  } else if (e.key === 'Tab') close()
}
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDoc)
  ui.popOverlay(oid)
})
</script>

<template>
  <div ref="root" class="menu">
    <slot name="trigger" :toggle="toggle" :open="open" :id="oid" />
    <Transition name="menu">
      <div v-if="open" ref="list" :id="oid" class="menu__list" :class="`menu__list--${align ?? 'right'}`" role="menu" :aria-label="label" @keydown="onKey">
        <button
          v-for="it in items"
          :key="it.id"
          type="button"
          role="menuitem"
          class="menu__item"
          :class="{ 'is-danger': it.danger }"
          :aria-disabled="it.disabled || undefined"
          @click.stop="pick(it)"
        >
          <span class="menu__label">{{ it.label }}</span>
          <span v-if="it.hint" class="menu__hint">{{ it.hint }}</span>
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.menu {
  position: relative;
  display: inline-flex;
}
.menu__list {
  position: absolute;
  top: calc(100% + 4px);
  z-index: var(--z-popover);
  min-width: 240px;
  max-width: 320px;
  padding: 4px;
  background: var(--bg-overlay);
  border-radius: var(--r-2);
  box-shadow: var(--shadow-pop);
}
.menu__list--right {
  right: 0;
}
.menu__list--left {
  left: 0;
}
.menu__item {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 7px 10px;
  border-radius: var(--r-1);
  text-align: left;
}
.menu__item:hover:not([aria-disabled]),
.menu__item:focus-visible {
  background: var(--bg-control-hover);
  box-shadow: none;
}
.menu__label {
  font-size: var(--fs-13);
}
.menu__hint {
  font-size: var(--fs-12);
  color: var(--text-3);
  line-height: 1.4;
}
.menu__item.is-danger .menu__label {
  color: var(--danger);
}
.menu__item[aria-disabled] {
  opacity: 0.45;
  cursor: not-allowed;
}
.menu-enter-active,
.menu-leave-active {
  transition:
    opacity var(--dur-select) var(--ease-out),
    transform var(--dur-select) var(--ease-out);
}
.menu-enter-from,
.menu-leave-to {
  opacity: 0;
  transform: translateY(-3px);
}
</style>
