<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  referenceImageUrl,
  type ReferenceImageKind,
  type ReferenceItem,
} from '../api/reference'
import { useEscapeLayer } from '../composables/useEscapeLayer'
import { useToast } from '../composables/useToast'
import { useViewerTransform } from '../composables/useViewerTransform'

/**
 * 参考图库的只读灯箱（M1）。
 *
 * 为什么不复用 `Lightbox.vue`：那个组件的 `items` 是 `HistoryItem[]`，
 * 绑了收藏 / 删除 / 重出图 / 投喂工作流，数据源与写操作都不适用于参考库。
 * 这里只保留「看」需要的能力：大图、缩放/平移、复制 ID 与关键词、下载原图，
 * 外加参考库特有的「白模 / 深度」切换与同姿势多角度切换。
 *
 * `items` 由父组件传入：姿势库是同一 `(体系, 姿势编号)` 下的全部角度，
 * 其它库只有当前这一条；所以左右键在这里就是「换角度」。
 */
const props = defineProps<{
  items: ReferenceItem[]
  index: number
}>()

const emit = defineEmits<{
  close: []
  'update:index': [value: number]
}>()

const toast = useToast()

const item = computed<ReferenceItem | undefined>(() => props.items[props.index])
const hasPrev = computed(() => props.index > 0)
const hasNext = computed(() => props.index < props.items.length - 1)

function go(delta: number) {
  const next = props.index + delta
  if (next < 0 || next >= props.items.length) return
  emit('update:index', next)
}

// ---------------------------------------------------------------------------
// 白模 / 深度
// ---------------------------------------------------------------------------

const mode = ref<Exclude<ReferenceImageKind, 'thumb'>>('image')
const canDepth = computed(() => !!item.value?.depth_url)

watch(canDepth, (ok) => {
  if (!ok) mode.value = 'image'
})

const imageSrc = computed(() => (item.value ? referenceImageUrl(item.value, mode.value) : ''))

function setMode(next: 'image' | 'depth') {
  if (next === 'depth' && !canDepth.value) return
  mode.value = next
}

// ---------------------------------------------------------------------------
// 缩放 / 平移（复用查看器的 transform 模型）
// ---------------------------------------------------------------------------

const {
  stageEl,
  imgEl,
  imgLoaded,
  zoomPercent,
  panning,
  fitMode,
  syncStageSize,
  setNaturalSize,
  initView,
  constrainView,
  applyView,
  onWheel,
  onPanStart,
  onStageClick,
  toggleFit,
  zoomBy,
  resetView,
  reset: resetViewer,
} = useViewerTransform({
  onStageClick: () => emit('close'),
})

const imgFailed = ref(false)
const reloadToken = ref(0)

function initFromImage(img: HTMLImageElement) {
  if (!img.naturalWidth) return
  fitMode.value = true
  setNaturalSize(img)
  initView()
}

function onImageLoad(event: Event) {
  imgFailed.value = false
  initFromImage(event.target as HTMLImageElement)
}

function retryImage() {
  imgFailed.value = false
  reloadToken.value += 1
}

watch([() => props.index, mode], async () => {
  imgFailed.value = false
  resetViewer()
  await nextTick()
  const img = imgEl.value
  // 缓存里的图不会再触发 load，需要主动初始化一次
  if (img?.complete && img.naturalWidth) initFromImage(img)
})

// ---------------------------------------------------------------------------
// 尺寸变化
// ---------------------------------------------------------------------------

let observer: ResizeObserver | null = null

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  if (stageEl.value) {
    observer = new ResizeObserver(() => {
      syncStageSize()
      if (fitMode.value) initView()
      else {
        constrainView()
        applyView()
      }
    })
    observer.observe(stageEl.value)
  }
  const img = imgEl.value
  if (img?.complete && img.naturalWidth) initFromImage(img)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  observer?.disconnect()
})

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    go(-1)
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    go(1)
  } else if (event.key === '+' || event.key === '=') {
    event.preventDefault()
    zoomBy(1.2)
  } else if (event.key === '-') {
    event.preventDefault()
    zoomBy(1 / 1.2)
  } else if (event.key === '0') {
    event.preventDefault()
    resetView()
  }
}

useEscapeLayer(() => true, () => emit('close'))

// ---------------------------------------------------------------------------
// 复制与下载
// ---------------------------------------------------------------------------

async function copyText(text: string, label: string) {
  if (!text) {
    toast.info(`没有可复制的${label}`)
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    toast.success(`已复制${label}`)
  } catch {
    toast.error('剪贴板不可用，请手动选择复制')
  }
}

const downloadName = computed(() => {
  const it = item.value
  if (!it) return 'reference'
  return `${it.library}-${it.id}`
})

const modeLabel = computed(() => {
  if (mode.value === 'depth') return '深度'
  return item.value?.library === 'pose' ? '白模' : '原图'
})

const positionLabel = computed(() => {
  if (props.items.length <= 1) return ''
  const angle = item.value?.angle
  return angle ? `角度 ${props.index + 1}/${props.items.length} · ${angle}` : `第 ${props.index + 1}/${props.items.length} 张`
})
</script>

<template>
  <Teleport to="body">
    <div v-if="item" class="ref-lightbox">
      <header class="lb-head">
        <div class="lb-title">
          <span class="name">{{ item.name || item.id }}</span>
          <span v-if="item.subtitle" class="sub">{{ item.subtitle }}</span>
          <span v-if="positionLabel" class="pos">{{ positionLabel }}</span>
        </div>

        <div class="lb-tools">
          <button
            v-if="item.library === 'pose'"
            class="tool"
            :class="{ active: mode === 'image' }"
            title="白模图"
            @click="setMode('image')"
          >
            白模
          </button>
          <button
            v-if="item.library === 'pose'"
            class="tool"
            :class="{ active: mode === 'depth' }"
            :disabled="!canDepth"
            title="深度图"
            @click="setMode('depth')"
          >
            深度
          </button>
          <span v-if="item.library === 'pose'" class="sep" />

          <button class="tool" :class="{ active: fitMode }" title="适应窗口" @click="toggleFit">
            适应
          </button>
          <button class="tool" title="缩小（-）" @click="zoomBy(1 / 1.2)">−</button>
          <span class="zoom">{{ zoomPercent }}%</span>
          <button class="tool" title="放大（+）" @click="zoomBy(1.2)">+</button>
          <button class="tool" title="重置视图（0）" @click="resetView">重置</button>

          <span class="sep" />
          <button class="tool" title="复制参考 ID" @click="copyText(item.id, '参考 ID')">
            复制 ID
          </button>
          <button
            v-if="item.keywords"
            class="tool"
            title="复制英文关键词"
            @click="copyText(item.keywords, '英文关键词')"
          >
            复制关键词
          </button>
          <a
            v-if="!item.remote"
            class="tool link"
            :href="item.image_url ?? undefined"
            :download="downloadName"
            title="下载原图"
          >
            下载
          </a>
          <a
            v-else
            class="tool link"
            :href="item.image_url ?? undefined"
            target="_blank"
            rel="noopener noreferrer"
            title="在新窗口打开外链原图"
          >
            打开原图
          </a>

          <button class="tool close" title="关闭（Esc）" @click="emit('close')">✕</button>
        </div>
      </header>

      <button class="nav prev" :disabled="!hasPrev" title="上一角度（←）" @click="go(-1)">
        ‹
      </button>

      <figure
        ref="stageEl"
        class="stage"
        :class="{ dragging: panning }"
        @wheel.prevent="onWheel"
        @mousedown="onPanStart"
        @click="onStageClick"
      >
        <img
          v-if="!imgFailed"
          :key="`${item.id}:${mode}:${reloadToken}`"
          ref="imgEl"
          :src="imageSrc"
          :alt="item.name || item.id"
          :class="{ loaded: imgLoaded }"
          :draggable="false"
          @load="onImageLoad"
          @error="imgFailed = true"
        />
        <div v-else class="stage-fallback">
          <p class="fallback-title">
            {{ item.remote ? '外链图片加载失败' : '图片加载失败' }}
          </p>
          <p class="fallback-hint">
            {{
              item.remote
                ? '外链素材可能被墙或已失效；可到来源站查看，或继续浏览其它条目。'
                : '上游文件可能已被删除或移动。'
            }}
          </p>
          <div class="fallback-actions">
            <button class="btn btn-sm" @click.stop="retryImage">重试</button>
            <a
              v-if="item.remote"
              class="btn btn-sm"
              :href="item.image_url ?? undefined"
              target="_blank"
              rel="noopener noreferrer"
              @click.stop
            >
              打开原链接
            </a>
          </div>
        </div>
      </figure>

      <button class="nav next" :disabled="!hasNext" title="下一角度（→）" @click="go(1)">
        ›
      </button>

      <aside class="info" @click.stop>
        <div class="info-row">
          <span class="info-label">类型</span>
          <span class="info-value">{{ modeLabel }}</span>
        </div>
        <div v-if="item.group" class="info-row">
          <span class="info-label">体系 / 分类</span>
          <span class="info-value">{{ item.group }}</span>
        </div>
        <div v-if="item.facet" class="info-row">
          <span class="info-label">细分</span>
          <span class="info-value">{{ item.facet }}</span>
        </div>
        <div v-if="item.angle" class="info-row">
          <span class="info-label">角度</span>
          <span class="info-value">{{ item.angle }}</span>
        </div>
        <div v-if="item.tags.length" class="info-row">
          <span class="info-label">标签</span>
          <span class="info-value tags">
            <span v-for="tag in item.tags" :key="tag" class="tag">{{ tag }}</span>
          </span>
        </div>
        <div v-if="item.keywords" class="info-row">
          <span class="info-label">关键词</span>
          <span class="info-value keywords">{{ item.keywords }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">ID</span>
          <span class="info-value id" :title="item.id" @click="copyText(item.id, '参考 ID')">
            {{ item.id }}
          </span>
        </div>
        <p v-if="item.remote" class="remote-note">
          外链素材，仅供浏览。本地出图读不到远程图，不能作为参考输入。
        </p>
      </aside>

      <div v-if="props.items.length > 1" class="filmstrip">
        <button
          v-for="(angleItem, i) in props.items"
          :key="angleItem.id"
          class="film"
          :class="{ active: i === props.index }"
          :title="angleItem.angle || angleItem.id"
          @click="emit('update:index', i)"
        >
          <img :src="angleItem.thumb_url ?? undefined" :alt="angleItem.angle || angleItem.id" loading="lazy" />
          <span>{{ angleItem.angle || i + 1 }}</span>
        </button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.ref-lightbox {
  position: fixed;
  inset: 0;
  z-index: var(--z-lightbox);
  display: flex;
  flex-direction: column;
  background: #0a0c10;
  color: var(--text);
}

.lb-head {
  display: flex;
  align-items: center;
  gap: var(--gap);
  min-height: 44px;
  padding: 0 var(--gap);
  border-bottom: 1px solid var(--border);
  background: var(--panel);
  z-index: 3;
}

.lb-title {
  display: flex;
  align-items: baseline;
  gap: var(--gap-sm);
  min-width: 0;
  flex: 1;
}

.lb-title .name {
  font-size: var(--fs-lg);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.lb-title .sub,
.lb-title .pos {
  font-size: var(--fs-xs);
  color: var(--text);
  opacity: 0.72;
  white-space: nowrap;
}

.lb-tools {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.tool {
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  border-radius: var(--radius-sm);
  padding: 3px 8px;
  font-size: var(--fs-sm);
}

.tool:hover:not(:disabled) {
  border-color: var(--border-strong);
  background: var(--panel-3);
}

.tool:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tool.active {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}

.tool.link {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}

.tool.close {
  margin-left: 4px;
}

.sep {
  width: 1px;
  height: 18px;
  background: var(--border);
  margin: 0 4px;
}

.zoom {
  min-width: 48px;
  text-align: center;
  font-size: var(--fs-xs);
  color: var(--text);
}

.stage {
  margin: 0;
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  cursor: grab;
  touch-action: none;
}

.stage.dragging {
  cursor: grabbing;
}

.stage img {
  position: absolute;
  left: 0;
  top: 0;
  max-width: none;
  max-height: none;
  transform-origin: center center;
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow);
  user-select: none;
  -webkit-user-drag: none;
  opacity: 0;
}

.stage img.loaded {
  opacity: 1;
}

.stage-fallback {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: var(--gap-lg);
  text-align: center;
}

.fallback-title {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 600;
}

.fallback-hint {
  margin: 0;
  max-width: 460px;
  font-size: var(--fs-sm);
  color: var(--text);
  opacity: 0.72;
}

.fallback-actions {
  display: flex;
  gap: var(--gap-sm);
  margin-top: var(--gap-sm);
}

.nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 44px;
  height: 68px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: rgba(22, 27, 34, 0.82);
  color: var(--text);
  font-size: 26px;
  line-height: 1;
  z-index: 2;
}

.nav:hover:not(:disabled) {
  background: var(--panel-3);
}

.nav:disabled {
  opacity: 0.25;
  cursor: not-allowed;
}

.nav.prev {
  left: var(--gap-sm);
}

.nav.next {
  right: var(--gap-sm);
}

.info {
  position: absolute;
  right: var(--gap);
  bottom: 86px;
  z-index: 2;
  width: min(340px, 40vw);
  max-height: 52vh;
  overflow: auto;
  padding: var(--gap);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  background: rgba(22, 27, 34, 0.94);
  box-shadow: var(--shadow);
  font-size: var(--fs-sm);
}

.info-row {
  display: flex;
  gap: var(--gap-sm);
  padding: 3px 0;
  line-height: 1.5;
}

.info-label {
  flex: none;
  width: 76px;
  color: var(--text);
  opacity: 0.66;
}

.info-value {
  min-width: 0;
  color: var(--text);
  word-break: break-all;
}

.info-value.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.tag {
  padding: 0 6px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: var(--fs-xs);
}

.info-value.keywords {
  font-size: var(--fs-xs);
  opacity: 0.85;
}

.info-value.id {
  cursor: copy;
  color: var(--primary);
}

.remote-note {
  margin: var(--gap-sm) 0 0;
  padding-top: var(--gap-sm);
  border-top: 1px solid var(--border);
  color: var(--warn);
  font-size: var(--fs-xs);
  line-height: 1.6;
}

.filmstrip {
  display: flex;
  align-items: stretch;
  gap: 6px;
  height: 74px;
  padding: 6px var(--gap);
  border-top: 1px solid var(--border);
  background: var(--panel);
  overflow-x: auto;
  z-index: 3;
}

.film {
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
}

.film img {
  width: 52px;
  height: 52px;
  object-fit: cover;
  border-radius: 4px;
}

.film span {
  font-size: var(--fs-xs);
  color: var(--text);
  opacity: 0.72;
  line-height: 1;
}

.film.active {
  border-color: var(--primary);
  background: var(--primary-soft);
}

@media (max-width: 860px) {
  .info {
    display: none;
  }

  .lb-title .sub,
  .lb-title .pos {
    display: none;
  }
}
</style>