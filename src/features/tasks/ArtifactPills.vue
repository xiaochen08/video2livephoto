<script setup lang="ts">
import type { Artifact } from '@/domain/types'
import { ARTIFACT_STATUS } from './jobText'
defineProps<{ artifacts: Artifact[] }>()
</script>

<template>
  <span class="pills" :aria-label="artifacts.map((a) => `${a.kind.toUpperCase()} ${ARTIFACT_STATUS[a.status].label}`).join('，')">
    <span v-for="a in artifacts" :key="a.kind" class="pill" :data-tone="ARTIFACT_STATUS[a.status].tone" :title="`${a.rel_dir}/${a.file_name} · ${ARTIFACT_STATUS[a.status].label}`">{{ a.kind.toUpperCase() }}</span>
  </span>
</template>

<style scoped>
.pills {
  display: inline-flex;
  gap: 3px;
}
.pill {
  font-size: 10px;
  line-height: 16px;
  padding: 0 4px;
  border-radius: 2px;
  font-weight: var(--fw-semibold);
  letter-spacing: 0.02em;
  color: var(--text-3);
  box-shadow: inset 0 0 0 1px var(--line-strong);
}
.pill[data-tone='accent'] {
  color: var(--accent-hover);
  box-shadow: inset 0 0 0 1px var(--accent-line);
}
.pill[data-tone='success'] {
  color: var(--success);
  background: var(--success-soft);
  box-shadow: none;
}
.pill[data-tone='danger'] {
  color: var(--danger);
  background: var(--danger-soft);
  box-shadow: none;
}
.pill[data-tone='warning'] {
  color: var(--warning);
  background: var(--warning-soft);
  box-shadow: none;
}
</style>
