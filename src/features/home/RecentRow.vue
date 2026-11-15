<script setup lang="ts">
import { MoreHorizontal } from 'lucide-vue-next'
import { computed } from 'vue'
import FrameImage from '@/components/FrameImage.vue'
import StatusTag from '@/components/StatusTag.vue'
import UiMenu from '@/components/UiMenu.vue'
import type { MenuItem } from '@/components/menu'
import UiSpinner from '@/components/UiSpinner.vue'
import { formatClock } from '@/domain/time'
import type { RecentProject } from '@/domain/types'
import { PROJECT_STATUS } from './projectStatus'

const props = defineProps<{ project: RecentProject; opening: boolean; current: boolean }>()
const emit = defineEmits<{ open: []; rename: []; remove: [] }>()
const status = computed(() => PROJECT_STATUS[props.project.status])
const thumbFrame = computed(() => Number(props.project.thumb_key?.split(':')[1] ?? 0))
const items = computed<MenuItem[]>(() => [
  { id: 'open', label: '打开', hint: '载入项目并进入编辑页', run: () => emit('open') },
  { id: 'rename', label: '重命名…', hint: '只修改项目显示名称；源视频与已导出文件名不变', run: () => emit('rename') },
  { id: 'remove', label: '从最近记录移除', hint: '只移除此入口；项目文件、源视频和导出结果都会保留', danger: true, run: () => emit('remove') },
])
</script>

<template>
  <div class="rrow" :class="{ 'is-opening': opening, 'is-current': current }">
    <button type="button" class="rrow__main" :aria-label="`打开项目 ${project.name}，状态：${status.label}`" :aria-busy="opening || undefined" @click="emit('open')">
      <FrameImage class="rrow__thumb" :class="{ 'is-portrait': project.orientation === 'portrait' }" :project-id="project.project_id" :frame="thumbFrame" size="thumb" :alt="''" />
      <span class="rrow__text">
        <span class="rrow__name truncate">{{ project.name }}</span>
        <span class="rrow__meta small truncate">{{ project.source_name }}</span>
      </span>
      <span class="rrow__stats small num">
        <template v-if="project.clip_count !== null">{{ project.clip_count }} 个片段</template>
        <template v-if="project.pending_review"> · {{ project.pending_review }} 处待检查</template>
      </span>
      <span class="rrow__status">
        <span v-if="opening" class="rrow__opening small"><UiSpinner :size="11" /> 正在打开…</span>
        <StatusTag v-else :label="status.label" :tone="status.tone" :icon="status.icon" size="sm" />
      </span>
      <span class="rrow__time small num">{{ formatClock(project.updated_at) }}</span>
    </button>
    <UiMenu :items="items" :label="`${project.name} 的操作`">
      <template #trigger="{ toggle, open, id }">
        <button type="button" class="rrow__more" :aria-label="`${project.name} 的更多操作`" aria-haspopup="menu" :aria-expanded="open" :aria-controls="id" @click="toggle">
          <MoreHorizontal :size="16" :stroke-width="1.75" />
        </button>
      </template>
    </UiMenu>
  </div>
</template>

<style scoped>
.rrow {
  display: flex;
  align-items: center;
  gap: 4px;
  padding-right: 6px;
  border-radius: var(--r-3);
  transition: background-color var(--dur-press) var(--ease-standard);
}
.rrow:hover {
  background: var(--bg-raised);
}
.rrow.is-current {
  box-shadow: inset 2px 0 0 var(--accent);
}
.rrow__main {
  flex: 1;
  min-width: 0;
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr) 150px 108px 92px;
  align-items: center;
  gap: 14px;
  padding: 8px 8px;
  text-align: left;
  border-radius: var(--r-2);
}
.rrow__thumb {
  width: 88px;
  height: 50px;
  border-radius: 8px;
  transition: transform var(--dur-spring) var(--ease-spring);
}
.rrow:hover .rrow__thumb {
  transform: scale(1.04);
}
.rrow__thumb.is-portrait :deep(img) {
  object-fit: contain;
}
.rrow__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.rrow__name {
  font-weight: var(--fw-medium);
}
.rrow__meta,
.rrow__stats,
.rrow__time {
  color: var(--text-3);
}
.rrow__time {
  text-align: right;
}
.rrow__opening {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-1);
}
.rrow__more {
  width: 28px;
  height: 28px;
  border-radius: var(--r-2);
  color: var(--text-3);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.rrow__more:hover {
  background: var(--bg-control);
  color: var(--text-1);
}
@media (max-width: 1280px) {
  .rrow__main {
    grid-template-columns: 72px minmax(0, 1fr) 108px 80px;
  }
  .rrow__thumb {
    width: 72px;
    height: 41px;
  }
  .rrow__stats {
    display: none;
  }
}
</style>
