<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Minimize2 } from 'lucide-vue-next'
import UiButton from '@/components/UiButton.vue'

/** Minimum usable CSS viewport: 960 × 540 (1920×1080 at 200% scaling). Below it the app explains. */
const MIN_W = 960
const MIN_H = 540
const tooSmall = ref(false)
const dismissed = ref(false)
const size = ref({ w: 0, h: 0 })
function check() {
  size.value = { w: window.innerWidth, h: window.innerHeight }
  tooSmall.value = window.innerWidth < MIN_W || window.innerHeight < MIN_H
  if (!tooSmall.value) dismissed.value = false
}
onMounted(() => {
  check()
  window.addEventListener('resize', check)
})
onBeforeUnmount(() => window.removeEventListener('resize', check))
</script>

<template>
  <div v-if="tooSmall && !dismissed" class="small-win" role="alertdialog" aria-labelledby="sw-title">
    <div class="small-win__card">
      <Minimize2 :size="22" :stroke-width="1.5" aria-hidden="true" />
      <h2 id="sw-title">窗口过小</h2>
      <p>
        当前可用区域 <span class="num">{{ size.w }} × {{ size.h }}</span>，最小可用尺寸为 <span class="num">{{ MIN_W }} × {{ MIN_H }}</span>。请放大窗口或降低 Windows 显示缩放。
      </p>
      <UiButton variant="ghost" size="sm" @click="dismissed = true">仍然继续（部分面板可能被遮挡）</UiButton>
    </div>
  </div>
</template>

<style scoped>
.small-win {
  position: fixed;
  inset: 0;
  z-index: 95;
  background: rgba(10, 11, 12, 0.94);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.small-win__card {
  max-width: 380px;
  display: grid;
  gap: 10px;
  justify-items: start;
  color: var(--text-2);
}
h2 {
  color: var(--text-1);
  font-size: var(--fs-16);
}
</style>
