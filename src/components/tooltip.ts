import type { Directive } from 'vue'

/**
 * v-tip: lightweight styled tooltip (one shared element). Shows after 450ms hover or on keyboard
 * focus. Value: string or { text, kbd }. Icon-only buttons must ALSO carry aria-label.
 */
type TipValue = string | { text: string; kbd?: string } | null | undefined

let el: HTMLDivElement | null = null
let timer: ReturnType<typeof setTimeout> | null = null
let owner: HTMLElement | null = null

function ensure() {
  if (el) return el
  el = document.createElement('div')
  el.className = 'v2-tooltip'
  el.setAttribute('role', 'tooltip')
  document.body.appendChild(el)
  return el
}

function show(target: HTMLElement, value: TipValue) {
  if (!value) return
  const tip = ensure()
  const text = typeof value === 'string' ? value : value.text
  const kbd = typeof value === 'string' ? undefined : value.kbd
  tip.textContent = text
  if (kbd) {
    const k = document.createElement('span')
    k.className = 'kbd'
    k.textContent = kbd
    tip.appendChild(k)
  }
  tip.style.display = 'flex'
  const r = target.getBoundingClientRect()
  const tr = tip.getBoundingClientRect()
  let top = r.bottom + 6
  if (top + tr.height > window.innerHeight - 4) top = r.top - tr.height - 6
  let left = r.left + r.width / 2 - tr.width / 2
  left = Math.max(4, Math.min(left, window.innerWidth - tr.width - 4))
  tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`
  tip.dataset.visible = 'true'
  owner = target
}

function hide() {
  if (timer) clearTimeout(timer)
  timer = null
  if (el) {
    el.dataset.visible = 'false'
    el.style.display = 'none'
  }
  owner = null
}

interface TipEl extends HTMLElement {
  __tip?: TipValue
  __tipOff?: () => void
}

export const vTip: Directive<TipEl, TipValue> = {
  mounted(target, binding) {
    target.__tip = binding.value
    const enter = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => show(target, target.__tip), 450)
    }
    const focus = () => {
      if (target.matches(':focus-visible')) show(target, target.__tip)
    }
    target.addEventListener('mouseenter', enter)
    target.addEventListener('mouseleave', hide)
    target.addEventListener('focus', focus)
    target.addEventListener('blur', hide)
    target.addEventListener('pointerdown', hide)
    target.__tipOff = () => {
      target.removeEventListener('mouseenter', enter)
      target.removeEventListener('mouseleave', hide)
      target.removeEventListener('focus', focus)
      target.removeEventListener('blur', hide)
      target.removeEventListener('pointerdown', hide)
    }
  },
  updated(target, binding) {
    target.__tip = binding.value
  },
  beforeUnmount(target) {
    target.__tipOff?.()
    if (owner === target) hide()
  },
}

declare module 'vue' {
  interface GlobalDirectives {
    vTip: typeof vTip
  }
}
