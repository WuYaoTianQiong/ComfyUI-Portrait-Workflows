<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { apiDelete, apiPost, viewUrl } from '../api/client'
import { useToast } from '../composables/useToast'
import { useImageLocation } from '../composables/useImageLocation'
import type { HistoryItem } from '../api/types'
import { formatSize, resolution, shotTime, sourceLabel } from '../utils/format'
import { confirmDialogWithCheckbox } from '../utils/naive'
import { useSettings } from '../composables/useSettings'
import { useEscapeLayer } from '../composables/useEscapeLayer'
import { useViewerTransform } from '../composables/useViewerTransform'
import Modal from './Modal.vue'

/**
 * 图片查看器。
 *
 * 旧版（static/imageViewer.js，1101 行）把这套东西和"多图对比"混在一个
 * 自定义弹层里：单图模式能缩放/旋转/翻转/1:1，对比模式最多 4 张并排
 * 且缩放同步。新前端把它拆成两个组件：
 * - `Lightbox.vue`      单图查看（缩放/旋转/翻转/下载/收藏/删除/投喂工作流）
 * - `CompareModal.vue`  多图对比（最多 4 张，同步 / 分屏）
 *
 * 缩放采用旧版的「transform + 手动平移」模型，而不是当前这版曾经的
 * 「真实宽高 + 滚动条」：
 * · 滚轮以鼠标指针为锚点缩放，指针下的像素保持不动；
 * · 放大后按住拖拽平移，看任意区域；
 * · rAF 插值让缩放平滑，边界约束保证图片不会被拖丢。
 * 之前那版虽然"真实宽高"不会被裁切，但缩放中心固定在画面中心、只能拖
 * 滚动条，手感远不如旧版 —— 这正是这次重做的原因。
 *
 * 信息卡放在左下角浮层，不占用图片显示区域；点击空白（stage 内图片外的
 * 区域）关闭查看器，点击图片本身不关闭。
 */
const props = defineProps<{
  items: HistoryItem[]
  index: number
  /** 工作流列表由父组件传入 —— 组件本身不查，避免多套查询状态。 */
  workflows?: Array<{ path: string; name: string }>
  /** 重新出图的任务正在提交/生成，按钮应保持禁用并给出可见反馈。 */
  regenerating?: boolean
  /**
   * 只读：任务/结果中心里"图还没入库"时打开的情况。
   * 隐藏收藏 / 删除 / 重出图 / 投喂这些写操作，其余（缩放、下载、信息）照常。
   */
  readonly?: boolean
  /** 是否显示「在画廊中查看」（画廊自己用不到，任务侧才需要）。 */
  canOpenGallery?: boolean
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
  /** 到画廊里按文件名定位这张图（任务侧打开时才有意义）。 */
  (e: 'open-in-gallery', filename: string): void
}>()

const toast = useToast()
const { revealImage } = useImageLocation()

const item = computed<HistoryItem | undefined>(() => props.items[props.index])

useEscapeLayer(() => !!item.value, () => emit('close'))
const outputPath = computed(() => {
  const it = item.value
  if (!it) return ''
  const base = it.img_type && it.img_type !== 'output' ? it.img_type : 'output'
  return `${base}/${it.subfolder ? `${it.subfolder}/` : ''}${it.filename}`
})

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
// 缩放 / 平移 / 旋转 / 翻转（实现见 useViewerTransform）
// ---------------------------------------------------------------------------

const promptTextEl = ref<HTMLPreElement | null>(null)
const promptSideEl = ref<HTMLElement | null>(null)
const showInfo = ref(true)
const promptInfoOpen = ref(false)

const {
  stageEl,
  imgEl,
  stageSize,
  natural,
  imgLoaded,
  rotation,
  flipped,
  fitMode,
  zoomPercent,
  panning,
  view,
  clampScale,
  computeFit,
  constrainView,
  applyView,
  initView,
  syncStageSize,
  setNaturalSize,
  zoomBy,
  onWheel,
  toggleFit,
  resetView,
  rotate90,
  flip,
  onPanStart,
  onStageClick,
  onRootClick,
  reset: resetViewer,
} = useViewerTransform({
  onChange: () => saveViewerState(),
  onPanStart: () => {
    clearInfoTimer()
    infoFaded.value = true
  },
  onStageClick: () => emit('close'),
})

function initFromImage(img: HTMLImageElement) {
  setNaturalSize(img)
  // 刷新恢复：第一次拿到尺寸时套用快照；否则正常适应窗口
  if (pendingSnapshot && pendingSnapshot.id === item.value?.id) {
    const snap = pendingSnapshot
    pendingSnapshot = null
    applyViewerSnapshot(snap)
  } else {
    pendingSnapshot = null
    fitMode.value = true
    initView()
  }
  saveViewerState()
}

function onImageLoad(event: Event) {
  initFromImage(event.target as HTMLImageElement)
}

// ---------------------------------------------------------------------------
// 尺寸变化
// ---------------------------------------------------------------------------

let observer: ResizeObserver | null = null

onMounted(() => {
  window.addEventListener('keydown', onKey)
  syncStageSize()
  if (stageEl.value) {
    observer = new ResizeObserver(() => {
      syncStageSize()
      if (fitMode.value) initView()
      else {
        constrainView()
        applyView()
      }
      saveViewerState()
    })
    observer.observe(stageEl.value)
  }

  // 刷新恢复：先把快照读出来，等图片尺寸到位再套用
  pendingSnapshot = readViewerSnapshot()
  const restoredScroll =
    pendingSnapshot && pendingSnapshot.id === item.value?.id
      ? { text: pendingSnapshot.promptScroll, side: pendingSnapshot.sideScroll }
      : null

  // 图片可能已经在缓存里，load 事件不会再来一次
  const img = imgEl.value
  if (img && img.complete && img.naturalWidth) initFromImage(img)

  scheduleInfoFade()

  // 刷新前弹窗是开着的：同一张图 + 有临时提示词时自动恢复
  const savedPromptId = readPromptOpenId()
  if (savedPromptId !== null) {
    if (item.value?.id === savedPromptId && tempPrompt.value) {
      promptInfoOpen.value = true
      if (restoredScroll) {
        nextTick(() => {
          if (promptTextEl.value) promptTextEl.value.scrollTop = restoredScroll.text
          if (promptSideEl.value) promptSideEl.value.scrollTop = restoredScroll.side
        })
      }
    } else {
      savePromptOpen(false)
    }
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  clearInfoTimer()
  if (stateSaveTimer !== null) {
    window.clearTimeout(stateSaveTimer)
    stateSaveTimer = null
  }
  // 主动关掉灯箱时清掉记录；刷新页面不会走到这里
  savePromptOpen(false)
  try {
    localStorage.removeItem(VIEWER_STATE_KEY)
  } catch {
    /* localStorage 不可用时忽略 */
  }
  observer?.disconnect()
  observer = null
})

watch(
  () => props.index,
  () => {
    resetViewState()
    nextTick(() => {
      const img = imgEl.value
      if (img && img.complete && img.naturalWidth) initFromImage(img)
    })
  },
)

function resetViewState() {
  resetViewer()
  restoreInfo()
  scheduleInfoFade()
  promptInfoOpen.value = false
}

// ---------------------------------------------------------------------------
// 写操作：收藏 / 删除 / 下载 / 投喂工作流
// ---------------------------------------------------------------------------

const busy = ref(false)

async function toggleFavorite() {
  if (!item.value) return
  busy.value = true
  try {
    await apiPost(`/api/images/${item.value.id}/favorite`)
    toast.success(item.value.is_favorite ? '已取消收藏' : '已收藏')
    emit('changed')
  } catch (e) {
    toast.error(`操作失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    busy.value = false
  }
}

const { deleteFiles, outputSubfolder } = useSettings()

async function removeItem() {
  if (!item.value) return
  const { confirmed, checked } = await confirmDialogWithCheckbox({
    title: '删除出图记录',
    content: `确定删除「${item.value.filename}」这条出图记录吗？`,
    checkboxLabel: '同时删除磁盘上的原图文件（不可恢复）',
    // 与画廊批量删除共用同一份记忆（useSettings.deleteFiles）
    defaultChecked: deleteFiles.value,
    positiveText: '删除',
    negativeText: '取消',
  })
  deleteFiles.value = checked
  if (!confirmed) return
  busy.value = true
  try {
    await apiDelete(`/api/images/${item.value.id}`, { delete_files: checked })
    toast.success(checked ? '已删除该记录与原图文件' : '已删除该记录')
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

/** 文件名点击复制。 */
async function copyFilename() {
  if (!item.value) return
  try {
    await navigator.clipboard.writeText(item.value.filename)
    toast.success('已复制文件名')
  } catch {
    toast.error('复制失败（浏览器拒绝了剪贴板访问）')
  }
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
    await apiPost(`/api/images/${item.value.id}/process`, {
      workflow_path: processWf.value,
      output_subfolder: outputSubfolder.value,
    })
    toast.success('已提交处理任务，可在「任务」页看进度')
    processOpen.value = false
  } catch (e) {
    toast.error(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    busy.value = false
  }
}

// ---------------------------------------------------------------------------
// 提示词入口
// ---------------------------------------------------------------------------

const promptParams = computed<Record<string, unknown>>(
  () => (item.value?.prompt_params ?? {}) as Record<string, unknown>,
)

function textOf(value: unknown): string {
  return typeof value === 'string' ? value : typeof value === 'number' ? String(value) : ''
}

/** 没有关联提示词库记录、但出图参数里留了正文的「临时提示词」。 */
const tempPrompt = computed(() =>
  item.value?.prompt_id ? '' : textOf(promptParams.value.prompt).trim(),
)
const tempNegative = computed(() =>
  item.value?.prompt_id ? '' : textOf(promptParams.value.negative_prompt).trim(),
)

const PARAM_SOURCE_LABEL: Record<string, string> = {
  prompt_run: '提示词出图',
  text_run: '文本跑图',
  composer: '组合创作',
  batch_replace: '替换碎片出图',
  faceswap: '图像编辑',
  history_process: '图片处理',
}

const promptSource = computed(() => {
  const raw = textOf(promptParams.value.source)
  if (raw) return PARAM_SOURCE_LABEL[raw] ?? raw
  return sourceLabel(item.value?.source ?? '')
})

const PARAM_LABEL: Record<string, string> = {
  seed: '随机种子',
  steps: '步数',
  cfg_scale: 'CFG',
  sampler: '采样器',
  model: '模型',
  width: '宽度',
  height: '高度',
  orientation: '方向',
}

const paramRows = computed(() => {
  const p = promptParams.value
  return Object.keys(PARAM_LABEL)
    .filter((key) => p[key] !== null && p[key] !== undefined && p[key] !== '' && typeof p[key] !== 'object')
    .map((key) => ({ label: PARAM_LABEL[key], value: String(p[key]) }))
})

/** 换脸 / 图片处理这类任务额外留下的溯源字段。 */
const extraRows = computed(() => {
  const p = promptParams.value
  const rows: Array<{ label: string; value: string }> = []
  const original = textOf(p.original_filename)
  if (original) rows.push({ label: '处理源图', value: original })
  const inputImage = textOf(p.input_image)
  if (inputImage) rows.push({ label: '输入图', value: inputImage })
  if (Array.isArray(p.inputs)) {
    const roles = p.inputs
      .map((it) => (typeof it === 'object' && it ? textOf((it as Record<string, unknown>).role) : ''))
      .filter(Boolean)
    if (roles.length) rows.push({ label: '输入角色', value: roles.join(' / ') })
  }
  const sourceId = textOf(p.source_prompt_id)
  if (sourceId) {
    const sourceName = textOf(p.source_prompt_name)
    rows.push({
      label: '来源提示词',
      value: sourceName ? `${sourceName} (#${sourceId})` : `#${sourceId}`,
    })
  }
  return rows
})

async function copyText(text: string, label: string) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    toast.success(`已复制${label}`)
  } catch {
    toast.error('复制失败（浏览器拒绝了剪贴板访问）')
  }
}

// ---------------------------------------------------------------------------
// 刷新恢复：临时提示词弹窗
// ---------------------------------------------------------------------------

/** 灯箱由 GalleryView 恢复；这里只记「哪个图的弹窗是开着的」。 */
const PROMPT_OPEN_KEY = 'pb.viewer.promptOpen'

function readPromptOpenId(): number | null {
  try {
    const raw = localStorage.getItem(PROMPT_OPEN_KEY)
    if (!raw) return null
    const id = Number(raw)
    return Number.isFinite(id) ? id : null
  } catch {
    return null
  }
}

function savePromptOpen(open: boolean) {
  try {
    if (open && item.value) localStorage.setItem(PROMPT_OPEN_KEY, String(item.value.id))
    else localStorage.removeItem(PROMPT_OPEN_KEY)
  } catch {
    /* localStorage 不可用时忽略 */
  }
}

/**
 * 弹窗开关变化：记到 storage；并在合适时机保存完整视图快照
 * （打开瞬间 DOM 还没渲染，滚动位置要等下一帧再存）。
 */
watch(promptInfoOpen, async (open) => {
  savePromptOpen(open)
  if (!open) {
    saveViewerState()
    return
  }
  await nextTick()
  scheduleViewerSave()
})

// ---------------------------------------------------------------------------
// 完整视图快照：刷新前后保持一模一样
// ---------------------------------------------------------------------------

interface ViewerSnapshot {
  id: number
  fitMode: boolean
  scale: number
  /** 图片中心相对 stage 的坐标（0~1），窗口尺寸变化时也能对准 */
  fx: number
  fy: number
  rotation: number
  flipped: boolean
  showInfo: boolean
  infoFaded: boolean
  promptScroll: number
  sideScroll: number
}

const VIEWER_STATE_KEY = 'pb.viewer.state'
/** 刷新后第一次拿到图片尺寸时要套用的快照。 */
let pendingSnapshot: ViewerSnapshot | null = null
let stateSaveTimer: number | null = null

function readViewerSnapshot(): ViewerSnapshot | null {
  try {
    const raw = localStorage.getItem(VIEWER_STATE_KEY)
    return raw ? (JSON.parse(raw) as ViewerSnapshot) : null
  } catch {
    return null
  }
}

function saveViewerState() {
  const it = item.value
  if (!it || !natural.value.w) return
  const sw = stageSize.value.w || 1
  const sh = stageSize.value.h || 1
  try {
    const snapshot: ViewerSnapshot = {
      id: it.id,
      fitMode: fitMode.value,
      scale: view.scale,
      fx: view.cx / sw,
      fy: view.cy / sh,
      rotation: rotation.value,
      flipped: flipped.value,
      showInfo: showInfo.value,
      infoFaded: infoFaded.value,
      promptScroll: promptTextEl.value?.scrollTop ?? 0,
      sideScroll: promptSideEl.value?.scrollTop ?? 0,
    }
    localStorage.setItem(VIEWER_STATE_KEY, JSON.stringify(snapshot))
  } catch {
    /* localStorage 不可用时忽略 */
  }
}

/** 滚动这类高频事件：200ms 合并写一次。 */
function scheduleViewerSave() {
  if (stateSaveTimer !== null) return
  stateSaveTimer = window.setTimeout(() => {
    stateSaveTimer = null
    saveViewerState()
  }, 200)
}

function onPromptScroll() {
  if (promptInfoOpen.value) scheduleViewerSave()
}

function applyViewerSnapshot(s: ViewerSnapshot) {
  rotation.value = s.rotation ?? 0
  flipped.value = !!s.flipped
  showInfo.value = s.showInfo !== false
  infoFaded.value = !!s.infoFaded
  fitMode.value = !!s.fitMode
  syncStageSize()
  const fit = computeFit()
  const scale = fitMode.value ? fit : clampScale(s.scale || fit)
  view.scale = view.targetScale = scale
  view.cx = view.targetCx = (Number.isFinite(s.fx) ? s.fx : 0.5) * stageSize.value.w
  view.cy = view.targetCy = (Number.isFinite(s.fy) ? s.fy : 0.5) * stageSize.value.h
  constrainView()
  applyView()
}

// ---------------------------------------------------------------------------
// 信息卡：默认展示，不在上面时渐渐变淡；拖拽经过不触发唤回
// ---------------------------------------------------------------------------

/** 鼠标离开后多久开始变淡；渐变过程由 CSS transition 负责。 */
const INFO_FADE_DELAY_MS = 2000
let infoTimer: number | null = null
const infoHovering = ref(false)
const infoFaded = ref(false)

/**
 * 在 setup 阶段（首次渲染前）就先套用快照里的显隐/淡出/旋转状态，
 * 否则刷新后会先显示完整信息卡、再淡出，和刷新前不一致。
 */
pendingSnapshot = readViewerSnapshot()
if (pendingSnapshot && pendingSnapshot.id === item.value?.id) {
  infoFaded.value = !!pendingSnapshot.infoFaded
  showInfo.value = pendingSnapshot.showInfo !== false
  rotation.value = pendingSnapshot.rotation ?? 0
  flipped.value = !!pendingSnapshot.flipped
  fitMode.value = !!pendingSnapshot.fitMode
} else {
  pendingSnapshot = null
}

function clearInfoTimer() {
  if (infoTimer !== null) {
    window.clearTimeout(infoTimer)
    infoTimer = null
  }
}

function scheduleInfoFade() {
  clearInfoTimer()
  if (!showInfo.value || infoHovering.value || panning.value) return
  infoTimer = window.setTimeout(() => {
    infoFaded.value = true
    infoTimer = null
    saveViewerState()
  }, INFO_FADE_DELAY_MS)
}

function restoreInfo() {
  const wasFaded = infoFaded.value
  clearInfoTimer()
  infoFaded.value = false
  if (wasFaded) saveViewerState()
}

function onInfoEnter() {
  infoHovering.value = true
  if (!panning.value) restoreInfo()
}

/** 拖拽图片时指针扫过卡片不算「移动到信息上」，不会把它唤回。 */
function onInfoMove() {
  if (!panning.value) restoreInfo()
}

function onInfoLeave() {
  infoHovering.value = false
  scheduleInfoFade()
}

/** 工具栏 ⓘ：显示 / 隐藏信息卡。 */
function toggleInfo() {
  if (showInfo.value) {
    showInfo.value = false
    clearInfoTimer()
  } else {
    showInfo.value = true
    restoreInfo()
    scheduleInfoFade()
  }
  saveViewerState()
}

// ---------------------------------------------------------------------------
// 键盘
// ---------------------------------------------------------------------------

/**
 * 键盘：← → 翻页，+/- 缩放，0 重置，f 翻转，r 旋转。
 * Esc 由 useEscapeLayer 统一处理（弹层栈只有最上面一层响应）。
 */
function onKey(event: KeyboardEvent) {
  if (event.defaultPrevented) return
  if (event.key === 'ArrowLeft') go(-1)
  else if (event.key === 'ArrowRight') go(1)
  else if (event.key === '+' || event.key === '=') zoomBy(1.2)
  else if (event.key === '-') zoomBy(1 / 1.2)
  else if (event.key === '0') resetView()
  else if (event.key === 'f' || event.key === 'F') flip()
  else if (event.key === 'r' || event.key === 'R') rotate90()
}
</script>

<template>
  <div v-if="item" class="lightbox" @click.self="onRootClick">
    <header class="bar">
      <span class="pos">{{ index + 1 }} / {{ items.length }}</span>
      <span class="spacer" />

      <div v-if="processOpen && !readonly" class="wf-picker">
        <select v-model="processWf" class="wf-select">
          <option value="">选择工作流…</option>
          <option v-for="wf in workflows ?? []" :key="wf.path" :value="wf.path">{{ wf.name }}</option>
        </select>
        <button class="tool primary" :disabled="busy" @click="feedToWorkflow">投喂</button>
        <button class="tool" @click="processOpen = false">取消</button>
      </div>

      <button
        v-if="!readonly"
        class="tool"
        :title="processOpen ? '收起工作流选择' : '投喂给工作流处理（超分/重绘等）'"
        @click="processOpen = !processOpen"
      >
        ⚡
      </button>
      <button class="tool" title="下载原图" @click="download">⬇</button>
      <button class="tool" title="在资源管理器中打开所在目录" @click="revealImage(item)">目录</button>
      <button
        v-if="canOpenGallery"
        class="tool"
        title="到画廊里按文件名定位这张图"
        @click="emit('open-in-gallery', item.filename)"
      >
        🗂
      </button>
      <button
        v-if="canRegenerate && !readonly"
        class="tool"
        :class="{ loading: regenerating }"
        :disabled="regenerating"
        :title="regenerating ? '正在提交/生成…' : '用这张图的记录重新出图'"
        @click="emit('regenerate', item)"
      >
        {{ regenerating ? '' : '🔄' }}
      </button>
      <button
        v-if="item.prompt_id && !readonly"
        class="tool"
        title="跳到这条提示词"
        @click="emit('jump-to-prompt', item.prompt_id!)"
      >
        ↗
      </button>
      <button
        v-if="!readonly"
        class="tool"
        :title="item.is_favorite ? '取消收藏' : '收藏'"
        @click="toggleFavorite"
      >
        {{ item.is_favorite ? '★' : '☆' }}
      </button>
      <button class="tool" title="水平翻转 (F)" @click="flip">⇋</button>
      <button class="tool" title="旋转 90° (R)" @click="rotate90">⟳</button>
      <button class="tool" :class="{ active: !fitMode }" title="适应 / 原始尺寸" @click="toggleFit">
        1:1
      </button>
      <button class="tool" title="缩小 (-)" @click="zoomBy(1 / 1.2)">−</button>
      <span class="zoom">{{ zoomPercent }}%</span>
      <button class="tool" title="放大 (+)" @click="zoomBy(1.2)">+</button>
      <button class="tool" title="重置视图 (0)" @click="resetView">重置</button>
      <button class="tool" :class="{ active: showInfo }" title="显示/隐藏信息" @click="toggleInfo">
        ⓘ
      </button>
      <button v-if="!readonly" class="tool danger" title="删除记录" @click="removeItem">🗑</button>
      <button class="tool close" title="关闭 (Esc)" @click="emit('close')">✕</button>
    </header>

    <button class="nav prev" :disabled="!hasPrev" title="上一张 (←)" @click="go(-1)">‹</button>

    <figure
      ref="stageEl"
      class="stage"
      :class="{ dragging: panning }"
      @wheel.prevent="onWheel"
      @mousedown="onPanStart"
      @click="onStageClick"
    >
      <img
        ref="imgEl"
        :src="viewUrl(item)"
        :alt="item.filename"
        :class="{ loaded: imgLoaded }"
        :draggable="false"
        @load="onImageLoad"
      />
    </figure>

    <button class="nav next" :disabled="!hasNext" title="下一张 (→)" @click="go(1)">›</button>

    <aside
      v-if="showInfo"
      class="info"
      :class="{ faded: infoFaded, instant: panning }"
      @click.stop
      @mouseenter="onInfoEnter"
      @mousemove="onInfoMove"
      @mouseleave="onInfoLeave"
    >
      <div class="info-head">
        <span
          class="filename copyable"
          :title="`点击复制：${item.filename}`"
          @click.stop="copyFilename"
        >
          {{ item.filename }}
        </span>
        <span v-if="resolution(item)" class="info-sum">{{ resolution(item) }}</span>
      </div>

      <div class="info-body">
        <dl class="facts">
          <div v-if="resolution(item)"><dt>分辨率</dt><dd>{{ resolution(item) }}</dd></div>
          <div v-if="item.file_size"><dt>体积</dt><dd>{{ formatSize(item.file_size) }}</dd></div>
          <div><dt>来源</dt><dd>{{ sourceLabel(item.source) }}</dd></div>
          <div><dt>出图时间</dt><dd>{{ shotTime(item) }}</dd></div>
          <div>
            <dt>存储位置</dt>
            <dd class="path" :title="outputPath">{{ outputPath }}</dd>
          </div>
          <div v-if="item.prompt_name"><dt>提示词</dt><dd>{{ item.prompt_name }}</dd></div>
        </dl>

        <button
          v-if="item.prompt_id"
          class="prompt-link"
          title="打开提示词库里的这条提示词"
          @click="emit('jump-to-prompt', item.prompt_id!)"
        >
          📝 跳到提示词{{ item.prompt_name ? `：${item.prompt_name}` : '' }}
        </button>
        <button
          v-else-if="tempPrompt"
          class="prompt-link"
          title="查看这张图出图时记录的临时提示词与参数"
          @click="promptInfoOpen = true"
        >
          📝 查看提示词信息（临时）
        </button>

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
          快捷键：← → 翻页 · 滚轮/+ − 缩放 · 拖拽平移 · 0 重置 · F 翻转 · R 旋转 · Esc 关闭
        </p>
      </div>
    </aside>

    <Modal
      :open="promptInfoOpen"
      headless
      raised
      width="min(1100px, 94vw)"
      height="86vh"
      @close="promptInfoOpen = false"
    >
      <div class="prompt-info">
        <div class="prompt-cols">
          <div class="prompt-main">
            <div class="prompt-box">
              <pre
                ref="promptTextEl"
                class="prompt-text main-prompt"
                @scroll.passive="onPromptScroll"
              >{{ tempPrompt || '（出图参数里没有留下提示词正文）' }}</pre>
            </div>
          </div>

          <aside
            ref="promptSideEl"
            class="prompt-side"
            @scroll.passive="onPromptScroll"
          >
            <div class="side-head">
              <h3
                class="side-heading copyable"
                title="点击复制文件名"
                @click="copyFilename"
              >
                出图参数（未关联提示词库）
              </h3>
              <button class="btn btn-sm" @click="promptInfoOpen = false">关闭</button>
            </div>

            <section class="side-block">
              <h3 class="side-title">文件信息</h3>
              <div
                class="side-filename copyable"
                title="点击复制文件名"
                @click="copyFilename"
              >
                {{ item.filename }}
              </div>
              <div v-if="promptSource" class="side-row">
                <span>来源</span><b>{{ promptSource }}</b>
              </div>
              <div class="side-row">
                <span>出图时间</span><b>{{ shotTime(item) }}</b>
              </div>
            </section>

            <button
              class="btn btn-sm side-copy"
              :disabled="!tempPrompt"
              @click="copyText(tempPrompt, '正向提示词')"
            >
              复制正向提示词
            </button>

            <section v-if="tempNegative" class="side-block">
              <h3 class="side-title">负面提示词</h3>
              <pre class="prompt-text side-prompt">{{ tempNegative }}</pre>
            </section>

            <dl v-if="paramRows.length" class="facts side-facts">
              <div v-for="row in paramRows" :key="row.label">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>

            <dl v-if="extraRows.length" class="facts side-facts">
              <div v-for="row in extraRows" :key="row.label">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>

            <p class="prompt-tip">
              这张图没有关联提示词库记录，以上内容来自出图时的参数快照。
            </p>
          </aside>
        </div>
      </div>
    </Modal>
  </div>
</template>

<style scoped>
.lightbox {
  position: fixed;
  inset: 0;
  /* 高于普通弹窗：结果中心/任务弹窗里点缩略图看原图时，查看器要盖在弹窗上面 */
  z-index: var(--z-lightbox);
  display: flex;
  /* header 在文档流里占一行，stage 拿到剩余高度 —— 图片不会被工具栏盖住，
     也不用再在 padding 里手动预留 40px。 */
  flex-direction: column;
  background: rgba(0, 0, 0, 0.88);
  backdrop-filter: blur(2px);
}

.bar {
  position: relative;
  z-index: 3;
  flex: none;
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

/* 重新出图提交中：复用 tokens.css 里的 btn-spin 转圈 */
.tool.loading::before {
  content: '';
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: btn-spin 0.7s linear infinite;
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
  /* figure 自带 1em 40px 外边距，不清掉会左右各缩 40px、上下多占 32px */
  margin: 0;
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  cursor: grab;
  /* 拖拽时禁止浏览器接管手势 / 选中 */
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
  /* 加载完再显示，避免先按错误尺寸闪一下 */
  opacity: 0;
}

.stage img.loaded {
  opacity: 1;
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
  z-index: 2;
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
  right: 16px;
}

/* 左下角浮层：默认展示；鼠标不在上面时渐渐变淡，移回来再恢复 */
.info {
  position: absolute;
  left: 16px;
  bottom: 16px;
  z-index: 2;
  /* 刚好容纳快捷键那一行（实测文本 402px + 左右内边距 20px + 边框 2px），不再多余加宽 */
  width: min(432px, 86vw);
  max-height: min(52vh, 460px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: rgba(16, 20, 26, 0.72);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  backdrop-filter: blur(10px);
  transition: opacity 0.35s ease;
}

.info.faded {
  /* 完全透明，但仍保留鼠标响应区：移动到这里会重新显形 */
  opacity: 0;
  transition: opacity 1.8s ease;
}

/* 拖图时不必慢慢渐隐，快速让开画面 */
.info.instant {
  transition: opacity 0.2s ease;
}

.info-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
}

.info-sum {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.info-body {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  min-height: 0;
  padding: 0 10px 10px;
  overflow-y: auto;
}

.filename {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-sm);
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.filename.copyable {
  cursor: copy;
}

.filename.copyable:hover {
  color: var(--primary);
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
  width: 74px;
  color: var(--muted);
}

.facts dd {
  margin: 0;
  word-break: break-all;
}

.prompt-link {
  display: block;
  width: 100%;
  text-align: left;
  padding: 6px 10px;
  font-size: var(--fs-sm);
  color: var(--text);
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.prompt-link:hover {
  border-color: var(--primary);
  color: var(--primary);
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
  /* 卡片已加宽，这行提示不换行 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 临时提示词弹窗：占满弹窗高度，提示词给最大空间 */
.prompt-info {
  height: 100%;
  box-sizing: border-box;
  padding: var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

/* 左侧全部给提示词，文件信息与参数都收在右栏 */
.prompt-cols {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: var(--gap);
}

.prompt-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.prompt-side {
  flex: none;
  width: 340px;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding-right: 2px;
}

.side-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: none;
}

.side-title {
  margin: 0 0 2px;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--muted);
}

/* 文件名：右栏里需要被一眼看到，放大加粗 */
.side-filename {
  font-size: var(--fs);
  font-weight: 700;
  line-height: 1.5;
  word-break: break-all;
}

.side-row {
  display: flex;
  gap: 8px;
  font-size: var(--fs-sm);
}

.side-row span {
  flex: none;
  width: 62px;
  color: var(--muted);
}

.side-row b {
  font-weight: 600;
  color: var(--text);
  word-break: break-all;
}

.side-head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-sm);
}

.side-heading {
  margin: 0;
  font-size: var(--fs);
  font-weight: 600;
}

.side-heading.copyable,
.side-filename.copyable {
  cursor: copy;
}

.side-heading.copyable:hover,
.side-filename.copyable:hover {
  color: var(--primary);
}

.side-copy {
  flex: none;
  width: 100%;
}

.side-facts {
  gap: 4px;
  flex: none;
}

.side-facts div {
  font-size: var(--fs-sm);
}

/* 提示词容器：只套一层边框，不再有标题栏占高度 */
.prompt-box {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  overflow: hidden;
}

/* 提示词本身仍是纯文本，滚动发生在容器内部 */
.prompt-text {
  margin: 0;
  padding: 0;
  overflow: auto;
  font-family: inherit;
  font-size: var(--fs-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  background: transparent;
}

/* 左栏正向提示词占满整个高度 */
.main-prompt {
  flex: 1;
  min-height: 0;
}

/* 右栏负面提示词保持小高度，避免把参数挤下去 */
.side-prompt {
  max-height: 140px;
  padding-top: 2px;
}

.prompt-tip {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--muted);
  line-height: 1.6;
}

@media (max-width: 820px) {
  .prompt-cols {
    flex-direction: column;
  }

  .prompt-side {
    width: auto;
    max-height: 40%;
  }
}
</style>
