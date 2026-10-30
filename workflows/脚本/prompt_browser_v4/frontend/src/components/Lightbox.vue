<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { apiDelete, apiPost, viewUrl } from '../api/client'
import { useToast } from '../composables/useToast'
import type { HistoryItem } from '../api/types'
import { formatSize, resolution, shotTime, sourceLabel } from '../utils/format'

/**
 * 图片查看器。
 *
 * 旧版（static/imageViewer.js，956 行）把这套东西和"多图对比"混在一个
 * PhotoSwipe 弹层里：单图模式能缩放/旋转/翻转/1:1，对比模式最多 4 张并排
 * 且缩放同步。重构时我只保留了"翻页 + 信息面板"，把其余能力漏掉了 ——
 * 端点覆盖核对查的是 API 调用，纯前端的功能（缩放、旋转、对比）根本不调
 * 后端接口，所以一个都没被查出来。
 *
 * 这里按旧版的能力清单补齐，并拆成两个组件：
 * - `Lightbox.vue`      单图查看（缩放/旋转/翻转/下载/收藏/删除/投喂工作流）
 * - `CompareModal.vue`  多图对比（最多 4 张，同步 / 分屏）
 */
const props = defineProps<{
  items: HistoryItem[]
  index: number
  /** 工作流列表由父组件传入 —— 组件本身不查，避免多套查询状态。 */
  workflows?: Array<{ path: string; name: string }>
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update:index', value: number): void
  /** 收藏 / 删除等写操作后通知父组件刷新列表。 */
  (e: 'changed'): void
  /** 用这张图的记录重新出图（旧版 🔄）。 */
  (e: 'regenerate', item: HistoryItem): void
  /** 跳到这条图片对应的提示词（旧版「跳到提示词」）。 */
  (e: 'jump-to-prompt', promptId: number): void
}>()

const toast = useToast()

const item = computed<HistoryItem | undefined>(() => props.items[props.index])

/**
 * 能不能重新出图：prompt_id 存在时走提示词出图；prompt_params.prompt 存在时
 * 用记录下来的文本重跑（同步进来的图没有提示词关联，但参数还在）。
 */
const canRegenerate = computed(
  () => !!(item.value?.prompt_id || (item.value?.prompt_params as Record<string, unknown> | null)?.prompt),
)
const hasPrev = computed(() => props.index > 0)
const hasNext = computed(() => props.index < props.items.length - 1)

function go(delta: number) {
  const next = props.index + delta
  if (next < 0 || next >= props.items.length) return
  emit('update:index', next)
}

// ---------------------------------------------------------------------------
// 缩放 / 旋转 / 翻转
//
// 关键：**不能用 transform: scale 做缩放**。
// transform 不改变布局尺寸，图片放大后会被 overflow:hidden 裁掉 ——
// 看起来只是"变大了"，但看不到任何新细节，等于假缩放。
// 正确做法是按「自然尺寸 × 比例」设置真实宽高，让容器产生滚动条。
// ---------------------------------------------------------------------------

/** 图片的自然像素尺寸（1:1 时的基准）。 */
const natural = ref({ w: 0, h: 0 })
const stageEl = ref<HTMLElement | null>(null)
const stageSize = ref({ w: 0, h: 0 })

/** 1 = 适应窗口；1:1 模式下为原始像素倍率。 */
const zoom = ref(1)
/** true = 适应窗口，false = 原始尺寸（1:1） */
const fitMode = ref(true)
const rotate = ref(0)
const flipped = ref(false)
const showInfo = ref(true)

watch(
  () => props.index,
  () => {
    zoom.value = 1
    fitMode.value = true
    rotate.value = 0
    flipped.value = false
    natural.value = { w: 0, h: 0 }
  },
)

/** "适应窗口"时的显示比例。 */
const fitScale = computed(() => {
  if (!natural.value.w || !stageSize.value.w) return 1
  const availW = Math.max(80, stageSize.value.w - 48)
  const availH = Math.max(80, stageSize.value.h - 80)
  return Math.min(availW / natural.value.w, availH / natural.value.h)
})

/**
 * 实际显示比例：
 * - 适应模式：fitScale × zoom（zoom=1 刚好铺满）
 * - 1:1 模式：zoom 就是像素倍率（zoom=1 → 原始像素）
 */
const displayScale = computed(() =>
  fitMode.value ? fitScale.value * zoom.value : zoom.value,
)

/** 真实宽高（不是 transform），放大后容器才滚得动。 */
const imageStyle = computed(() => {
  const scale = displayScale.value
  return {
    width: `${Math.round(natural.value.w * scale)}px`,
    height: `${Math.round(natural.value.h * scale)}px`,
    transform: `rotate(${rotate.value}deg) scaleX(${flipped.value ? -1 : 1})`,
  }
})

function onImageLoad(event: Event) {
  const img = event.target as HTMLImageElement
  natural.value = { w: img.naturalWidth, h: img.naturalHeight }
}

function setZoom(value: number) {
  zoom.value = Math.min(8, Math.max(0.1, value))
}

function zoomBy(delta: number) {
  setZoom(zoom.value * (1 + delta))
}

function toggleFit() {
  fitMode.value = !fitMode.value
  // 从"适应"切到"1:1"时把倍率接上 fitScale，避免画面突然缩到很小
  if (!fitMode.value) zoom.value = 1 / (fitScale.value || 1)
  else zoom.value = 1
}

function resetView() {
  zoom.value = 1
  fitMode.value = true
  rotate.value = 0
  flipped.value = false
}

function rotate90() {
  rotate.value = (rotate.value + 90) % 360
}

function flip() {
  flipped.value = !flipped.value
}

function onWheel(event: WheelEvent) {
  zoomBy(event.deltaY > 0 ? -0.15 : 0.15)
}

/** 容器尺寸变了（窗口缩放 / 信息栏收起）要重算适应比例。 */
let observer: ResizeObserver | null = null

onMounted(() => {
  window.addEventListener('keydown', onKey)
  if (stageEl.value) {
    stageSize.value = { w: stageEl.value.clientWidth, h: stageEl.value.clientHeight }
    observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (rect) stageSize.value = { w: rect.width, h: rect.height }
    })
    observer.observe(stageEl.value)
  }
})

// ---------------------------------------------------------------------------
// 写操作：收藏 / 删除 / 下载 / 投喂工作流
// ---------------------------------------------------------------------------

const busy = ref(false)

async function toggleFavorite() {
  if (!item.value) return
  busy.value = true
  try {
    await apiPost(`/api/history/${item.value.id}/favorite`)
    toast.success(item.value.favorite ? '已取消收藏' : '已收藏')
    emit('changed')
  } catch (e) {
    toast.error(`操作失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    busy.value = false
  }
}

async function removeItem() {
  if (!item.value) return
  if (!confirm(`确定删除「${item.value.filename}」这条出图记录吗？\n（只删记录，不动磁盘文件）`)) return
  busy.value = true
  try {
    await apiDelete(`/api/history/${item.value.id}`)
    toast.success('已删除该记录')
    emit('changed')
    emit('close')
  } catch (e) {
    toast.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    busy.value = false
  }
}

function download() {
  if (!item.value) return
  window.open(viewUrl(item.value), '_blank')
}

const processWf = ref('')
const processOpen = ref(false)

async function feedToWorkflow() {
  if (!item.value) return
  if (!processWf.value) {
    toast.error('请先选择工作流')
    return
  }
  busy.value = true
  try {
    await apiPost(`/api/history/${item.value.id}/process`, { workflow_path: processWf.value })
    toast.success('已提交处理任务，可在「任务」页看进度')
    processOpen.value = false
  } catch (e) {
    toast.error(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    busy.value = false
  }
}

// ---------------------------------------------------------------------------
// 键盘
// ---------------------------------------------------------------------------

/**
 * 键盘：← → 翻页，Esc 关闭，+/- 缩放，0 重置，f 翻转，r 旋转。
 */
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
  else if (event.key === 'ArrowLeft') go(-1)
  else if (event.key === 'ArrowRight') go(1)
  else if (event.key === '+' || event.key === '=') zoomBy(0.2)
  else if (event.key === '-') zoomBy(-0.2)
  else if (event.key === '0') resetView()
  else if (event.key === 'f') flip()
  else if (event.key === 'r') rotate90()
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div v-if="item" class="lightbox" @click.self="emit('close')">
    <header class="bar">
      <span class="pos">{{ index + 1 }} / {{ items.length }}</span>
      <span class="spacer" />

      <div v-if="processOpen" class="wf-picker">
        <select v-model="processWf" class="wf-select">
          <option value="">选择工作流…</option>
          <option v-for="wf in workflows ?? []" :key="wf.path" :value="wf.path">{{ wf.name }}</option>
        </select>
        <button class="tool primary" :disabled="busy" @click="feedToWorkflow">投喂</button>
        <button class="tool" @click="processOpen = false">取消</button>
      </div>

      <button
        class="tool"
        :title="processOpen ? '收起工作流选择' : '投喂给工作流处理（超分/重绘等）'"
        @click="processOpen = !processOpen"
      >
        ⚡
      </button>
      <button class="tool" title="下载原图" @click="download">⬇</button>
      <button
        v-if="canRegenerate"
        class="tool"
        title="用这张图的记录重新出图"
        @click="emit('regenerate', item)"
      >
        🔄
      </button>
      <button
        v-if="item.prompt_id"
        class="tool"
        title="跳到这条提示词"
        @click="emit('jump-to-prompt', item.prompt_id!)"
      >
        ↗
      </button>
      <button class="tool" :title="item.favorite ? '取消收藏' : '收藏'" @click="toggleFavorite">
        {{ item.favorite ? '★' : '☆' }}
      </button>
      <button class="tool" title="水平翻转 (F)" @click="flip">⇋</button>
      <button class="tool" title="旋转 90° (R)" @click="rotate90">⟳</button>
      <button class="tool" :class="{ active: !fitMode }" title="适应 / 原始尺寸" @click="toggleFit">
        1:1
      </button>
      <button class="tool" title="缩小 (-)" @click="zoomBy(-0.2)">−</button>
      <span class="zoom">{{ Math.round(displayScale * 100) }}%</span>
      <button class="tool" title="放大 (+)" @click="zoomBy(0.2)">+</button>
      <button class="tool" title="重置视图 (0)" @click="resetView">重置</button>
      <button class="tool" :class="{ active: showInfo }" title="显示/隐藏信息" @click="showInfo = !showInfo">
        ⓘ
      </button>
      <button class="tool danger" title="删除记录" @click="removeItem">🗑</button>
      <button class="tool close" title="关闭 (Esc)" @click="emit('close')">✕</button>
    </header>

    <button class="nav prev" :disabled="!hasPrev" title="上一张 (←)" @click="go(-1)">‹</button>

    <figure ref="stageEl" class="stage" @wheel.prevent="onWheel">
      <img
        :src="viewUrl(item)"
        :alt="item.filename"
        :style="imageStyle"
        @load="onImageLoad"
        :draggable="false"
      />
    </figure>

    <button class="nav next" :disabled="!hasNext" title="下一张 (→)" @click="go(1)">›</button>

    <aside v-if="showInfo" class="info">
      <header class="info-head">
        <span class="pos">{{ index + 1 }} / {{ items.length }}</span>
        <button class="close" title="关闭 (Esc)" @click="emit('close')">✕</button>
      </header>

      <div class="filename" :title="item.filename">{{ item.filename }}</div>

      <dl class="facts">
        <div v-if="resolution(item)"><dt>分辨率</dt><dd>{{ resolution(item) }}</dd></div>
        <div v-if="item.file_size"><dt>体积</dt><dd>{{ formatSize(item.file_size) }}</dd></div>
        <div><dt>来源</dt><dd>{{ sourceLabel(item.source) }}</dd></div>
        <div><dt>出图时间</dt><dd>{{ shotTime(item) }}</dd></div>
        <div v-if="item.prompt_name"><dt>提示词</dt><dd>{{ item.prompt_name }}</dd></div>
      </dl>

      <div v-if="item.tags.length" class="tags">
        <span
          v-for="tag in item.tags"
          :key="tag.id"
          class="tag"
          :style="{ '--c': tag.color }"
        >
          {{ tag.name }}
        </span>
      </div>

      <p v-if="item.missing" class="missing-tip">
        🚫 磁盘上已找不到这个文件，记录与标签仍保留
      </p>

      <p class="hint">
        快捷键：← → 翻页 · 滚轮/+ − 缩放 · 0 重置 · F 翻转 · R 旋转 · Esc 关闭
      </p>
    </aside>
  </div>
</template>

<style scoped>
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  /* 必须 stretch：stage 高度若按内容（图片高度）算，而图片高度又依赖
     「适应窗口」的比例（依赖 stage 高度），就成了循环依赖 —— 比例会被压到 3%。 */
  align-items: stretch;
  justify-content: center;
  background: rgba(0, 0, 0, 0.88);
  backdrop-filter: blur(2px);
}

.bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: var(--gap-sm) var(--gap);
  background: rgba(20, 24, 30, 0.92);
  border-bottom: 1px solid var(--border);
}

.spacer {
  flex: 1;
}

.pos {
  font-size: var(--fs-sm);
  color: var(--muted);
  margin-right: var(--gap-sm);
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
  padding: 3px 8px;
  font-size: var(--fs-sm);
  line-height: 1.2;
}

.tool:hover:not(:disabled) {
  background: var(--panel-3);
  border-color: var(--border-strong);
}

.tool.active {
  border-color: var(--primary);
  color: var(--primary);
}

.tool.primary {
  background: var(--primary);
  color: #fff;
}

.tool.danger:hover:not(:disabled) {
  color: var(--danger);
  border-color: var(--danger);
}

.tool:disabled {
  opacity: 0.4;
  cursor: default;
}

.wf-picker {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-right: var(--gap-sm);
}

.wf-select {
  width: 220px;
}

.stage {
  margin: 0;
  /* 必须占满剩余空间：stage 是 flex item，宽度默认由内容（图片）撑开，
     图片还没加载时宽度就是 0，"适应窗口"的缩放比会算成 3%。 */
  flex: 1;
  min-width: 0;
  max-width: calc(100% - 360px);
  max-height: 100%;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: var(--gap-lg);
  padding-top: calc(var(--gap-lg) + 40px);
  /* 放大后要能滚动 —— 这正是不能用 transform 缩放的原因 */
  overflow: auto;
}

.stage img {
  /* 宽高由脚本按「自然尺寸 × 比例」算好，这里不能再限死 */
  flex: none;
  max-width: none;
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow);
  user-select: none;
}

.nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 44px;
  height: 68px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: rgba(22, 27, 34, 0.8);
  color: var(--text);
  font-size: 26px;
  line-height: 1;
}

.nav:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.nav:disabled {
  opacity: 0.25;
  cursor: default;
}

.prev {
  left: 16px;
}

.next {
  right: 336px;
}

.info {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 320px;
  padding: var(--gap-lg);
  padding-top: calc(var(--gap-lg) + 40px);
  overflow-y: auto;
  background: var(--panel);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.info-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.close {
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-lg);
}

.close:hover {
  color: var(--danger);
}

.filename {
  font-size: var(--fs-sm);
  word-break: break-all;
  color: var(--text);
}

.facts {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.facts div {
  display: flex;
  gap: var(--gap);
  font-size: var(--fs-sm);
}

.facts dt {
  flex: none;
  width: 62px;
  color: var(--muted);
}

.facts dd {
  margin: 0;
  word-break: break-all;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  font-size: var(--fs-xs);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--c);
  color: var(--c);
}

.missing-tip {
  margin: 0;
  font-size: var(--fs-sm);
  padding: var(--gap-sm);
  border-radius: var(--radius-sm);
  background: var(--danger-soft);
  color: #fecaca;
}

.hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--muted);
  line-height: 1.6;
}
</style>
