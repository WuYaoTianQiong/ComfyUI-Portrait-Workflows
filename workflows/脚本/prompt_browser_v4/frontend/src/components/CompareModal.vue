<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { viewUrl } from '../api/client'
import type { HistoryItem } from '../api/types'

/**
 * 多图对比。
 *
 * 旧版（static/gallery.js 的 enterCompareMode + static/imageViewer.js 的
 * compare-modal）在选中 2~4 张图后打开对比弹层：
 * - **同步**模式：所有图叠在一起，缩放/平移联动，用来逐像素比对细节
 * - **分屏**模式：每张图各占一格
 * 最多 4 张 —— 再多就没法看了。
 *
 * 重构时这段整体丢了：它不调任何后端接口，所以端点覆盖核对查不出来。
 */
const props = defineProps<{
  open: boolean
  items: HistoryItem[]
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

/** 同步 = 叠在一起联动缩放；分屏 = 各占一格。 */
const mode = ref<'sync' | 'split'>('sync')

/** 缩放比例（同步模式下所有图共用）。 */
const zoom = ref(1)
const offset = ref({ x: 0, y: 0 })
const dragging = ref(false)
const dragStart = ref({ x: 0, y: 0 })


function setZoom(value: number) {
  zoom.value = Math.min(8, Math.max(0.1, value))
}

function zoomBy(delta: number) {
  setZoom(zoom.value * (1 + delta))
}

function resetView() {
  zoom.value = 1
  offset.value = { x: 0, y: 0 }
}

function onWheel(event: WheelEvent) {
  zoomBy(event.deltaY > 0 ? -0.15 : 0.15)
}

function onPointerDown(event: PointerEvent) {
  dragging.value = true
  dragStart.value = { x: event.clientX - offset.value.x, y: event.clientY - offset.value.y }
  ;(event.target as HTMLElement).setPointerCapture?.(event.pointerId)
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return
  offset.value = {
    x: event.clientX - dragStart.value.x,
    y: event.clientY - dragStart.value.y,
  }
}

function onPointerUp() {
  dragging.value = false
}

function onKey(event: KeyboardEvent) {
  if (!props.open) return
  if (event.key === 'Escape') emit('close')
  else if (event.key === '+' || event.key === '=') zoomBy(0.2)
  else if (event.key === '-') zoomBy(-0.2)
  else if (event.key === '0') resetView()
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

/** 同步模式下所有图共用一个变换；分屏模式各自 fit，不做联动。 */
const sharedTransform = computed(() => ({
  transform: `translate(${offset.value.x}px, ${offset.value.y}px) scale(${zoom.value})`,
}))
</script>

<template>
  <div v-if="open" class="compare" @click.self="emit('close')">
    <header class="bar">
      <span class="title">图片对比（{{ items.length }} 张）</span>
      <div class="mode-switch">
        <button class="tool" :class="{ active: mode === 'sync' }" @click="mode = 'sync'">同步</button>
        <button class="tool" :class="{ active: mode === 'split' }" @click="mode = 'split'">分屏</button>
      </div>
      <span class="spacer" />
      <span class="zoom">{{ Math.round(zoom * 100) }}%</span>
      <button class="tool" title="缩小 (-)" @click="zoomBy(-0.2)">−</button>
      <button class="tool" title="放大 (+)" @click="zoomBy(0.2)">+</button>
      <button class="tool" title="重置 (0)" @click="resetView">重置</button>
      <button class="tool close" title="关闭 (Esc)" @click="emit('close')">✕</button>
    </header>

    <div
      class="body"
      :class="mode"
      @wheel.prevent="onWheel"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointerleave="onPointerUp"
    >
      <figure v-for="item in items" :key="item.id" class="cell">
        <img
          :src="viewUrl(item)"
          :alt="item.filename"
          :style="mode === 'sync' ? sharedTransform : undefined"
          :draggable="false"
        />
        <figcaption :title="item.filename">{{ item.filename }}</figcaption>
      </figure>

      <p v-if="items.length < 2" class="hint">至少选择 2 张图片才能对比</p>
    </div>
  </div>
</template>

<style scoped>
.compare {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: flex;
  flex-direction: column;
  background: rgba(0, 0, 0, 0.9);
}

.bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: var(--gap-sm) var(--gap);
  background: rgba(20, 24, 30, 0.95);
  border-bottom: 1px solid var(--border);
}

.title {
  font-size: var(--fs-sm);
  color: var(--text);
  margin-right: var(--gap-sm);
}

.mode-switch {
  display: flex;
  gap: 2px;
}

.spacer {
  flex: 1;
}

.zoom {
  font-size: var(--fs-xs);
  color: var(--muted);
  min-width: 42px;
  text-align: center;
}

.tool {
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  border-radius: var(--radius-sm);
  padding: 3px 9px;
  font-size: var(--fs-sm);
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

.body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: grid;
  gap: 2px;
  cursor: grab;
  position: relative;
}

.body:active {
  cursor: grabbing;
}

.body.sync {
  grid-template-columns: 1fr;
  place-items: center;
}

/* 同步模式：所有图绝对叠在一起，缩放平移联动 */
.body.sync .cell {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
}

.body.split {
  grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
  grid-auto-rows: minmax(0, 1fr);
}

.cell {
  margin: 0;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.body.sync .cell {
  pointer-events: none;
}

.cell img {
  flex: 1;
  min-height: 0;
  width: 100%;
  object-fit: contain;
  user-select: none;
}

.body.sync .cell img {
  object-fit: contain;
  max-width: 100%;
  max-height: 100%;
}

.cell figcaption {
  flex: none;
  font-size: 10px;
  color: var(--muted);
  padding: 2px 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: rgba(20, 24, 30, 0.8);
}

.hint {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: var(--fs-sm);
}
</style>
