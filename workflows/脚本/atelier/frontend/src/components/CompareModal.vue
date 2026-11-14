<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { viewUrl } from '../api/client'
import EmptyState from './EmptyState.vue'
import Icon from './Icon.vue'
import type { HistoryItem } from '../api/types'
import { useEscapeLayer } from '../composables/useEscapeLayer'
import { useImageLocation } from '../composables/useImageLocation'
import { useViewerTransform } from '../composables/useViewerTransform'

/**
 * 多图对比。
 *
 * 旧版（static/gallery.js 的 enterCompareMode + static/imageViewer.js 的
 * compare-modal）：选中 2~4 张图后打开对比弹层。
 *
 * **布局是网格，不是叠加**（旧版 CSS：compare-grid-2/3/4，3 张时首图跨两列），
 * 但 3 张竖图/方图「品字」会让顶部两格大量留白，因此按图片长宽比自动改为三列并列，
 * 也可以在顶栏手动切换（compare-grid-3-row）。
 * 而「同步 / 分屏」按钮控制的是**缩放是否联动**（`_compareZoomSync`）——
 * 第一版我把它当成了布局模式，做成三张图完全叠在一起，结果根本没法看。
 *
 * 缩放/平移已统一到 `useViewerTransform`（与单图灯箱同一套模型）：
 * 滚轮以鼠标为锚点缩放、rAF 插值、拖拽平移、边界约束。
 * 之前那版用「真实宽高 + 原生滚动条」，放大后居中溢出不可滚动、锚点固定在顶部，
 * 正是这轮被替换掉的原因。
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

type Pane = ReturnType<typeof useViewerTransform>

/** 最多同时对比 4 张（画廊已限制选择上限），按需取前 N 个。 */
const MAX_PANES = 4

/**
 * 每格一个与灯箱同款的视图实例：鼠标锚点缩放、rAF 插值、拖拽平移、边界约束。
 * `fitPadding` 取 16（四周各 8px）——比灯箱的 48 更紧凑，对比时多留画面。
 */
const panes: Pane[] = Array.from({ length: MAX_PANES }, () =>
  useViewerTransform({ fitPadding: 16 }),
)

/** 窗口尺寸变化时重算适应比例；声明在 bindStage 之前，ref 回调里会用到。 */
let observer: ResizeObserver | null = null

function bindStage(index: number, el: unknown) {
  const pane = panes[index]
  if (!pane) return
  const prev = pane.stageEl.value
  if (prev && observer) observer.unobserve(prev)
  pane.stageEl.value = (el as HTMLElement | null) ?? null
  if (pane.stageEl.value && observer) observer.observe(pane.stageEl.value)
}

function bindImg(index: number, el: unknown) {
  const pane = panes[index]
  if (pane) pane.imgEl.value = (el as HTMLImageElement | null) ?? null
}

/** 三张图并列的平均长宽比上限：再宽就是横图，品字布局反而每张更大。 */
const ROW_MAX_ASPECT = 1.2

/** 手动指定的 3 图布局；null = 按图片比例自动判断。 */
const manualLayout = ref<'grid' | 'row' | null>(null)

/** 单张图的长宽比：优先用接口给的 width/height，缺失时等图片加载后取自然尺寸。 */
function aspectAt(index: number): number | null {
  const item = props.items[index]
  if (item?.width && item?.height) return item.width / item.height
  const natural = panes[index]?.natural.value
  if (natural?.w && natural.h) return natural.w / natural.h
  return null
}

const avgAspect = computed(() => {
  const known: number[] = []
  for (let i = 0; i < props.items.length; i++) {
    const ratio = aspectAt(i)
    if (ratio) known.push(ratio)
  }
  if (!known.length) return null
  return known.reduce((sum, x) => sum + x, 0) / known.length
})

/** 三张图是否改成三列并列（竖图/方图三列明显更大）。 */
const threeInRow = computed(() => {
  if (props.items.length !== 3) return false
  if (manualLayout.value) return manualLayout.value === 'row'
  // 尺寸未知时保守保留品字
  return avgAspect.value !== null && avgAspect.value < ROW_MAX_ASPECT
})

function toggleLayout() {
  manualLayout.value = threeInRow.value ? 'grid' : 'row'
}

// 重新打开或换一批图时回到自动判断，并清掉上一批图的视图
watch(
  () => [props.open, props.items.map((it) => it.id).join(',')],
  ([open]) => {
    if (!open) return
    manualLayout.value = null
    for (const pane of panes) pane.reset()
  },
)

/** 网格类名 —— 与旧版 compare-grid-N 一致；3 张竖图/方图改走三列。 */
const gridClass = computed(() => {
  const count = Math.max(1, props.items.length)
  if (count === 3 && threeInRow.value) return 'compare-grid-3-row'
  return `compare-grid-${count}`
})

function onImageLoad(event: Event, index: number) {
  const pane = panes[index]
  if (!pane) return
  pane.setNaturalSize(event.target as HTMLImageElement)
  pane.fitMode.value = true
  pane.initView()
}

/** 滚轮缩放：以鼠标为锚点；联动时各格按同一相对位置同步。 */
function onWheel(event: WheelEvent, index: number) {
  const pane = panes[index]
  const stage = pane?.stageEl.value
  if (!pane || !stage) return
  const factor = Math.exp(-event.deltaY * 0.002)
  if (!Number.isFinite(factor) || factor <= 0) return
  const rect = stage.getBoundingClientRect()
  if (!linkZoom.value) {
    pane.zoomTo(pane.view.scale * factor, event.clientX - rect.left, event.clientY - rect.top)
    return
  }
  const rx = stage.clientWidth ? (event.clientX - rect.left) / stage.clientWidth : 0.5
  const ry = stage.clientHeight ? (event.clientY - rect.top) / stage.clientHeight : 0.5
  for (let i = 0; i < props.items.length; i++) {
    const p = panes[i]
    const st = p.stageEl.value
    if (!st) continue
    p.zoomTo(p.view.scale * factor, rx * st.clientWidth, ry * st.clientHeight)
  }
}

// ---------------------------------------------------------------------------
// 拖拽平移
// ---------------------------------------------------------------------------

interface DragSeed {
  pane: Pane
  cx: number
  cy: number
}

const dragIndex = ref<number | null>(null)
const dragStart = { x: 0, y: 0 }
let dragSeeds: DragSeed[] = []

function onPointerDown(event: PointerEvent, index: number) {
  if (event.button !== 0) return
  dragIndex.value = index
  dragStart.x = event.clientX
  dragStart.y = event.clientY
  // 停掉所有格子的缩放动画，记录起始中心，拖拽期间直接改 view
  dragSeeds = panes.slice(0, props.items.length).map((pane) => {
    pane.cancelAnim()
    pane.view.targetScale = pane.view.scale
    return { pane, cx: pane.view.cx, cy: pane.view.cy }
  })
  event.preventDefault()
}

function onPointerMove(event: PointerEvent) {
  const index = dragIndex.value
  if (index === null) return
  const dx = event.clientX - dragStart.x
  const dy = event.clientY - dragStart.y
  const seeds = linkZoom.value ? dragSeeds : [dragSeeds[index]]
  for (const seed of seeds) {
    const v = seed.pane.view
    v.cx = v.targetCx = seed.cx + dx
    v.cy = v.targetCy = seed.cy + dy
    seed.pane.constrainView()
    seed.pane.applyView()
  }
}

function onPointerUp() {
  dragIndex.value = null
  dragSeeds = []
}

function resetView() {
  for (let i = 0; i < props.items.length; i++) {
    const pane = panes[i]
    pane.fitMode.value = true
    pane.initView()
  }
}

function onKey(event: KeyboardEvent) {
  if (!props.open) return
  if (event.key === '0') resetView()
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  observer = new ResizeObserver(() => {
    for (let i = 0; i < props.items.length; i++) {
      const pane = panes[i]
      pane.syncStageSize()
      if (pane.fitMode.value) pane.initView()
      else {
        pane.constrainView()
        pane.applyView()
      }
    }
  })
  for (const pane of panes) {
    if (pane.stageEl.value) observer.observe(pane.stageEl.value)
  }
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
        <Icon :name="linkZoom ? 'link-2' : 'unlink'" /> {{ linkZoom ? '缩放联动' : '独立缩放' }}
      </button>
      <button
        v-if="items.length === 3"
        class="tool"
        :title="threeInRow ? '当前为三列并列，点击切换成品字布局' : '当前为品字布局，点击切换成三列并列'"
        @click="toggleLayout"
      >
        {{ threeInRow ? '并列布局' : '品字布局' }}
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
        class="cell"
        @wheel.prevent="onWheel($event, index)"
        @pointerdown="onPointerDown($event, index)"
      >
        <div :ref="(el) => bindStage(index, el)" class="cell-scroll">
          <img
            :ref="(el) => bindImg(index, el)"
            :src="viewUrl(item)"
            :alt="item.filename"
            :class="{ loaded: panes[index]?.imgLoaded.value }"
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
  background: var(--compare-scrim);
}

.bar {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  background: var(--compare-bar-bg);
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

/* 3 张竖图/方图：三列并列，避免品字顶部两格左右大量留白 */
.compare-grid-3-row {
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: 1fr;
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
  background: var(--compare-cell-bg);
}

/* 视图舞台：transform 模型（与灯箱一致），不产生原生滚动条 */
.cell-scroll {
  flex: 1;
  min-height: 0;
  position: relative;
  overflow: hidden;
  cursor: grab;
  touch-action: none;
}

.cell-scroll:active {
  cursor: grabbing;
}

.cell img {
  position: absolute;
  left: 0;
  top: 0;
  max-width: none;
  transform-origin: center center;
  user-select: none;
  -webkit-user-drag: none;
  /* 自然尺寸与适应比例算好后再显示，避免先按原始尺寸闪一下 */
  opacity: 0;
}

.cell img.loaded {
  opacity: 1;
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
  background: var(--compare-caption-bg);
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
