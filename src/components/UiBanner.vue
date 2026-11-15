<script setup lang="ts">
import { AlertTriangle, CircleCheck, CircleX, Info, X, FlaskConical } from 'lucide-vue-next'
import { computed } from 'vue'

const props = withDefaults(defineProps<{ tone?: 'info' | 'success' | 'warning' | 'danger' | 'demo'; title?: string; dismissible?: boolean; compact?: boolean }>(), { tone: 'info' })
defineEmits<{ dismiss: [] }>()
const icon = computed(() => ({ info: Info, success: CircleCheck, warning: AlertTriangle, danger: CircleX, demo: FlaskConical })[props.tone])
</script>

<template>
  <div class="banner" :class="[`banner--${tone}`, { 'banner--compact': compact }]" :role="tone === 'danger' ? 'alert' : 'status'">
    <component :is="icon" :size="16" :stroke-width="1.75" class="banner__icon" aria-hidden="true" />
    <div class="banner__body">
      <p v-if="title" class="banner__title">{{ title }}</p>
      <div class="banner__text"><slot /></div>
    </div>
    <div v-if="$slots.actions" class="banner__actions"><slot name="actions" /></div>
    <button v-if="dismissible" type="button" class="banner__close" aria-label="关闭提示" @click="$emit('dismiss')"><X :size="14" /></button>
  </div>
</template>

<style scoped>
.banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--r-3);
  background: var(--bg-raised);
  border: 1px solid var(--line);
  font-size: var(--fs-13);
  animation: v2-fade-in var(--dur-select) var(--ease-out);
}
.banner--compact {
  padding: 7px 10px;
  align-items: center;
}
.banner__icon {
  flex: none;
  margin-top: 2px;
}
.banner--compact .banner__icon {
  margin-top: 0;
}
.banner__body {
  flex: 1;
  min-width: 0;
}
.banner__title {
  font-weight: var(--fw-semibold);
  margin-bottom: 2px;
}
.banner__text {
  color: var(--text-2);
  line-height: 1.5;
}
.banner__actions {
  display: flex;
  gap: 6px;
  flex: none;
  align-items: center;
  flex-wrap: wrap;
}
.banner__close {
  color: var(--text-3);
  padding: 2px;
  border-radius: var(--r-1);
}
.banner__close:hover {
  color: var(--text-1);
  background: var(--bg-control);
}
.banner--info .banner__icon {
  color: var(--accent);
}
.banner--success {
  border-color: rgba(50, 215, 75, 0.3);
}
.banner--success .banner__icon {
  color: var(--success);
}
.banner--warning {
  border-color: rgba(255, 214, 10, 0.3);
  background: linear-gradient(0deg, var(--warning-soft), var(--warning-soft)), var(--bg-raised);
}
.banner--warning .banner__icon {
  color: var(--warning);
}
.banner--danger {
  border-color: rgba(255, 69, 58, 0.38);
  background: linear-gradient(0deg, var(--danger-soft), var(--danger-soft)), var(--bg-raised);
}
.banner--danger .banner__icon {
  color: var(--danger);
}
.banner--demo {
  border-style: dashed;
  border-color: rgba(201, 154, 90, 0.45);
}
.banner--demo .banner__icon {
  color: var(--demo);
}
</style>
