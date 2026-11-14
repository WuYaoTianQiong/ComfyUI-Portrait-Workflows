<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { apiDelete, apiGet, apiPost, viewUrl } from '../api/client'
import Icon from './Icon.vue'
import { useToast } from '../composables/useToast'
import { useImageLocation } from '../composables/useImageLocation'
import type { HistoryItem, ImageDetail, PromptDetail } from '../api/types'
import {
  formatDateTime,
  formatElapsed,
  formatSize,
  resolution,
  shotTime,
  sourceLabel,
  statusLabel,
} from '../utils/format'
import { confirmDialogWithCheckbox } from '../utils/naive'
import { useSettings } from '../composables/useSettings'
import { useEscapeLayer } from '../composables/useEscapeLayer'
import { useLoadTimeout } from '../composables/useLoadTimeout'
import { useViewerTransform } from '../composables/useViewerTransform'
import ManualCleanupModal from './ManualCleanupModal.vue'
import Modal from './Modal.vue'
import Skeleton from './Skeleton.vue'

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
const props = withDefaults(
  defineProps<{
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
    /**
     * 文件类操作：下载原图 / 在资源管理器中打开目录 / 出片档案 / 存储位置。
     * 这些入口都依赖 ComfyUI input/output/temp 三目录内的 `filename`；
     * 参考图等非历史记录条目打开时传 false，默认 true 不影响画廊 / 任务页。
     */
    fileActions?: boolean
  }>(),
  { fileActions: true },
)

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
const router = useRouter()
const { revealImage } = useImageLocation()

const item = computed<HistoryItem | undefined>(() => props.items[props.index])

useEscapeLayer(() => !!item.value, () => emit('close'))
const outputPath = computed(() => {
  const it = item.value
  if (!it) return ''
  const base = it.img_type && it.img_type !== 'output' ? it.img_type : 'output'
  return `${base}/${it.subfolder ? `${it.subfolder}/` : ''}${it.filename}`
})

/** `fileActions` 缺省时按 true 处理（画廊 / 任务页不传，行为不变）。 */
const showFileActions = computed(() => props.fileActions !== false)

/**
 * 展示 / 下载用的图片地址。
 *
 * 历史记录的 `view_url` 是后端 `build_view_url()` 的产物，与 `viewUrl(item)`
 * 完全同格式，因此优先用它不会改变画廊 / 任务页的地址；缺失时（老记录 /
 * 占位 fixture）回落到统一的 `viewUrl` 拼装。参考图这类不在媒体三目录内的
 * 条目，只有后端下发的 `view_url` 能指向真实图片。
 */
function displayUrl(target: HistoryItem): string {
  return target.view_url || viewUrl(target)
}

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
  imageError.value = false
  loadTimedOut.value = false
  loadTimeout.stop()
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

/** 图片加载失败：显示统一的「重试」，而不是裂图。 */
const imageError = ref(false)
/** 递增后通过 key 重建 img 元素，强制重新拉取原图。 */
const reloadNonce = ref(0)
/** 加载超时（请求挂起）：与失败共用错误态，但文案区分。 */
const loadTimedOut = ref(false)
const loadTimeout = useLoadTimeout(() => {
  loadTimedOut.value = true
  imgLoaded.value = false
})

/** 重试时给 URL 追加 nonce，绕过可能卡死的浏览器/代理缓存条目。 */
const imgSrc = computed(() => {
  const url = item.value ? displayUrl(item.value) : ''
  if (!reloadNonce.value) return url
  return `${url}${url.includes('?') ? '&' : '?'}_r=${reloadNonce.value}`
})

function onImageError() {
  imageError.value = true
  imgLoaded.value = false
  loadTimeout.stop()
}

function retryImage() {
  imageError.value = false
  loadTimedOut.value = false
  reloadNonce.value++
  loadTimeout.start()
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
  else loadTimeout.start()

  scheduleInfoFade()

  // 刷新前弹窗是开着的：同一张图时自动恢复
  const savedPromptId = readPromptOpenId()
  if (savedPromptId !== null) {
    if (item.value?.id === savedPromptId) {
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
      else loadTimeout.start()
    })
  },
)

function resetViewState() {
  resetViewer()
  imageError.value = false
  loadTimedOut.value = false
  loadTimeout.stop()
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
  window.open(displayUrl(item.value), '_blank')
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

const manualCleanupOpen = ref(false)

function onCleanupApplied() {
  emit('changed')
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

/** 输入图角色 → 档案里的展示文案（合成台与图像编辑共用同一套角色名）。 */
const INPUT_ROLE_LABEL: Record<string, string> = {
  target: '主图',
  ref1: '参考1',
  ref2: '参考2',
  ref3: '参考3',
  ref4: '参考4',
}

interface ReferenceInput {
  label: string
  path: string
}

/**
 * 合成台 / 图像编辑提交时，每张输入图的绝对路径都写进了
 * `prompt_params.inputs[].meta.path`；这里原样取出交给 `/api/browser/*` 读取。
 * 只有提示词出图这类没有输入图的记录才为空，档案里也不会出现空区块。
 */
const referenceInputs = computed<ReferenceInput[]>(() => {
  const raw = promptParams.value.inputs
  if (!Array.isArray(raw)) return []
  const out: ReferenceInput[] = []
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue
    const row = entry as Record<string, unknown>
    const rawMeta = row.meta
    const meta = rawMeta && typeof rawMeta === 'object'
      ? (rawMeta as Record<string, unknown>)
      : {}
    const path = textOf(meta.path)
    if (!path) continue
    const role = textOf(row.role)
    out.push({ label: INPUT_ROLE_LABEL[role] ?? (role || '参考图'), path })
  }
  return out
})

function referenceThumb(path: string): string {
  return `/api/browser/thumb?path=${encodeURIComponent(path)}&size=200`
}

function referenceImage(path: string): string {
  return `/api/browser/image?path=${encodeURIComponent(path)}`
}

/** 参考图放大预览（只读）：复用画廊灯箱的缩放引擎，不绑定出图记录。 */
const previewRef = ref<ReferenceInput | null>(null)
const previewError = ref(false)
const previewReloadNonce = ref(0)
const previewTimedOut = ref(false)
const previewTimeout = useLoadTimeout(() => {
  previewTimedOut.value = true
  previewImgLoaded.value = false
})

const previewSrc = computed(() => {
  if (!previewRef.value) return ''
  const url = referenceImage(previewRef.value.path)
  if (!previewReloadNonce.value) return url
  return `${url}${url.includes('?') ? '&' : '?'}_r=${previewReloadNonce.value}`
})

const {
  stageEl: previewStageEl,
  imgEl: previewImgEl,
  imgLoaded: previewImgLoaded,
  fitMode: previewFitMode,
  initView: previewInitView,
  setNaturalSize: previewSetNaturalSize,
  onWheel: previewOnWheel,
  onPanStart: previewOnPanStart,
  onStageClick: previewOnStageClick,
  rotate90: previewRotate90,
  flip: previewFlip,
  toggleFit: previewToggleFit,
  reset: previewReset,
} = useViewerTransform({
  onStageClick: () => closeReferencePreview(),
  fitPadding: 32,
})

function closeReferencePreview() {
  previewRef.value = null
  previewError.value = false
  previewTimedOut.value = false
  previewTimeout.stop()
  previewReset()
}

useEscapeLayer(() => !!previewRef.value, closeReferencePreview)

function openReferencePreview(ref: ReferenceInput) {
  previewRef.value = ref
  previewError.value = false
  previewTimedOut.value = false
  previewReloadNonce.value += 1
  void nextTick(() => {
    // 图片可能已在缓存里，load 事件不会再触发
    const img = previewImgEl.value
    if (img && img.complete && img.naturalWidth) {
      previewSetNaturalSize(img)
      previewInitView()
    } else {
      previewTimeout.start()
    }
  })
}

function onPreviewImageLoad(event: Event) {
  previewError.value = false
  previewTimedOut.value = false
  previewTimeout.stop()
  previewSetNaturalSize(event.target as HTMLImageElement)
  previewInitView()
}

function onPreviewImageError() {
  previewError.value = true
  previewImgLoaded.value = false
  previewTimeout.stop()
}

function retryPreviewImage() {
  previewError.value = false
  previewTimedOut.value = false
  previewReloadNonce.value += 1
  previewTimeout.start()
}

interface ReferenceResolveResult {
  found: boolean
  library?: string
  item_id?: string
  name?: string
  tab?: string
  q?: string
}

const referenceResolving = ref(false)

/**
 * 「在参考图库中打开」：后端按绝对路径反查出库条目，再跳到对应页签并预填检索词。
 * 上传图 / 临时文件不属于任何库条目，给明确提示而不是跳到一个空搜索。
 */
async function openInReferenceLibrary() {
  const current = previewRef.value
  if (!current || referenceResolving.value) return
  referenceResolving.value = true
  try {
    const hit = await apiGet<ReferenceResolveResult>('/api/reference/resolve', {
      path: current.path,
    })
    if (!hit?.found || !hit.tab) {
      toast.info('该参考图不在参考图库中（上传图或缓存图）')
      return
    }
    closeReferencePreview()
    void router.push({
      path: '/reference',
      query: { tab: hit.tab, q: hit.q || hit.item_id || '' },
    })
  } catch (e) {
    toast.error(`定位参考图失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    referenceResolving.value = false
  }
}

/**
 * 出图时记录在参数里的提示词正文。
 * 已关联提示词库的图也保留一份快照 —— 库里后来改过，也能看到这张图当时用的版本。
 */
const recordedPrompt = computed(
  () =>
    textOf(promptParams.value.prompt).trim() ||
    textOf((detail.value?.prompt_params as Record<string, unknown> | null | undefined)?.prompt).trim(),
)
const recordedNegative = computed(
  () =>
    textOf(promptParams.value.negative_prompt).trim() ||
    textOf((detail.value?.prompt_params as Record<string, unknown> | null | undefined)?.negative_prompt).trim(),
)

/**
 * 已关联提示词库、但出图记录没留正文的旧图：只读补一份库里的当前版本，
 * 免得档案左栏空着。是否回退会在标题旁标注，避免和"出图时快照"混淆。
 */
const libraryPrompt = ref<PromptDetail | null>(null)
const libraryPromptText = computed(() => textOf(libraryPrompt.value?.prompt).trim())

const shownPrompt = computed(() => recordedPrompt.value || libraryPromptText.value)
const shownNegative = computed(
  () => recordedNegative.value || textOf(libraryPrompt.value?.negative_prompt).trim(),
)
const promptNote = computed(() => {
  if (!item.value?.prompt_id) return ''
  if (recordedPrompt.value) return '· 出图时快照'
  return libraryPromptText.value ? '· 当前提示词库版本' : ''
})

const promptPlaceholder = computed(() =>
  item.value?.prompt_id
    ? '（这条出图记录没有留下提示词正文，可打开提示词库查看）'
    : '（出图参数里没有留下提示词正文）',
)

interface CompiledSnapshot {
  positive?: unknown
  negative?: unknown
  notes?: unknown
  warnings?: unknown
  negative_effective?: boolean
}

/** 提交时的编译快照：原文在左栏，这里展示实际注入的正向与负向。 */
const compiled = computed<CompiledSnapshot | null>(() => {
  const raw = promptParams.value.compiled
  return raw && typeof raw === 'object' ? (raw as CompiledSnapshot) : null
})
const compiledPositive = computed(() => textOf(compiled.value?.positive).trim())
const compiledNegative = computed(() => textOf(compiled.value?.negative).trim())
const compiledEffective = computed(() => compiled.value?.negative_effective !== false)
const stringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((x): x is string => typeof x === 'string') : []
const compiledNotes = computed(() => stringList(compiled.value?.notes))
const compiledWarnings = computed(() => stringList(compiled.value?.warnings))

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

/**
 * 面板打开时才补取完整参数（工作流 / 实际采样参数 / 耗时）。
 * 列表接口只带快照，逐张图查 ComfyUI history 会把画廊拖慢。
 */
const detail = ref<ImageDetail | null>(null)
const detailLoading = ref(false)
let detailSeq = 0

watch(
  [promptInfoOpen, () => item.value?.id],
  async ([open, id]) => {
    if (!open || !id) {
      detail.value = null
      libraryPrompt.value = null
      detailLoading.value = false
      return
    }
    const seq = ++detailSeq
    detailLoading.value = true
    const promptId = item.value?.prompt_id ?? 0
    // 有出图时快照就不必再查库；只有旧图缺正文时补一次当前版本
    const libraryPromise =
      promptId && !recordedPrompt.value
        ? apiGet<PromptDetail>(`/api/prompts/${promptId}`).catch(() => null)
        : Promise.resolve(null)
    try {
      const [data, lib] = await Promise.all([
        apiGet<ImageDetail>(`/api/images/${id}/detail`),
        libraryPromise,
      ])
      if (seq === detailSeq) {
        detail.value = data
        libraryPrompt.value = lib
      }
    } catch {
      if (seq === detailSeq) {
        detail.value = null
        libraryPrompt.value = null
      }
    } finally {
      if (seq === detailSeq) detailLoading.value = false
    }
  },
  { immediate: true },
)

function pick(...values: unknown[]): string {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue
    return String(value)
  }
  return ''
}

interface ArchiveRow {
  label: string
  value: string
  title?: string
  /** 长字段（路径、文件名、模型名）独占整行。 */
  wide?: boolean
  /** 有值时整行可点击跳到对应提示词。 */
  promptId?: number
}

/** 文件信息：短字段两列，存储位置单独整行并支持定位。 */
const fileRows = computed<ArchiveRow[]>(() => {
  const it = item.value
  if (!it) return []
  return [
    { label: '来源', value: promptSource.value },
    { label: '出图时间', value: shotTime(it) || '—' },
    { label: '执行耗时', value: elapsedText.value || '—' },
    { label: '分辨率', value: resolution(it) },
    { label: '体积', value: it.file_size ? formatSize(it.file_size) : '' },
  ].filter((row) => row.value)
})

/** 实际运行参数：任务快照 → ComfyUI history → PNG 元数据，缺失的逐项回退。 */
const runParamRows = computed<ArchiveRow[]>(() => {
  const p = promptParams.value
  const run = detail.value?.run
  const sampler = [pick(run?.sampler, p.sampler), pick(run?.scheduler, p.scheduler)]
    .filter(Boolean)
    .join(' · ')
  return [
    { label: '模型', value: pick(run?.model, p.model), wide: true },
    { label: '采样器', value: sampler },
    { label: '步数', value: pick(run?.steps, p.steps) },
    { label: 'CFG', value: pick(run?.cfg_scale, p.cfg_scale) },
    { label: '去噪', value: pick(run?.denoise, p.denoise) },
    { label: '随机种子', value: pick(run?.seed, p.seed) },
    { label: '方向', value: pick(p.orientation) },
  ].filter((row) => row.value)
})

const QUALITY_SCALES: Record<string, number> = {
  '0.75x': 0.75,
  '1.0x': 1,
  '1.25x': 1.25,
  '1.5x': 1.5,
  '2.0x': 2,
  // 兼容迁移前的历史记录
  '2K': 0.75,
  '4K': 1,
  '6K': 1.25,
  '8K': 1.5,
  '12K': 2,
}

/** 档案里不暴露内部键（8K），用真实宽高反算倍率与 MP。 */
const qualityText = computed(() => {
  const q = detail.value?.run.quality
  if (!q) return ''
  const scale = QUALITY_SCALES[q]
  const it = item.value
  if (!scale || !it?.width || !it?.height) return q
  const mp = (it.width * it.height) / 1_000_000
  return `${scale}× · ${Math.round(mp * 100) / 100}MP · ${it.width}×${it.height}`
})

const workflowRows = computed<ArchiveRow[]>(() => {
  const run = detail.value?.run
  if (!run) return []
  return [
    {
      label: '工作流',
      value: pick(run.workflow_name, run.workflow_path),
      title: run.workflow_path,
      wide: true,
    },
    { label: '质量档位', value: qualityText.value, title: run.quality },
    { label: '出图比例', value: run.aspect_ratio, title: '' },
    { label: '输出目录', value: run.output_subfolder, title: '', wide: true },
    { label: '提交时间', value: formatDateTime(run.submitted_at, true), title: run.submitted_at },
    { label: '完成时间', value: formatDateTime(run.finished_at, true), title: run.finished_at },
  ].filter((row) => row.value)
})

const jobRow = computed(() => {
  const d = detail.value
  if (!d?.job_title) return null
  const status = statusLabel(d.job_status)
  return {
    title: d.job_title,
    status,
    text: status ? `${d.job_title} · ${status}` : d.job_title,
  }
})

const elapsedText = computed(() => formatElapsed(detail.value?.run.duration_seconds))

/** 换脸 / 图片处理这类任务额外留下的溯源字段。 */
const extraRows = computed<ArchiveRow[]>(() => {
  const p = promptParams.value
  const rows: ArchiveRow[] = []
  const original = textOf(p.original_filename)
  if (original) rows.push({ label: '处理源图', value: original, title: original, wide: true })
  const inputImage = textOf(p.input_image)
  if (inputImage) rows.push({ label: '输入图', value: inputImage, title: inputImage, wide: true })
  if (Array.isArray(p.inputs)) {
    const roles = p.inputs
      .map((it) => (typeof it === 'object' && it ? textOf((it as Record<string, unknown>).role) : ''))
      .filter(Boolean)
    if (roles.length) rows.push({ label: '输入角色', value: roles.join(' / ') })
  }
  const sourceId = Number(textOf(p.source_prompt_id))
  if (Number.isFinite(sourceId) && sourceId > 0) {
    const sourceName = textOf(p.source_prompt_name)
    rows.push({
      label: '来源提示词',
      value: sourceName ? `${sourceName} (#${sourceId})` : `#${sourceId}`,
      title: `打开提示词${sourceName ? `：${sourceName}` : ` #${sourceId}`}`,
      wide: true,
      promptId: sourceId,
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

/** 档案里的提示词入口：先收起弹窗，再交给父组件跳转。 */
function jumpToPrompt(promptId: number) {
  promptInfoOpen.value = false
  emit('jump-to-prompt', promptId)
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
  if (previewRef.value) return
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
        <Icon name="zap" />
      </button>
      <button v-if="showFileActions" class="tool" title="下载原图" @click="download"><Icon name="download" /></button>
      <button
        v-if="showFileActions"
        class="tool"
        title="在资源管理器中打开所在目录"
        @click="revealImage(item)"
      >
        目录
      </button>
      <button
        v-if="canOpenGallery"
        class="tool"
        title="到画廊里按文件名定位这张图"
        @click="emit('open-in-gallery', item.filename)"
      >
        <Icon name="crosshair" />
      </button>
      <button
        v-if="canRegenerate && !readonly"
        class="tool"
        :class="{ loading: regenerating }"
        :disabled="regenerating"
        :title="regenerating ? '正在提交/生成…' : '用这张图的记录重新出图'"
        @click="emit('regenerate', item)"
      >
        <Icon v-if="!regenerating" name="refresh-cw" />
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
      <button v-if="!readonly" class="tool danger" title="删除记录" @click="removeItem"><Icon name="trash-2" /></button>
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
      <div v-if="!imgLoaded && !imageError && !loadTimedOut" class="stage-state loading">
        <Skeleton
          variant="block"
          width="min(360px, 56vw)"
          height="min(520px, 58vh)"
          radius="var(--radius)"
        />
        <span>加载中…</span>
      </div>
      <div v-else-if="imageError || loadTimedOut" class="stage-state error" @click.stop>
        <span>{{ loadTimedOut ? '图片加载超时（30 秒无响应），请重试' : '图片加载失败，请检查文件是否存在' }}</span>
        <button class="btn btn-sm" @click.stop="retryImage">重试</button>
      </div>

      <img
        ref="imgEl"
        :key="`${item.id}-${reloadNonce}`"
        :src="imgSrc"
        :alt="item.filename"
        :class="{ loaded: imgLoaded }"
        :draggable="false"
        @load="onImageLoad"
        @error="onImageError"
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
          <div v-if="showFileActions">
            <dt>存储位置</dt>
            <dd class="path" :title="outputPath">{{ outputPath }}</dd>
          </div>
          <div v-if="item.prompt_name"><dt>提示词</dt><dd>{{ item.prompt_name }}</dd></div>
        </dl>

        <button
          v-if="showFileActions"
          class="prompt-link"
          title="查看这张图的提示词、工作流与出图参数"
          @click="promptInfoOpen = true"
        >
          <Icon name="clipboard-list" /> 出图档案
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
          <Icon name="ban" /> 磁盘上已找不到这个文件，记录与标签仍保留
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
        <div v-if="previewRef" class="ref-preview" @click.self="closeReferencePreview">
          <div class="ref-preview-bar">
            <span class="ref-preview-title">{{ previewRef.label }}</span>
            <span class="ref-preview-path" :title="previewRef.path">{{ previewRef.path }}</span>
            <span class="spacer" />
            <button class="btn btn-sm" type="button" title="水平翻转" @click="previewFlip">
              ⇋
            </button>
            <button class="btn btn-sm" type="button" title="旋转 90°" @click="previewRotate90">
              ⟳
            </button>
            <button
              class="btn btn-sm"
              :class="{ active: !previewFitMode }"
              type="button"
              title="适应 / 原始尺寸"
              @click="previewToggleFit"
            >
              1:1
            </button>
            <button
              class="btn btn-sm"
              type="button"
              :disabled="referenceResolving"
              @click="openInReferenceLibrary"
            >
              {{ referenceResolving ? '定位中…' : '在参考图库中打开' }}
            </button>
            <a
              class="btn btn-sm"
              :href="referenceImage(previewRef.path)"
              target="_blank"
              rel="noopener"
            >
              新窗口打开原图
            </a>
            <button class="btn btn-sm" type="button" @click="closeReferencePreview">关闭</button>
          </div>
          <div
            ref="previewStageEl"
            class="ref-preview-stage"
            @wheel.prevent="previewOnWheel"
            @mousedown="previewOnPanStart"
            @click="previewOnStageClick"
          >
            <span v-if="!previewImgLoaded && !previewError && !previewTimedOut" class="ref-preview-state">
              加载中…
            </span>
            <div v-else-if="previewError || previewTimedOut" class="ref-preview-state error" @click.stop>
              <span>{{ previewTimedOut ? '参考图加载超时（30 秒无响应），请重试' : '参考图加载失败，请检查文件是否存在' }}</span>
              <button class="btn btn-sm" type="button" @click.stop="retryPreviewImage">
                重试
              </button>
            </div>
            <img
              :key="`${previewRef.path}-${previewReloadNonce}`"
              ref="previewImgEl"
              class="ref-preview-img"
              :class="{ loaded: previewImgLoaded }"
              :src="previewSrc"
              :alt="previewRef.label"
              :draggable="false"
              @load="onPreviewImageLoad"
              @error="onPreviewImageError"
            />
          </div>
        </div>

        <div class="prompt-cols">
          <div class="prompt-main">
            <section class="text-section">
              <header class="text-head">
                <span>
                  正向提示词
                  <span v-if="promptNote" class="text-note">{{ promptNote }}</span>
                </span>
                <div class="text-actions">
                  <button
                    v-if="item.prompt_id"
                    class="btn btn-sm prompt-jump"
                    :title="item.prompt_name || `#${item.prompt_id}`"
                    @click="jumpToPrompt(item.prompt_id!)"
                  >
                    ↗ 提示词库{{ item.prompt_name ? `：${item.prompt_name}` : '' }}
                  </button>
                  <button
                    class="btn btn-sm"
                    :disabled="!shownPrompt"
                    @click="copyText(shownPrompt, '正向提示词')"
                  >
                    复制
                  </button>
                </div>
              </header>
              <div class="prompt-box">
                <pre
                  ref="promptTextEl"
                  class="prompt-text main-prompt"
                  @scroll.passive="onPromptScroll"
                >{{ shownPrompt || promptPlaceholder }}</pre>
              </div>
            </section>

            <section v-if="shownNegative" class="text-section neg-section">
              <header class="text-head">
                <span>负面提示词</span>
                <button class="btn btn-sm" @click="copyText(shownNegative, '负面提示词')">
                  复制
                </button>
              </header>
              <pre class="prompt-text neg-prompt">{{ shownNegative }}</pre>
            </section>

            <section v-if="compiledPositive" class="text-section compiled-section">
              <header class="text-head">
                <span>
                  编译后
                  <span class="text-note">· 负向{{ compiledEffective ? '生效' : '不生效' }}</span>
                </span>
                <button class="btn btn-sm" @click="copyText(compiledPositive, '编译后正向')">
                  复制
                </button>
              </header>
              <div class="compiled-grid">
                <div>
                  <h4>正向（提交）</h4>
                  <pre class="prompt-text compiled-text compiled-positive">{{ compiledPositive }}</pre>
                </div>
                <div>
                  <h4>实际负向（{{ compiledEffective ? '提交' : '不提交' }}）</h4>
                  <pre class="prompt-text compiled-text compiled-negative">{{ compiledEffective ? (compiledNegative || '（空）') : '（工作流负向不生效）' }}</pre>
                </div>
              </div>
              <ul v-if="compiledNotes.length" class="compiled-notes">
                <li v-for="(note, i) in compiledNotes" :key="`compiled-note-${i}`">{{ note }}</li>
              </ul>
              <ul v-if="compiledWarnings.length" class="compiled-notes warn">
                <li v-for="(warn, i) in compiledWarnings" :key="`compiled-warn-${i}`">{{ warn }}</li>
              </ul>
            </section>
          </div>

          <aside
            ref="promptSideEl"
            class="prompt-side"
            @scroll.passive="onPromptScroll"
          >
            <div class="side-head">
              <h3 class="side-heading">
                出图档案
                <span class="side-tag">{{ item.prompt_id ? '已关联提示词库' : '临时提示词' }}</span>
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
              <dl class="facts side-facts">
                <div
                  v-for="row in fileRows"
                  :key="row.label"
                  class="kv"
                  :class="{ wide: row.wide }"
                >
                  <dt>{{ row.label }}</dt>
                  <dd :title="row.title">{{ row.value }}</dd>
                </div>
                <div v-if="showFileActions" class="kv wide">
                  <dt>存储位置</dt>
                  <dd
                    class="path linkable"
                    :title="`在资源管理器中定位：${outputPath}`"
                    @click.stop="revealImage(item)"
                  >
                    {{ outputPath }}
                  </dd>
                </div>
              </dl>
            </section>

            <section class="side-block cleanup-block">
              <h3 class="side-title">后期清理</h3>
              <p class="prompt-tip">手动框选印章/文字并局部擦除，生成新图，不覆盖原图。</p>
              <div class="cleanup-actions">
                <button
                  class="btn btn-sm"
                  :disabled="busy"
                  @click="promptInfoOpen = false; manualCleanupOpen = true"
                >
                  框选清理
                </button>
              </div>
            </section>

            <section v-if="detailLoading" class="side-block">
              <span class="prompt-tip">正在汇总工作流与运行参数…</span>
            </section>

            <section v-if="workflowRows.length || jobRow" class="side-block">
              <h3 class="side-title">工作流与任务</h3>
              <dl class="facts side-facts">
                <div v-if="jobRow" class="kv wide">
                  <dt>任务</dt>
                  <dd :title="jobRow.title">{{ jobRow.text }}</dd>
                </div>
                <div
                  v-for="row in workflowRows"
                  :key="row.label"
                  class="kv"
                  :class="{ wide: row.wide }"
                >
                  <dt>{{ row.label }}</dt>
                  <dd :title="row.title">{{ row.value }}</dd>
                </div>
              </dl>
            </section>

            <section v-if="runParamRows.length" class="side-block">
              <h3 class="side-title">运行参数</h3>
              <dl class="facts side-facts">
                <div
                  v-for="row in runParamRows"
                  :key="row.label"
                  class="kv"
                  :class="{ wide: row.wide }"
                >
                  <dt>{{ row.label }}</dt>
                  <dd>{{ row.value }}</dd>
                </div>
              </dl>
            </section>

            <section v-if="referenceInputs.length" class="side-block">
              <h3 class="side-title">参考图</h3>
              <div class="ref-grid">
                <button
                  v-for="ref in referenceInputs"
                  :key="ref.path"
                  class="ref-card"
                  type="button"
                  :title="ref.path"
                  @click="openReferencePreview(ref)"
                >
                  <img
                    class="ref-thumb"
                    :src="referenceThumb(ref.path)"
                    :alt="ref.label"
                    loading="lazy"
                  />
                  <span class="ref-label">{{ ref.label }}</span>
                </button>
              </div>
            </section>

            <section v-if="extraRows.length" class="side-block">
              <h3 class="side-title">来源与输入</h3>
              <dl class="facts side-facts">
                <div
                  v-for="row in extraRows"
                  :key="row.label"
                  class="kv"
                  :class="{ wide: row.wide }"
                >
                  <dt>{{ row.label }}</dt>
                  <dd
                    v-if="row.promptId"
                    class="linkable"
                    :title="row.title"
                    @click.stop="jumpToPrompt(row.promptId!)"
                  >
                    {{ row.value }}
                  </dd>
                  <dd v-else :title="row.title">{{ row.value }}</dd>
                </div>
              </dl>
            </section>

            <p class="prompt-tip">
              <template v-if="item.prompt_id">
                这张图关联了提示词库记录；参数来自任务记录、出图参数快照与 ComfyUI 执行记录。
                提示词正文优先展示出图时的快照，缺失时回退到提示词库当前版本。
              </template>
              <template v-else>
                这张图没有关联提示词库记录；以上内容来自任务记录、出图参数快照与 ComfyUI 执行记录。
              </template>
            </p>
          </aside>
        </div>
      </div>
    </Modal>

    <ManualCleanupModal
      :open="manualCleanupOpen"
      :image-id="item?.id ?? 0"
      :image-url="item ? displayUrl(item) : ''"
      @close="manualCleanupOpen = false"
      @applied="onCleanupApplied"
    />
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
  background: rgb(0 0 0 / .72);
  backdrop-filter: blur(2px);
  transition: opacity var(--dur) var(--ease);
}

.bar {
  position: relative;
  z-index: 3;
  flex: none;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: var(--gap-sm) var(--gap);
  background: var(--panel);
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
  color: var(--accent-link);
}

.tool.primary {
  background: var(--primary);
  color: var(--text);
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

.stage-state {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--gap-sm);
  color: var(--muted);
  font-size: var(--fs-sm);
  pointer-events: none;
}

.stage-state.error {
  pointer-events: auto;
}

.stage-state.error .btn {
  pointer-events: auto;
}

/* Skeleton 根节点满宽、骨架条默认左对齐，居中容器里要显式居中 */
.stage-state.loading :deep(.skeleton) {
  align-items: center;
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
  background: var(--panel-2);
  color: var(--text);
  font-size: 26px;
  line-height: 1;
  z-index: 2;
}

.nav:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--accent-link);
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
  background: var(--panel);
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
  color: var(--accent-link);
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
  background: var(--panel-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.prompt-link:hover {
  border-color: var(--primary);
  color: var(--accent-link);
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
  color: var(--text);
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
  gap: var(--gap-sm);
}

/* 正向占满剩余高度；负面按内容高度（上限 30%），不再挤在右栏 */
.text-section {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.neg-section {
  flex: 0 1 auto;
  max-height: 30%;
}

.compiled-section {
  flex: 0 1 auto;
  max-height: 42%;
  overflow-y: auto;
}

.compiled-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--gap-sm);
}

.compiled-grid h4 {
  margin: 0 0 4px;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--muted);
}

.compiled-text {
  max-height: 160px;
  overflow-y: auto;
}

.compiled-notes {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--muted);
}

.compiled-notes.warn {
  color: var(--warn);
}

@media (max-width: 900px) {
  .compiled-grid {
    grid-template-columns: 1fr;
  }
}

.text-head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.text-note {
  color: var(--muted);
}

.text-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

/* 提示词名可能很长：入口本身给足点击宽度，但别把标题挤掉 */
.prompt-jump {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prompt-side {
  flex: none;
  /* 两列短字段需要的最小宽度；长字段（路径/模型）仍独占整行 */
  width: 440px;
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

/* 参考图缩略图：右栏宽度内自适应列数，点开看原图 */
.ref-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
  gap: var(--gap-sm);
}

.ref-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 0;
  border: 0;
  background: none;
  color: var(--text);
  font: inherit;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}

.ref-thumb {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.ref-card:hover .ref-thumb {
  border-color: var(--primary);
}

.ref-label {
  font-size: var(--fs-xs);
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 参考图放大预览：盖在档案弹窗之上，Esc / 点空白关闭 */
.ref-preview {
  position: fixed;
  inset: 0;
  z-index: 5;
  display: flex;
  flex-direction: column;
  background: rgb(0 0 0 / .88);
}

.ref-preview-bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}

.ref-preview-title {
  flex: none;
  font-size: var(--fs-sm);
  font-weight: 600;
}

.ref-preview-path {
  min-width: 0;
  font-size: var(--fs-xs);
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-preview-stage {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  cursor: grab;
  touch-action: none;
}

.ref-preview-stage:active {
  cursor: grabbing;
}

.ref-preview-img {
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

.ref-preview-img.loaded {
  opacity: 1;
}

.ref-preview-state {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--gap-sm);
  color: var(--muted);
  font-size: var(--fs-sm);
  pointer-events: none;
}

.ref-preview-state.error {
  pointer-events: auto;
}

/* 文件名：右栏里需要被一眼看到，放大加粗 */
.side-filename {
  font-size: var(--fs);
  font-weight: 700;
  line-height: 1.5;
  word-break: break-all;
}

.side-tag {
  margin-left: 6px;
  font-size: var(--fs-xs);
  font-weight: 400;
  color: var(--muted);
}

.linkable {
  cursor: pointer;
  color: var(--accent-link);
  text-decoration: underline dotted;
  text-underline-offset: 3px;
}

.linkable:hover {
  text-decoration-style: solid;
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

.side-filename.copyable {
  cursor: copy;
}

.side-filename.copyable:hover {
  color: var(--accent-link);
}

/* 短字段两列，长字段（路径 / 模型 / 文件名）由 .wide 独占整行 */
.side-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 14px;
  flex: none;
}

.side-facts .kv {
  display: flex;
  gap: 6px;
  min-width: 0;
  font-size: var(--fs-sm);
}

.side-facts .kv.wide {
  grid-column: 1 / -1;
}

.side-facts dt {
  flex: none;
  width: 58px;
  color: var(--muted);
}

.side-facts dd {
  margin: 0;
  min-width: 0;
  word-break: normal;
  overflow-wrap: anywhere;
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

/* 负面提示词在左栏底部，按内容高度、上限 30% */
.neg-prompt {
  flex: 0 1 auto;
  min-height: 0;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.prompt-tip {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--muted);
  line-height: 1.6;
}

.cleanup-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--gap-sm);
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

@media (max-width: 560px) {
  .side-facts {
    grid-template-columns: 1fr;
  }

  .side-facts .kv {
    grid-column: 1 / -1;
  }

  .prompt-jump {
    max-width: 150px;
  }
}
</style>
