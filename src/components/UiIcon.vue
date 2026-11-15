<script setup lang="ts">
import type { Component } from 'vue'

const props = withDefaults(defineProps<{ icon: Component; size?: 'sm' | 'md' | 'lg' | number }>(), { size: 'md' })
const px = typeof props.size === 'number' ? props.size : { sm: 14, md: 16, lg: 20 }[props.size]
</script>

<template>
  <component :is="icon" :size="px" :stroke-width="1.75" aria-hidden="true" class="ui-icon" />
</template>

<style scoped>
.ui-icon {
  flex: none;
}
</style>
