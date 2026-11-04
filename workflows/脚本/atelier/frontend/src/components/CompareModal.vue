<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { viewUrl } from '../api/client'
import EmptyState from './EmptyState.vue'
import type { HistoryItem } from '../api/types'
import { useEscapeLayer } from '../composables/useEscapeLayer'
import { useImageLocation } from '../composables/useImageLocation'

/**
 * 多图对比。
 *
 * 旧版（static/gallery.js 的 enterCompareMode + static/imageViewer.js 的
 * compare-modal）：选中 2~4 张图后打开对比弹层。
 *
 * **布局是网格，不是叠加**（旧版 CSS：compare-grid-2/3/4，3 张时首图跨两列），
 * 而「同步 / 分屏」按钮控制的是**缩放是否联动**（`_compareZoomSync`）——
 * 第一版我把它当成了布局模式，做成三张图完全叠在一起，结果根本没法看。
 *
 * 缩放同样不能用 transform：那样放大后会被裁掉，看不到新细节。
 * 这里按「自然尺寸 × 比例」设置真实宽高，每格自己滚动。
 */
const props = defineProps<{
  open: boolean
  items: HistoryItem[]
}>()

const emit = defineEmits<{ (e: 'close'): void }>()
const { revealImage } = useImageLocation()

useEscapeLayer(() => props.open, () => emit('close'))

/** 缩放是否在所有图之间联动。 */
const linkZoom = ref(true)

interface CellView {
  zoom: number
  natural: { w: number; h: number }
  /** 该格"适应"的显示比例（格子尺寸 ÷ 自然尺寸）。 */
  fit: number
  offset: { x: number; y: number }
}

const views = ref<CellView[]>([])
const cellEls = ref<HTMLElement[]>([])

/** 网格类名 —— 与旧版 compare-grid-N 一致。 */
const gridClass = computed(() => `compare-grid-${Math.max(1, props.items.length)}`)

function viewAt(index: number): CellView {
  if (!views.value[index]) {
    views.value[index] = { zoom: 1, natural: { w: 0, h: 0 }, fit: 1, offset: { x: 0, y: 0 } }
  }
  return views.value[index]
}

function imgStyle(index: number) {
  const v = viewAt(index)
  const scale = v.fit * v.zoom
  return {
    width: `${Math.round(v.natural.w * scale)}px`,
    height: `${Math.round(v.natural.h * scale)}px`,
    transform: `translate(${v.offset.x}px, ${v.offset.y}px)`,
    // 把 zoom 也写进 style：测试环境里图片不会真的 load（natural 尺寸为 0），
    // 没有这个变量就区分不出「这张缩放了、那张没有」。
    '--zoom': v.zoom,
  }
}

function onImageLoad(event: Event, index: number) {
  const img = event.target as HTMLImageElement
  const v = viewAt(index)
  v.natural = { w: img.naturalWidth, h: img.naturalHeight }
  v.fit = computeFit(index)
}

function computeFit(index: number): number {
  const el = cellEls.value[index]
  const v = viewAt(index)
  if (!el || !v.natural.w) return 1
  const w = el.clientWidth - 16
  const h = el.clientHeight - 16
  if (w <= 0 || h <= 0) return 1
  return Math.min(w / v.natural.w, h / v.natural.h)
}

function onWheel(event: WheelEvent, index: number) {
  const delta = event.deltaY > 0 ? -0.15 : 0.15
  const targets = linkZoom.value
    ? props.items.map((_, i) => i)
    : [index]
  for (const i of targets) {
    const v = viewAt(i)
    v.zoom = Math.min(8, Math.max(0.1, v.zoom * (1 + delta)))
  }
}

// ---------------------------------------------------------------------------
// 拖拽平移
// ---------------------------------------------------------------------------

const dragging = ref(false)
const dragOrigin = ref({ x: 0, y: 0 })

function onPointerDown(event: PointerEvent, index: number) {
  dragging.value = true
  const v = viewAt(index)
  dragOrigin.value = { x: event.clientX - v.offset.x, y: event.clientY - v.offset.y }
  ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return
  const targets = linkZoom.value
    ? props.items.map((_, i) => i)
    : [props.items.length - 1]
  for (const i of targets) {
    const v = viewAt(i)
    v.offset = {
      x: event.clientX - dragOrigin.value.x,
      y: event.clientY - dragOrigin.value.y,
    }
  }
}

function onPointerUp() {
  dragging.value = false
}

function resetView() {
  for (let i = 0; i < props.items.length; i++) {
    const v = viewAt(i)
    v.zoom = 1
    v.offset = { x: 0, y: 0 }
    v.fit = computeFit(i)
  }
}

function onKey(event: KeyboardEvent) {
  if (!props.open) return
  if (event.key === '0') resetView()
}

// 窗口尺寸变了要重算"适应"比例
let observer: ResizeObserver | null = null

onMounted(() => {
  window.addEventListener('keydown', onKey)
  observer = new ResizeObserver(() => {
    for (let i = 0; i < props.items.length; i++) {
      const v = viewAt(i)
      if (v.zoom === 1) v.fit = computeFit(i)
    }
  })
  cellEls.value.forEach((el) => el && observer?.observe(el))
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  observer?.disconnect()
})
</script>

<template>
  <div v-if="open" class="compare" @click.self="emit('close')">
    <header class="bar">
      <span class="title">图片对比（{{ items.length }} 张）</span>
      <button
        class="tool"
        :class="{ active: linkZoom }"
        title="开启后，缩放与拖动会同时作用于所有图片"
        @click="linkZoom = !linkZoom"
      >
        {{ linkZoom ? '🔗 缩放联动' : '🔗 独立缩放' }}
      </button>
      <span class="spacer" />
      <span class="hint">滚轮缩放 · 拖动平移 · 0 重置 · Esc 退出</span>
      <button class="tool" title="重置 (0)" @click="resetView">重置</button>
      <button class="tool close" title="关闭 (Esc)" @click="emit('close')">✕</button>
    </header>

    <div
      class="body"
      :class="gridClass"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointerleave="onPointerUp"
    >
      <figure
        v-for="(item, index) in items"
        :key="item.id"
        :ref="(el) => { if (el) cellEls[index] = el as HTMLElement }"
        class="cell"
        @wheel.prevent="onWheel($event, index)"
        @pointerdown="onPointerDown($event, index)"
      >
        <div class="cell-scroll">
          <img
            :src="viewUrl(item)"
            :alt="item.filename"
            :style="imgStyle(index)"
            :draggable="false"
            @load="onImageLoad($event, index)"
          />
        </div>
        <figcaption :title="item.filename">
          <span class="name">{{ item.filename }}</span>
          <button class="locate" type="button" title="在资源管理器中定位" @click.stop="revealImage(item)">
            定位
          </button>
        </figcaption>
      </figure>

      <EmptyState
        v-if="items.length < 2"
        class="empty"
        text="至少选择 2 张图片才能对比"
        hint="回到画廊按住 Ctrl 多选 2–4 张，再点「对比」。"
        action-text="关闭"
        @action="emit('close')"
      />
    </div>
  </div>
</template>

<style scoped>
.btn {
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.compare {
  position: fixed;
  inset: 0;
  z-index: var(--z-compare);
  display: flex;
  flex-direction: column;
  background: rgba(0, 0, 0, 0.92);
}

.bar {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  background: rgba(20, 24, 30, 0.95);
  border-bottom: 1px solid var(--border);
}

.title {
  font-size: var(--fs-sm);
  color: var(--text);
}

.spacer {
  flex: 1;
}

.hint {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.tool {
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  border-radius: var(--radius-sm);
  padding: 3px 9px;
  font-size: var(--fs-sm);
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.tool:hover {
  background: var(--panel-3);
  border-color: var(--border-strong);
}

.tool.active {
  border-color: var(--primary);
  color: var(--primary);
}

.close:hover {
  color: var(--danger);
}

/* 网格排布 —— 与旧版 compare-grid-N 一致：3 张时首图跨两列 */
.body {
  flex: 1;
  min-height: 0;
  display: grid;
  gap: 2px;
  padding: 2px;
  overflow: hidden;
}

.compare-grid-1 {
  grid-template-columns: 1fr;
  grid-template-rows: 1fr;
}

.compare-grid-2 {
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr;
}

.compare-grid-3 {
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr;
}

.compare-grid-3 .cell:first-child {
  grid-column: 1 / -1;
}

.compare-grid-4 {
  grid-template-columns: 1fr 1fr;
  grid-template-rows: 1fr 1fr;
}

.cell {
  margin: 0;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.02);
}

.cell-scroll {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  overflow: auto;
  padding: 6px;
  cursor: grab;
}

.cell-scroll:active {
  cursor: grabbing;
}

.cell img {
  flex: none;
  max-width: none;
  user-select: none;
}

.cell figcaption {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
  color: var(--muted);
  padding: 3px 6px;
  overflow: hidden;
  background: rgba(20, 24, 30, 0.85);
}

.cell figcaption .name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell figcaption .locate {
  flex: none;
  padding: 0 5px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-xs);
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.cell figcaption .locate:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.empty {
  grid-column: 1 / -1;
  place-self: center;
}
</style>
