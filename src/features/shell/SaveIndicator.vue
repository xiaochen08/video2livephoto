<script setup lang="ts">
import { Check, CircleAlert, Dot } from 'lucide-vue-next'
import { computed } from 'vue'
import { useActions, useApp } from '@/app/context'
import UiSpinner from '@/components/UiSpinner.vue'

const { session, adapter } = useApp()
const actions = useActions()
const demo = adapter.mode === 'demo'
const label = computed(() => {
  switch (session.saveState.value) {
    case 'saved':
      return demo ? '已保存（模拟）' : '已保存'
    case 'dirty':
      return '有修改'
    case 'saving':
      return '保存中…'
    case 'failed':
      return '保存失败'
  }
  return ''
})
</script>

<template>
  <div class="save" :data-state="session.saveState.value" role="status" aria-live="polite">
    <UiSpinner v-if="session.saveState.value === 'saving'" :size="11" label="保存中" />
    <Check v-else-if="session.saveState.value === 'saved'" :size="13" :stroke-width="2" aria-hidden="true" />
    <CircleAlert v-else-if="session.saveState.value === 'failed'" :size="13" :stroke-width="2" aria-hidden="true" />
    <Dot v-else :size="16" :stroke-width="4" aria-hidden="true" class="save__dot" />
    <span>{{ label }}</span>
    <button
      v-if="session.saveState.value === 'failed' || session.saveState.value === 'dirty'"
      type="button"
      class="save__btn"
      v-tip="session.state.saveError ? session.state.saveError.message : '立即保存 (Ctrl+S)'"
      @click="actions.save()"
    >
      {{ session.saveState.value === 'failed' ? '重试' : '保存' }}
    </button>
  </div>
</template>

<style scoped>
.save {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-12);
  color: var(--text-3);
  white-space: nowrap;
  min-width: 0;
}
.save[data-state='dirty'] {
  color: var(--text-2);
}
.save__dot {
  color: var(--warning);
  margin: 0 -4px;
}
.save[data-state='failed'] {
  color: var(--danger);
}
.save__btn {
  color: var(--accent-hover);
  font-weight: var(--fw-medium);
  padding: 1px 6px;
  border-radius: var(--r-1);
}
.save__btn:hover {
  background: var(--accent-soft);
}
</style>
