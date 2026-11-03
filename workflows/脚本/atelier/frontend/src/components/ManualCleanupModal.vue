<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { apiPost } from '../api/client'
import Modal from './Modal.vue'
import { useToast } from '../composables/useToast'

const props = defineProps<{
  open: boolean
  imageId: number
  imageUrl: string
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'applied', payload: { filename?: string; removed?: number }): void
}>()

const toast = useToast()
const imgEl = ref<HTMLImageElement | null>(null)
const wrapEl = ref<HTMLElement | null>(null)
const busy = ref(false)
const error = ref('')
const drawing = ref(false)
const start = ref({ x: 0, y: 0 })
const displayBox = ref<{ x: number; y: number; w: number; h: number } | null>(null)
const naturalBox = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null)

const hasSelection = computed(() => !!naturalBox.value)
const marqueeStyle = computed(() => {
  const b = displayBox.value
  return b
    ? { left: `${b.x}px`, top: `${b.y}px`, width: `${b.w}px`, height: `${b.h}px` }
    : {}
})

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function imagePoint(event: PointerEvent) {
  const img = imgEl.value
  if (!img) return null
  const rect = img.getBoundingClientRect()
  return {
    x: clamp(event.clientX - rect.left, 0, rect.width),
    y: clamp(event.clientY - rect.top, 0, rect.height),
    rect,
  }
}

function onPointerDown(event: PointerEvent) {
  if (busy.value || !imgEl.value) return
  const point = imagePoint(event)
  if (!point) return
  event.preventDefault()
  drawing.value = true
  start.value = { x: point.x, y: point.y }
  displayBox.value = { x: point.x, y: point.y, w: 0, h: 0 }
  naturalBox.value = null
  wrapEl.value?.setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (!drawing.value) return
  const point = imagePoint(event)
  if (!point) return
  displayBox.value = {
    x: Math.min(start.value.x, point.x),
    y: Math.min(start.value.y, point.y),
    w: Math.abs(point.x - start.value.x),
    h: Math.abs(point.y - start.value.y),
  }
}

function onPointerUp(event: PointerEvent) {
  if (!drawing.value) return
  drawing.value = false
  wrapEl.value?.releasePointerCapture(event.pointerId)
  const box = displayBox.value
  const img = imgEl.value
  if (!box || !img || box.w < 4 || box.h < 4) {
    displayBox.value = null
    naturalBox.value = null
    return
  }
  const rect = img.getBoundingClientRect()
  const sx = img.naturalWidth / rect.width
  const sy = img.naturalHeight / rect.height
  naturalBox.value = {
    x1: Math.round(box.x * sx),
    y1: Math.round(box.y * sy),
    x2: Math.round((box.x + box.w) * sx),
    y2: Math.round((box.y + box.h) * sy),
  }
}

function clearSelection() {
  displayBox.value = null
  naturalBox.value = null
}

async function apply() {
  if (!naturalBox.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const res = await apiPost<{
      success: boolean
      removed: number
      filename?: string
      message?: string
    }>(`/api/images/${props.imageId}/cleanup`, {
      boxes: [naturalBox.value],
      padding: 6,
    })
    if (!res.success) {
      error.value = res.message || '未生成新图'
      return
    }
    toast.success(`已清理 ${res.removed} 个选区，生成 ${res.filename}`)
    emit('applied', { filename: res.filename, removed: res.removed })
    clearSelection()
    emit('close')
  } catch (e) {
    error.value = `清理失败：${e instanceof Error ? e.message : String(e)}`
  } finally {
    busy.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) {
      clearSelection()
      error.value = ''
      drawing.value = false
    }
  },
)
</script>

<template>
  <Modal
    :open="open"
    title="手动清理"
    width="min(980px, 94vw)"
    height="min(86vh, 820px)"
    raised
    @close="emit('close')"
  >
    <div class="manual-cleanup">
      <p class="hint">
        在图片上拖拽框选要擦除的印章或文字；生成新图，不覆盖原图。可重复操作多次。
      </p>
      <div
        ref="wrapEl"
        class="canvas-wrap"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      >
        <img ref="imgEl" :src="imageUrl" draggable="false" alt="" />
        <div v-if="displayBox" class="marquee" :style="marqueeStyle" />
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </div>
    <template #footer>
      <span class="spacer" />
      <button class="btn btn-sm" :disabled="busy" @click="clearSelection">清除选区</button>
      <button class="btn btn-sm primary" :disabled="busy || !hasSelection" @click="apply">
        {{ busy ? '清理中…' : '应用清理' }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.manual-cleanup {
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  overflow: auto;
}

.hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--muted);
  line-height: 1.6;
}

.canvas-wrap {
  position: relative;
  width: fit-content;
  max-width: 100%;
  margin: 0 auto;
  cursor: crosshair;
  user-select: none;
  touch-action: none;
}

.canvas-wrap img {
  display: block;
  max-width: 100%;
  max-height: 62vh;
  object-fit: contain;
  pointer-events: none;
}

.marquee {
  position: absolute;
  border: 2px solid var(--primary);
  background: color-mix(in srgb, var(--primary) 18%, transparent);
  pointer-events: none;
}

.error {
  margin: 0;
  color: var(--danger);
  font-size: var(--fs-xs);
}
</style>
