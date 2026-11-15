<script setup lang="ts">
defineProps<{ mode: string }>()
</script>

<template>
  <main class="cfg">
    <h1>未指定运行模式</h1>
    <p>
      当前构建模式为 <code>{{ mode }}</code>。请使用 <code>--mode demo</code>（浏览器演示）或 <code>--mode desktop</code>（桌面接入）启动。生产环境不会自动使用演示数据。
    </p>
  </main>
</template>

<style scoped>
.cfg {
  max-width: 560px;
  margin: 15vh auto;
  padding: 24px;
  display: grid;
  gap: 12px;
  color: var(--text-1);
}
h1 {
  font-size: var(--fs-18);
}
p {
  color: var(--text-2);
}
code {
  font-family: var(--font-mono);
  background: var(--bg-control);
  padding: 1px 5px;
  border-radius: var(--r-1);
}
</style>
