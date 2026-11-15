<script setup lang="ts">
import { ImageOff, RotateCcw } from 'lucide-vue-next'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useApp } from '@/app/context'
import { isAbort, toAppError } from '@/domain/errors'
import UiSpinner from './UiSpinner.vue'

/**
 * Displays one frame from the adapter's frame service.
 * - lazy: requests only when visible (IntersectionObserver, with a margin for neighbours)
 * - every new request supersedes the previous; late results of older requests are discarded
 * - URLs are released back to the adapter cache on change/unmount
 */
const props = withDefaults(
  defineProps<{ projectId: string; frame: number; size?: 'thumb' | 'full'; lazy?: boolean; alt?: string; fit?: 'cover' | 'contain'; showState?: boolean }>(),
  { size: 'thumb', lazy: true, fit: 'cover', showState: true },
)
const emit = defineEmits<{ state: ['loading' | 'ready' | 'error'] }>()
const { adapter } = useApp()
const root = ref<HTMLElement>()
const url = ref<string | null>(null)
const status = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const errMsg = ref('')
const exact = ref(true)
const loadedFrame = ref<number | null>(null)
let reqSeq = 0
let ctrl: AbortController | null = null
let visible = !props.lazy
let io: IntersectionObserver | null = null

function release() {
  if (url.value) adapter.preview.releaseFrame(url.value)
  url.value = null
}

async function load() {
  if (!visible) return
  const seq = ++reqSeq
  ctrl?.abort()
  const c = (ctrl = new AbortController())
  status.value = 'loading'
  emit('state', 'loading')
  try {
    const res = await adapter.preview.getFrame({ project_id: props.projectId, frame: props.frame, size: props.size }, c.signal)
    if (seq !== reqSeq) {
      adapter.preview.releaseFrame(res.url)
      return
    }
    release()
    url.value = res.url
    loadedFrame.value = res.frame
    exact.value = res.exact
    status.value = 'ready'
    emit('state', 'ready')
  } catch (e) {
    if (seq !== reqSeq || isAbort(e)) return
    errMsg.value = toAppError(e).message
    status.value = 'error'
    emit('state', 'error')
  }
}

watch(() => [props.projectId, props.frame, props.size], load)

onMounted(() => {
  if (!props.lazy) return load()
  io = new IntersectionObserver(
    (entries) => {
      const v = entries.some((e) => e.isIntersecting)
      if (v && !visible) {
        visible = true
        if (status.value === 'idle' || url.value === null) load()
      } else visible = v
    },
    { rootMargin: '200px' },
  )
  if (root.value) io.observe(root.value)
})
onBeforeUnmount(() => {
  reqSeq++
  ctrl?.abort()
  io?.disconnect()
  release()
})
defineExpose({ reload: load, status })
</script>

<template>
  <div ref="root" class="frame" :class="`frame--${fit}`">
    <img v-if="url" :src="url" :alt="alt ?? `第 ${frame} 帧`" :data-frame="loadedFrame" draggable="false" />
    <template v-if="showState">
      <div v-if="status === 'loading' && !url" class="frame__state" aria-hidden="true"><UiSpinner :size="size === 'thumb' ? 10 : 16" /></div>
      <div v-else-if="status === 'error'" class="frame__state frame__state--error">
        <ImageOff :size="size === 'thumb' ? 14 : 20" :stroke-width="1.5" aria-hidden="true" />
        <template v-if="size === 'full'">
          <span class="small">{{ errMsg }}</span>
          <button type="button" class="frame__retry" @click.stop="load"><RotateCcw :size="12" /> 重试当前帧</button>
        </template>
        <span v-else class="sr-only">缩略图读取失败</span>
      </div>
    </template>
    <slot :status="status" :exact="exact" />
  </div>
</template>

<style scoped>
.frame {
  position: relative;
  background: #000;
  overflow: hidden;
}
.frame img {
  width: 100%;
  height: 100%;
  max-width: none;
  user-select: none;
}
.frame--cover img {
  object-fit: cover;
}
.frame--contain img {
  object-fit: contain;
}
.frame__state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
  justify-content: center;
  color: var(--text-3);
  text-align: center;
  padding: 6px;
}
.frame__state--error {
  color: var(--text-3);
  background: repeating-linear-gradient(45deg, #0c0c0c, #0c0c0c 6px, #111 6px, #111 12px);
}
.frame__retry {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: var(--r-1);
  background: var(--bg-control);
  color: var(--text-1);
  font-size: var(--fs-12);
}
.frame__retry:hover {
  background: var(--bg-control-hover);
}
</style>
