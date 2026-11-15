<script setup lang="ts">
import { Diamond, Check } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { useApp } from '@/app/context'
import UiSegmented from '@/components/UiSegmented.vue'
import EmptyState from '@/components/EmptyState.vue'
import { CUT_KIND_LABEL } from '@/domain/clipHints'
import { formatTime, frameToUs } from '@/domain/time'
import type { Cut } from '@/domain/types'

const { session, view, playhead } = useApp()
const scope = ref<'pending' | 'all'>('pending')
const cuts = computed(() => session.timeline.value?.cuts ?? [])
const pending = session.pendingCuts
// a cut counts once even though it touches two clips
const list = computed<Cut[]>(() => (scope.value === 'pending' ? pending.value : cuts.value))

function pick(c: Cut) {
  view.state.reviewCutId = c.cut_id
  playhead.requestSeek(c.frame)
}
</script>

<template>
  <section class="rlist" aria-label="切点检查列表">
    <header class="rlist__head">
      <h2 class="rlist__title">切点检查</h2>
      <p class="small secondary num">待检查 {{ pending.length }} 处 · 共 {{ cuts.length }} 个切点</p>
      <UiSegmented
        v-model="scope"
        aria-label="列表范围"
        size="sm"
        :options="[
          { value: 'pending', label: '待检查', count: pending.length },
          { value: 'all', label: '全部切点', count: cuts.length },
        ]"
      />
    </header>
    <ul v-if="list.length" class="rlist__items" role="listbox" aria-label="切点">
      <li
        v-for="c in list"
        :key="c.cut_id"
        role="option"
        :aria-selected="view.state.reviewCutId === c.cut_id"
        class="ritem"
        :class="{ 'is-current': view.state.reviewCutId === c.cut_id }"
        tabindex="0"
        @click="pick(c)"
        @keydown.enter.space.prevent="pick(c)"
      >
        <Diamond v-if="c.review === 'pending'" :size="11" :stroke-width="2.5" class="ritem__flag" aria-hidden="true" />
        <Check v-else :size="12" :stroke-width="2.5" class="ritem__ok" aria-hidden="true" />
        <div class="ritem__text">
          <span class="ritem__line">
            <span class="mono">#{{ c.frame }}</span> · {{ CUT_KIND_LABEL[c.kind] }}
            <span v-if="c.skipped && c.review === 'pending'" class="ritem__skip small">已跳过</span>
          </span>
          <span class="small muted num">{{ formatTime(frameToUs(c.frame, session.stream.value!)) }}<template v-if="c.confidence !== null"> · 置信 {{ c.confidence.toFixed(2) }}</template><template v-else-if="c.review === 'pending'"> · 建议检查</template></span>
        </div>
      </li>
    </ul>
    <EmptyState v-else compact title="没有待检查的切点">所有切点都已确认。切换到「全部切点」可复查。</EmptyState>
  </section>
</template>

<style scoped>
.rlist {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  min-height: 0;
}
.rlist__head {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line-subtle);
}
.rlist__title {
  font-size: var(--fs-13);
  font-weight: var(--fw-semibold);
}
.rlist__items {
  flex: 1;
  overflow-y: auto;
}
.ritem {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line-subtle);
  cursor: default;
  position: relative;
}
.ritem:hover {
  background: var(--bg-raised);
}
.ritem.is-current {
  background: var(--accent-soft-strong);
}
.ritem.is-current::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 3px;
  background: var(--accent);
}
.ritem__flag {
  color: var(--review);
  flex: none;
}
.ritem__ok {
  color: var(--success);
  flex: none;
}
.ritem__text {
  display: grid;
  min-width: 0;
}
.ritem__line {
  font-size: var(--fs-13);
}
.ritem__skip {
  color: var(--text-3);
  margin-left: 6px;
}
</style>
