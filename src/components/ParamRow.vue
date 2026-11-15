<script setup lang="ts">
defineProps<{ label: string; value?: string | number | null; mono?: boolean; muted?: boolean }>()
</script>

<template>
  <div class="prow">
    <dt class="prow__label">{{ label }}</dt>
    <dd class="prow__value" :class="{ 'num mono-ish': mono, muted }">
      <slot>{{ value ?? '—' }}</slot>
    </dd>
  </div>
</template>

<style scoped>
.prow {
  display: grid;
  grid-template-columns: minmax(84px, 38%) 1fr;
  align-items: baseline;
  gap: 8px;
  min-height: 24px;
  font-size: var(--fs-13);
}
.prow__label {
  color: var(--text-3);
}
.prow__value {
  color: var(--text-1);
  min-width: 0;
  overflow-wrap: anywhere;
}
.mono-ish {
  font-variant-numeric: tabular-nums;
}
</style>
