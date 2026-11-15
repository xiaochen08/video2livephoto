<script setup lang="ts">
defineProps<{ title: string; aside?: string }>()
</script>

<template>
  <section class="isec">
    <header class="isec__head">
      <h3 class="section-title">{{ title }}</h3>
      <span v-if="aside" class="small muted">{{ aside }}</span>
      <slot name="aside" />
    </header>
    <div class="isec__body"><slot /></div>
  </section>
</template>

<style scoped>
.isec {
  padding: 12px 14px 14px;
  border-bottom: 1px solid var(--line-subtle);
}
.isec__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.isec__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
