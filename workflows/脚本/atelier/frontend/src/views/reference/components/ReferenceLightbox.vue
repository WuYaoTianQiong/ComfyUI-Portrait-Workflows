<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import Skeleton from '../../../components/Skeleton.vue'
import { useToast } from '../../../composables/useToast'
import { useViewerTransform } from '../../../composables/useViewerTransform'

/**
 * 参考图库统一灯箱（阶段 2.1 共享底座）。
 *
 * 为什么不直接用 `components/Lightbox.vue`：
 * 那个组件是**画廊出图记录**的查看器（props 是 `HistoryItem[]`，内部绑定
 * `viewUrl` / 收藏 / 删除 / 投喂工作流等出图侧写操作），API 与参考图库条目
 * 完全不兼容；按任务约束「不 fork 复制 1906 行」，这里只复用它的缩放引擎
 * `composables/useViewerTransform`（滚轮锚点缩放、拖拽平移、适应窗口），
 * 灯箱外壳按参考图库需要重写。
 *
 * 视觉对齐 §5：遮罩 rgba(0,0,0,0.1) + blur(4px)；弹窗宽 896px、`max-height: 90dvh`
 * （1080 视口测量 658.39px）、圆角 14px、底 #171717；图片视口 564 × 550.39px、
 * 圆角 10px、底 rgba(38,38,38,0.6)；关闭按钮 32 × 32 / 圆角 8 / 距右 / 上 16px；
 * 左右翻页按钮 44 × 44 圆形。
 *
 * 键盘：←/→ 组内角度翻页、↑/↓ 跨组翻页、+/− 缩放、0 复位、Esc 关闭。
 */
export interface ReferenceLightboxThumb {
  /** 角度 / 视角的唯一键（如 `正面`） */
  key: string
  /** 缩略条上的小字 */
  label: string
  /** 缩略图地址；null 表示无图，渲染占位 */
  url: string | null
}

export interface ReferenceLightboxMetaRow {
  label: string
  value: string
}

const props = withDefaults(
  defineProps<{
    open: boolean
    /** 标题（姿势名 / 服装名 / 人像标题） */
    title: string
    /** 大图地址；null 时渲染占位，绝不输出空 src */
    imageUrl: string | null
    alt?: string
    /** 左上角信息徽标（编号） */
    badge?: string
    /** 角度徽标 */
    angle?: string
    /** 顶部计数文案，如「12 / 60」 */
    counter?: string
    /** 信息表（体系 / 分类 / 模式 / 尺寸等） */
    metaRows?: ReferenceLightboxMetaRow[]
    /** 多角度缩略条；空数组时不渲染 */
    thumbnails?: ReferenceLightboxThumb[]
    /** 当前角度键 */
    activeThumbKey?: string | null
    /** 缩略条标题 */
    thumbTitle?: string
    /** 深度图开关：null = 不渲染该分段（服装 / 人像） */
    depthMode?: boolean | null
    /** 是否已在配方中 */
    selected?: boolean
    selectLabel?: string
    selectedLabel?: string
    /** 下载文件名；空串时用 idText */
    downloadName?: string
    /** 可复制的 ID；空串时不渲染 ID 行 */
    copyValue?: string
    /** 复制成功提示 */
    copyToast?: string
    canPrev?: boolean
    canNext?: boolean
    canPrevGroup?: boolean
    canNextGroup?: boolean
  }>(),
  {
    alt: '',
    badge: '',
    angle: '',
    counter: '',
    metaRows: () => [],
    thumbnails: () => [],
    activeThumbKey: null,
    thumbTitle: '切换视角（← / →）',
    depthMode: null,
    selected: false,
    selectLabel: '加入角色配方',
    selectedLabel: '已在角色配方中（点击移除）',
    downloadName: '',
    copyValue: '',
    copyToast: '已复制 ID',
    canPrev: false,
    canNext: false,
    canPrevGroup: false,
    canNextGroup: false,
  },
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'prev'): void
  (e: 'next'): void
  (e: 'prev-group'): void
  (e: 'next-group'): void
  (e: 'select-thumb', key: string): void
  (e: 'toggle-select'): void
  (e: 'update:depthMode', value: boolean): void
}>()

const toast = useToast()

const {
  stageEl,
  imgEl,
  imgLoaded,
  natural,
  fitMode,
  zoomPercent,
  panning,
  onWheel,
  onPanStart,
  zoomBy,
  animateTo,
  syncStageSize,
  setNaturalSize,
  constrainView,
  applyView,
  reset: resetViewer,
} = useViewerTransform()

/**
 * 以「铺满视口」为 100% 的适应比例。
 *
 * `useViewerTransform` 的 `computeFit()` 会预留 48px 内边距（画廊灯箱需要留白），
 * 参考图库灯箱的视口本身就是完整显示区，按 §5 图片应铺到 412.79 × 550.39
 * （3:4，正好撑满 564 × 550.39 视口）。因此这里用自己的适应比例：
 * `min(视口宽/原图宽, 视口高/原图高)`，百分比也以此为 100%。
 */
const fitScale = ref(1)

function fitImage() {
  const el = stageEl.value
  const { w, h } = natural.value
  if (!el || !w || !h) return
  fitScale.value = Math.min(el.clientWidth / w, el.clientHeight / h)
  fitMode.value = true
  animateTo(fitScale.value, el.clientWidth / 2, el.clientHeight / 2)
}

/** 展示百分比：100% = 适应视口（与 React ZoomViewport 口径一致）。 */
const displayZoom = computed(() => {
  const base = fitScale.value * 100
  if (!base) return 100
  return Math.round((zoomPercent.value / base) * 100)
})

/** 大图加载失败：给重试，而不是裂图。 */
const imageError = ref(false)
/** 递增后通过 key 重建 img，强制重新拉取。 */
const reloadNonce = ref(0)

function onImageLoad(event: Event) {
  imageError.value = false
  setNaturalSize(event.target as HTMLImageElement)
  fitImage()
}

function onImageError() {
  imageError.value = true
  imgLoaded.value = false
}

function retryImage() {
  imageError.value = false
  reloadNonce.value += 1
}

/** stage 尺寸变化：适应模式重新贴合，手动缩放保持当前比例并重新约束边界。 */
let observer: ResizeObserver | null = null

function observeStage() {
  observer?.disconnect()
  const el = stageEl.value
  if (!el) return
  observer = new ResizeObserver(() => {
    syncStageSize()
    if (fitMode.value) fitImage()
    else {
      constrainView()
      applyView()
    }
  })
  observer.observe(el)
}

function initFromCache() {
  const img = imgEl.value
  if (img && img.complete && img.naturalWidth) {
    imageError.value = false
    setNaturalSize(img)
    fitImage()
  }
}

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      observer?.disconnect()
      observer = null
      resetViewer()
      return
    }
    imageError.value = false
    await nextTick()
    syncStageSize()
    observeStage()
    initFromCache()
  },
  { immediate: true },
)

watch(
  () => props.imageUrl,
  async () => {
    imageError.value = false
    resetViewer()
    await nextTick()
    syncStageSize()
    initFromCache()
  },
)

// ---------------------------------------------------------------------------
// 键盘
// ---------------------------------------------------------------------------

function onKey(event: KeyboardEvent) {
  if (!props.open || event.defaultPrevented) return
  switch (event.key) {
    case 'Escape':
      emit('close')
      return
    case 'ArrowLeft':
      event.preventDefault()
      emit('prev')
      return
    case 'ArrowRight':
      event.preventDefault()
      emit('next')
      return
    case 'ArrowUp':
      event.preventDefault()
      emit('prev-group')
      return
    case 'ArrowDown':
      event.preventDefault()
      emit('next-group')
      return
    case '+':
    case '=':
      event.preventDefault()
      zoomBy(1.25)
      return
    case '-':
      event.preventDefault()
      zoomBy(1 / 1.25)
      return
    case '0':
      event.preventDefault()
      fitImage()
      return
    default:
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  observer?.disconnect()
  observer = null
})

// ---------------------------------------------------------------------------
// 展示派生
// ---------------------------------------------------------------------------

const imageAlt = computed(() => props.alt || props.title)
const showDepthSwitch = computed(() => props.depthMode !== null)
const downloadFileName = computed(() => props.downloadName || props.copyValue || 'reference')
const hasThumbs = computed(() => props.thumbnails.length > 0)
const showLoading = computed(() => Boolean(props.imageUrl) && !imgLoaded.value && !imageError.value)

async function copyId() {
  if (!props.copyValue) return
  try {
    await navigator.clipboard.writeText(props.copyValue)
    toast.success(props.copyToast)
  } catch {
    toast.error('复制失败（浏览器拒绝了剪贴板访问）')
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="ref-lightbox" data-testid="reference-lightbox" @click.self="emit('close')">
      <div
        class="ref-lightbox__panel"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
      >
        <button
          type="button"
          class="ref-lightbox__close"
          title="关闭（Esc）"
          aria-label="关闭"
          data-testid="lightbox-close"
          @click="emit('close')"
        >
          ✕
        </button>

        <div class="ref-lightbox__stage-area">
          <div class="ref-lightbox__controls" aria-label="图片缩放控制">
            <button
              type="button"
              class="ref-lightbox__ctrl"
              aria-label="缩小图片"
              :disabled="displayZoom <= 100"
              @click="zoomBy(1 / 1.25)"
            >
              −
            </button>
            <span class="ref-lightbox__zoom" aria-live="polite">{{ displayZoom }}%</span>
            <button type="button" class="ref-lightbox__ctrl" aria-label="放大图片" @click="zoomBy(1.25)">
              +
            </button>
            <button type="button" class="ref-lightbox__ctrl is-wide" @click="fitImage">适应窗口</button>
          </div>

          <figure
            ref="stageEl"
            class="ref-lightbox__stage"
            :class="{ dragging: panning }"
            @wheel.prevent="onWheel"
            @mousedown="onPanStart"
          >
            <div v-if="!imageUrl" class="ref-lightbox__placeholder">该条目没有可用的原图</div>
            <div v-else-if="showLoading" class="ref-lightbox__loading">
              <Skeleton variant="block" width="min(320px, 52%)" height="80%" radius="10px" />
              <span>加载中…</span>
            </div>
            <div v-else-if="imageError" class="ref-lightbox__placeholder is-error">
              <span>图片加载失败，请检查文件是否存在</span>
              <button type="button" class="ref-lightbox__retry" @click.stop="retryImage">重试</button>
            </div>
            <img
              v-if="imageUrl && !imageError"
              ref="imgEl"
              :key="`${imageUrl}-${reloadNonce}`"
              :src="imageUrl"
              :alt="imageAlt"
              :class="{ loaded: imgLoaded }"
              :draggable="false"
              @load="onImageLoad"
              @error="onImageError"
            />
          </figure>

          <p class="ref-lightbox__hint">滚轮或双指缩放 · 放大后拖动 · 100% 为适应窗口 · ← / → 切换视角 · ↑ / ↓ 切换姿势</p>

          <button
            v-if="canPrev"
            type="button"
            class="ref-lightbox__nav prev"
            title="上一个视角（←）"
            aria-label="上一个视角"
            @click="emit('prev')"
          >
            ‹
          </button>
          <button
            v-if="canNext"
            type="button"
            class="ref-lightbox__nav next"
            title="下一个视角（→）"
            aria-label="下一个视角"
            @click="emit('next')"
          >
            ›
          </button>
        </div>

        <aside class="ref-lightbox__aside">
          <header class="ref-lightbox__head">
            <div class="ref-lightbox__badges">
              <span v-if="counter" class="ref-lightbox__counter">{{ counter }}</span>
              <span v-if="badge" class="ref-lightbox__badge">{{ badge }}</span>
              <span v-if="angle" class="ref-lightbox__badge is-outline">{{ angle }}</span>
            </div>

            <div v-if="showDepthSwitch" class="ref-lightbox__segment" data-testid="lightbox-depth-toggle">
              <button
                type="button"
                class="ref-lightbox__segment-btn"
                :class="{ 'is-active': depthMode === false }"
                @click="emit('update:depthMode', false)"
              >
                白模
              </button>
              <button
                type="button"
                class="ref-lightbox__segment-btn"
                :class="{ 'is-active': depthMode === true }"
                @click="emit('update:depthMode', true)"
              >
                深度图
              </button>
            </div>
          </header>

          <h2 class="ref-lightbox__title">{{ title }}</h2>

          <div v-if="copyValue" class="ref-lightbox__id">
            <span class="ref-lightbox__id-text" :title="copyValue">{{ copyValue }}</span>
            <button type="button" class="ref-lightbox__copy" title="复制 ID" @click="copyId">复制</button>
          </div>

          <section v-if="hasThumbs" class="ref-lightbox__thumbs">
            <h3 class="ref-lightbox__section-title">{{ thumbTitle }}</h3>
            <div class="ref-lightbox__thumb-grid">
              <button
                v-for="thumb in thumbnails"
                :key="thumb.key"
                type="button"
                class="ref-lightbox__thumb"
                :class="{ 'is-active': thumb.key === activeThumbKey }"
                :title="thumb.label"
                @click="emit('select-thumb', thumb.key)"
              >
                <span class="ref-lightbox__thumb-img">
                  <img v-if="thumb.url" :src="thumb.url" :alt="thumb.label" loading="lazy" />
                  <span v-else class="ref-lightbox__thumb-empty">无</span>
                </span>
                <span class="ref-lightbox__thumb-label">{{ thumb.label }}</span>
              </button>
            </div>
          </section>

          <dl v-if="metaRows.length" class="ref-lightbox__facts">
            <template v-for="row in metaRows" :key="row.label">
              <dt>{{ row.label }}</dt>
              <dd>{{ row.value }}</dd>
            </template>
          </dl>

          <div class="ref-lightbox__actions">
            <button
              type="button"
              class="ref-lightbox__select"
              :class="{ 'is-selected': selected }"
              data-testid="lightbox-toggle-select"
              @click="emit('toggle-select')"
            >
              {{ selected ? selectedLabel : selectLabel }}
            </button>
            <div class="ref-lightbox__action-grid">
              <a
                v-if="imageUrl"
                class="ref-lightbox__action"
                :href="imageUrl"
                :download="downloadFileName"
              >
                下载
              </a>
              <a
                v-if="imageUrl"
                class="ref-lightbox__action"
                :href="imageUrl"
                target="_blank"
                rel="noopener noreferrer"
              >
                新窗口原图
              </a>
            </div>
          </div>
        </aside>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* 遮罩：§5 rgba(0,0,0,0.1) + blur(4px) */
.ref-lightbox {
  position: fixed;
  inset: 0;
  z-index: var(--z-lightbox);
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(4px);
}

/*
 * 弹窗：896 × 658.39（1080 视口实测）、max-height 90dvh、圆角 14px、底 #171717。
 * 高度同时受 658.39px 与 90dvh 约束，窄屏（矮视口）自动收缩。
 */
.ref-lightbox__panel {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  width: 896px;
  max-width: 95vw;
  height: min(658.39px, 90dvh);
  max-height: 90dvh;
  overflow: hidden;
  border-radius: 14px;
  background: #171717;
  box-shadow: var(--shadow-3);
}

/* 关闭按钮：32 × 32 / 圆角 8 / 距右 / 上 16px */
.ref-lightbox__close {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 3;
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08);
  color: #fafafa;
  font-size: 14px;
  line-height: 1;
}

.ref-lightbox__close:hover {
  background: rgba(255, 255, 255, 0.16);
}

/* 左侧：缩放控制 + 图片视口 + 提示；下边距 16 ���，stage 吸收剩余高度 */
.ref-lightbox__stage-area {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  min-height: 0;
  padding: 16px;
}

.ref-lightbox__controls {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex: none;
  height: 44px;
}

.ref-lightbox__ctrl {
  box-sizing: border-box;
  min-width: 44px;
  height: 32px;
  padding: 0 8px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 8px;
  background: transparent;
  color: #fafafa;
  font-size: 14px;
  line-height: 1;
}

.ref-lightbox__ctrl.is-wide {
  font-size: 12px;
}

.ref-lightbox__ctrl:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.32);
  background: rgba(255, 255, 255, 0.06);
}

.ref-lightbox__ctrl:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ref-lightbox__zoom {
  min-width: 48px;
  color: #a1a1a1;
  font-size: 12px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

/* 图片视口：564 × 550.39、圆角 10px、底 rgba(38,38,38,.6)；flex 吸收剩余高度 */
.ref-lightbox__stage {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  max-height: 626px;
  margin: 0;
  overflow: hidden;
  border-radius: 10px;
  background: rgba(38, 38, 38, 0.6);
  cursor: grab;
  touch-action: none;
}

.ref-lightbox__stage.dragging {
  cursor: grabbing;
}

.ref-lightbox__stage img {
  position: absolute;
  top: 0;
  left: 0;
  max-width: none;
  max-height: none;
  border-radius: 6px;
  opacity: 0;
  user-select: none;
  -webkit-user-drag: none;
}

.ref-lightbox__stage img.loaded {
  opacity: 1;
}

.ref-lightbox__placeholder,
.ref-lightbox__loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #a1a1a1;
  font-size: 12px;
  text-align: center;
  pointer-events: none;
}

.ref-lightbox__placeholder.is-error {
  color: #fca5a5;
  pointer-events: auto;
}

.ref-lightbox__retry {
  padding: 4px 12px;
  border: 1px solid currentColor;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font-size: 12px;
}

.ref-lightbox__hint {
  flex: none;
  margin: 0;
  color: #a1a1a1;
  font-size: 11px;
  line-height: 16px;
  text-align: center;
}

/* 左右翻页：44 × 44 圆形 */
.ref-lightbox__nav {
  position: absolute;
  top: 50%;
  z-index: 2;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 50%;
  background: #262626;
  color: #fafafa;
  font-size: 22px;
  line-height: 1;
  transform: translateY(-50%);
  box-shadow: var(--shadow-2);
}

.ref-lightbox__nav:hover {
  background: #333333;
}

.ref-lightbox__nav.prev {
  left: 24px;
}

.ref-lightbox__nav.next {
  right: 24px;
}

/* 右侧信息栏：300px、内边距 20px、顶部分隔线 */
.ref-lightbox__aside {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
  padding: 20px;
  padding-top: 56px;
  border-left: 1px solid rgba(255, 255, 255, 0.08);
  overflow-y: auto;
}

.ref-lightbox__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.ref-lightbox__badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.ref-lightbox__counter {
  color: #a1a1a1;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.ref-lightbox__badge {
  display: inline-flex;
  align-items: center;
  min-height: 19px;
  padding: 2px 6px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.1);
  color: #fafafa;
  font-size: 10px;
  font-weight: 600;
  line-height: 15px;
  white-space: nowrap;
}

.ref-lightbox__badge.is-outline {
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: transparent;
  color: #d4d4d4;
}

/* 白模 / 深度图分段 */
.ref-lightbox__segment {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
  padding: 2px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 8px;
  background: #262626;
}

.ref-lightbox__segment-btn {
  padding: 2px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #a1a1a1;
  font-size: 11px;
  font-weight: 500;
  line-height: 18px;
}

.ref-lightbox__segment-btn.is-active {
  background: #0a0a0a;
  color: #fafafa;
  box-shadow: var(--shadow-1);
}

.ref-lightbox__title {
  margin: 0;
  color: #fafafa;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
}

/* ID 行：等宽、可复制 */
.ref-lightbox__id {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  background: #262626;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.ref-lightbox__id-text {
  min-width: 0;
  overflow: hidden;
  color: #e5e5e5;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-lightbox__copy {
  flex: none;
  padding: 0;
  border: 0;
  background: transparent;
  color: #00d492;
  font-family: inherit;
  font-size: 12px;
}

.ref-lightbox__copy:hover {
  text-decoration: underline;
}

.ref-lightbox__section-title {
  margin: 0 0 6px;
  color: #a1a1a1;
  font-size: 12px;
  font-weight: 500;
}

/* 灯箱内 5 角度缩略条：5 列 + 4px 间距 */
.ref-lightbox__thumb-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
}

.ref-lightbox__thumb {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px;
  overflow: hidden;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: #a1a1a1;
}

.ref-lightbox__thumb.is-active {
  border-color: #e5e5e5;
  background: #0a0a0a;
  color: #fafafa;
}

.ref-lightbox__thumb:hover {
  border-color: rgba(255, 255, 255, 0.3);
}

.ref-lightbox__thumb-img {
  display: block;
  width: 100%;
  aspect-ratio: 1 / 1;
  overflow: hidden;
  border-radius: 8px;
  background: #262626;
}

.ref-lightbox__thumb-img img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.ref-lightbox__thumb-empty {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  font-size: 9px;
  color: #737373;
}

.ref-lightbox__thumb-label {
  font-size: 10px;
  line-height: 1.2;
  text-align: center;
}

/* 信息表：68px 标签列 + 内容 */
.ref-lightbox__facts {
  display: grid;
  grid-template-columns: 68px minmax(0, 1fr);
  gap: 6px 8px;
  margin: 0;
  font-size: 12px;
}

.ref-lightbox__facts dt {
  color: #a1a1a1;
}

.ref-lightbox__facts dd {
  margin: 0;
  color: #fafafa;
  font-weight: 500;
  word-break: break-all;
}

/* 底部操作：主按钮 + 下载 / 新窗口 */
.ref-lightbox__actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: auto;
}

.ref-lightbox__select {
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  border: 0;
  border-radius: 8px;
  background: #e5e5e5;
  color: #171717;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.ref-lightbox__select.is-selected {
  background: #262626;
  color: #fafafa;
}

.ref-lightbox__action-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.ref-lightbox__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 32px;
  padding: 0 8px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 8px;
  background: transparent;
  color: #fafafa;
  font-size: 12px;
  text-decoration: none;
}

.ref-lightbox__action:hover {
  background: rgba(255, 255, 255, 0.06);
}

/* 窄屏：改为上下堆叠，弹窗内部滚动 */
@media (max-width: 900px) {
  .ref-lightbox__panel {
    display: flex;
    flex-direction: column;
    width: min(96vw, 640px);
    height: min(88dvh, 780px);
    overflow-y: auto;
  }

  .ref-lightbox__stage-area {
    flex: none;
  }

  .ref-lightbox__stage {
    height: 46dvh;
    flex: none;
  }

  .ref-lightbox__aside {
    padding: 16px;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    border-left: 0;
    overflow: visible;
  }

  .ref-lightbox__nav {
    display: none;
  }
}
</style>