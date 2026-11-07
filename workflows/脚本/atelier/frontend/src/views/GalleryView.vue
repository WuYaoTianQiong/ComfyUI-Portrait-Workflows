<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useRoute, useRouter } from 'vue-router'

import Lightbox from '../components/Lightbox.vue'
import CompareModal from '../components/CompareModal.vue'
import Modal from '../components/Modal.vue'
import GalleryFilterSidebar from '../components/GalleryFilterSidebar.vue'
import GalleryGrid from '../components/GalleryGrid.vue'
import { apiPost } from '../api/client'
import {
  backfillImageTaxonomy,
  batchDeleteImages,
  cleanupMissingImages,
  getImageFacets,
  listImageIds,
  listImages,
  setImageFavorite,
  syncImagesLight,
} from '../api/images'
import { listCategories, listTags } from '../api/taxonomy'
import { useToast } from '../composables/useToast'
import { useWorkflows } from '../composables/useWorkflows'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { useGenerate } from '../composables/useGenerate'
import { findHistoryItem } from '../composables/useImagePreview'
import { useSettings } from '../composables/useSettings'
import { useWorkflowQuality } from '../composables/useWorkflowQuality'
import { useWorkflowAspectRatio } from '../composables/useWorkflowAspectRatio'
import { useImageLocation } from '../composables/useImageLocation'
import { useGallerySelection } from '../composables/useGallerySelection'
import type { HistoryItem, HistoryPage, ImageFacets } from '../api/types'
import { flattenCategories } from '../utils/categories'

import { confirmDialog, confirmDialogWithCheckbox } from '../utils/naive'
import { CONFIRM_PROMPTS } from '../utils/confirmKeys'
import { readSession, writeSession } from '../composables/useSessionState'

/**
 * 会话状态：筛选 / 排序 / 页码 / 滚动位置。
 *
 * 切页或刷新后回到上次看到的那一屏；`pb.gallerySidebar` 只管侧栏开合。
 */
interface GallerySession {
  page: number
  pageSize: number
  sortBy: string
  search: string
  categoryId: number | null
  selectedTags: number[]
  tagMatch: 'all' | 'any'
  onlyMissing: boolean
  source: string
  dateFacet: string
  model: string
  orientation: string
  scrollTop: number
  /** 卡片密度：紧凑 / 标准（纯展示偏好，不影响筛选与分页）。 */
  density: 'standard' | 'compact'
  /** 刷新后要恢复的灯箱图片 id（null = 灯箱当时没开）。 */
  viewerId?: number | null
}

const SESSION_KEY = 'pb.session.gallery'
const savedSession = readSession<GallerySession>(SESSION_KEY, {
  page: 1,
  pageSize: 60,
  sortBy: 'newest',
  search: '',
  categoryId: null,
  selectedTags: [],
  tagMatch: 'all',
  onlyMissing: false,
  source: '',
  dateFacet: '',
  model: '',
  orientation: '',
  scrollTop: 0,
  density: 'standard',
  viewerId: null,
})

const pageSize = ref(savedSession.pageSize)
const sortBy = ref(savedSession.sortBy)
const page = ref(savedSession.page)
const search = ref(savedSession.search)
const categoryId = ref<number | null>(savedSession.categoryId)
const selectedTags = ref<number[]>(savedSession.selectedTags)
const tagMatch = ref<'all' | 'any'>(savedSession.tagMatch)
const onlyMissing = ref(savedSession.onlyMissing)

// 分面筛选（来源 / 年月 / 模型 / 方向）—— 每个维度单选，再点一次取消
const source = ref(savedSession.source)
const dateFacet = ref(savedSession.dateFacet)
const model = ref(savedSession.model)
const orientation = ref(savedSession.orientation)

/** 卡片密度：默认标准，紧凑档缩小列宽与间距。 */
const density = ref<'standard' | 'compact'>(savedSession.density ?? 'standard')
const skeletonCount = computed(() => (density.value === 'compact' ? 18 : 10))

function setDensity(value: 'standard' | 'compact') {
  density.value = value
}

/**
 * 侧栏折叠：低频分面不该常驻吃掉 240px，折叠状态记在本机。
 * 新键 `pb.gallery_sidebar_v1`；旧键 `pb.gallerySidebar` 只在无新键时只读回落
 * （旧键不删、不再写入，保证老用户的折叠偏好仍然生效）。
 */
const SIDEBAR_KEY = 'pb.gallery_sidebar_v1'
const LEGACY_SIDEBAR_KEY = 'pb.gallerySidebar'
const sidebarOpen = ref(true)
try {
  const saved = localStorage.getItem(SIDEBAR_KEY)
  if (saved === '1' || saved === '0') {
    sidebarOpen.value = saved === '1'
  } else {
    sidebarOpen.value = localStorage.getItem(LEGACY_SIDEBAR_KEY) !== '0'
  }
} catch {
  /* 隐私模式下保持默认展开 */
}

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value
  try {
    localStorage.setItem(SIDEBAR_KEY, sidebarOpen.value ? '1' : '0')
  } catch {
    /* 忽略 */
  }
}

/** 当前生效的筛选数量（折叠侧栏时提示用户"还有筛选在生效"）。 */
const filterBadge = computed(
  () =>
    (categoryId.value ? 1 : 0) +
    (selectedTags.value.length ? 1 : 0) +
    (source.value ? 1 : 0) +
    (dateFacet.value ? 1 : 0) +
    (model.value ? 1 : 0) +
    (orientation.value ? 1 : 0) +
    (onlyMissing.value ? 1 : 0) +
    (search.value.trim() ? 1 : 0),
)

const queryClient = useQueryClient()

/**
 * 列表状态全部收敛成"一个缓存键"。
 *
 * 旧前端把分页/筛选/排序拆在十几个 `window._galleryXxx` 裸变量里，
 * 任何一处漏同步就是"筛选筛了、全选选到范围外"。这里键变了就重查，
 * 键没变就用缓存，不存在两边不同步的可能。
 */
const historyKey = computed(() => [
  'history',
  page.value,
  pageSize,
  sortBy.value,
  categoryId.value,
  selectedTags.value.slice().sort((a, b) => a - b).join(','),
  tagMatch.value,
  onlyMissing.value,
  search.value.trim(),
  source.value,
  dateFacet.value,
  model.value,
  orientation.value,
])

/** 排序变了要回到第 1 页：停在第 3 页看新顺序没有意义。 */
watch(sortBy, () => {
  if (page.value !== 1) page.value = 1
})

/** 列表与「全选全部」共用的筛选参数（后者不需要分页参数）。 */
function historyFilterParams() {
  return {
    page: page.value,
    page_size: pageSize.value,
    sort: sortBy.value,
    category_id: categoryId.value ?? undefined,
    tag_ids: selectedTags.value.join(','),
    tag_match: tagMatch.value,
    missing: onlyMissing.value ? 1 : undefined,
    search: search.value.trim(),
    source: source.value,
    date: dateFacet.value,
    model: model.value,
    orientation: orientation.value,
  }
}
/** 列表与分面共用的筛选参数（不含分面维度自身 —— 后端就是按这个口径算的）。 */
const facetScope = computed(() => ({
  search: search.value.trim(),
  category_id: categoryId.value ?? undefined,
  tag_ids: selectedTags.value.join(','),
  tag_match: tagMatch.value,
  missing: onlyMissing.value ? 1 : undefined,
}))

const {
  data: history,
  isFetching,
  isError,
  error,
} = useQuery<HistoryPage>({
  queryKey: historyKey,
  queryFn: () => listImages(historyFilterParams()),
  // 翻页时保留上一页内容，避免整页闪烁
  placeholderData: (prev) => prev,
})

/** 分面计数：后端按「当前筛选（不含分面维度自身）」算，避免「数出来的和筛出来的对不上」。 */
const { data: facets } = useQuery<ImageFacets>({
  queryKey: computed(() => ['facets', facetScope.value]),
  queryFn: () => getImageFacets(facetScope.value),
  placeholderData: (prev) => prev,
  staleTime: 15_000,
})

const { data: tagData } = useQuery({
  queryKey: ['tags', 'image'],
  queryFn: () => listTags({ count_scope: 'image' }),
})

const { data: catData } = useQuery({
  queryKey: ['categories', 'gallery'],
  queryFn: () => listCategories({ tree: true, count_scope: 'image' }),
})

const items = computed<HistoryItem[]>(() => history.value?.items ?? [])
const total = computed(() => history.value?.total ?? 0)

/**
 * 深链（`/gallery?image=<文件名>`）：组合器 / 任务页点「在画廊中查看」过来。
 *
 * 不覆盖当前筛选、也不往网格里塞一张不属于本页的卡片 —— 单独取那条记录
 * 交给灯箱，取不到就提示（图还没入库）。看完关闭即回到正常画廊。
 */
const route = useRoute()
const router = useRouter()
const deepLinkItem = ref<HistoryItem | null>(null)
/** 灯箱的数据源：深链那张单图，或当前网格这一页。 */
const viewerItems = computed<HistoryItem[]>(() =>
  deepLinkItem.value ? [deepLinkItem.value] : items.value,
)


const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

const gridEl = ref<HTMLElement | null>(null)
let scrollSaveTimer: number | undefined

function saveSession() {
  writeSession(SESSION_KEY, {
    page: page.value,
    pageSize: pageSize.value,
    sortBy: sortBy.value,
    search: search.value,
    categoryId: categoryId.value,
    selectedTags: selectedTags.value,
    tagMatch: tagMatch.value,
    onlyMissing: onlyMissing.value,
    source: source.value,
    dateFacet: dateFacet.value,
    model: model.value,
    orientation: orientation.value,
    density: density.value,
    scrollTop: gridEl.value?.scrollTop ?? savedSession.scrollTop,
    viewerId:
      lightboxIndex.value !== null ? (viewerItems.value[lightboxIndex.value]?.id ?? null) : null,
  })
}

watch(
  () =>
    [
      page.value,
      pageSize.value,
      sortBy.value,
      search.value,
      categoryId.value,
      selectedTags.value.join(','),
      tagMatch.value,
      onlyMissing.value,
      source.value,
      dateFacet.value,
      model.value,
      orientation.value,
      density.value,
    ].join('|'),
  saveSession,
)

/** 滚动很频繁，节流后再写。 */
function onGridScroll() {
  if (scrollSaveTimer) return
  scrollSaveTimer = window.setTimeout(() => {
    scrollSaveTimer = undefined
    saveSession()
  }, 300)
}

/** 图片加载完成前网格高度还会变，恢复要等这一页数据到位。 */
let scrollRestored = false
let viewerRestored = false
watch(items, async () => {
  // 刷新后回到上次打开的那张图（按 id 找，不依赖页码下标）
  if (!viewerRestored && savedSession.viewerId) {
    viewerRestored = true
    const idx = items.value.findIndex((it) => it.id === savedSession.viewerId)
    if (idx >= 0) lightboxIndex.value = idx
    else saveSession()
  }
  if (scrollRestored || !savedSession.scrollTop) return
  scrollRestored = true
  await nextTick()
  if (gridEl.value) gridEl.value.scrollTop = savedSession.scrollTop
})

/** 深链进来时优先展示那张图，别被会话里"上次开着的灯箱"抢走。 */
watch(
  () => route.query.image,
  async (filename) => {
    if (typeof filename !== 'string' || !filename) return
    // 用完即抹掉：否则刷新、返回都会再次触发，且没法回到普通画廊地址
    router.replace({ path: '/gallery' })
    try {
      const hit = await findHistoryItem({ filename })
      if (!hit) {
        toast.info('这张图还没入库，暂时无法在画廊中查看')
        return
      }
      viewerRestored = true
      deepLinkItem.value = hit
      lightboxIndex.value = 0
    } catch (e) {
      toast.error(`打开图片失败：${e instanceof Error ? e.message : String(e)}`)
    }
  },
  { immediate: true },
)

/** 关闭灯箱时把深链那张单图放掉，回到正常网格。 */
function closeLightbox() {
  lightboxIndex.value = null
  deepLinkItem.value = null
}

onBeforeUnmount(() => {
  if (scrollSaveTimer) window.clearTimeout(scrollSaveTimer)
  saveSession()
})

// ---------------- 选择与批量操作 ----------------

const {
  selected,
  selectedCount,
  toggle: toggleSelect,
  selectAll,
  selectPage: selectAllOnPage,
  clear: clearSelection,
} = useGallerySelection(() => items.value.map((it) => it.id))
const selectingAll = ref(false)

/**
 * 全选全部：跨页把当前筛选下的所有记录都选上。
 *
 * 后端 `/api/images/ids` 不分页，返回当前筛选下的全部 id —— 旧前端的"全选全部"
 * 就是这个语义，新前端之前只支持"全选本页"，批量删除时得翻页累加。
 */
async function selectAllMatching() {
  selectingAll.value = true
  try {
    const data = await listImageIds(historyFilterParams())
    selectAll(data.ids)
    if (!data.ids.length) toast.info('当前筛选下没有可选的图片')
  } catch (e) {
    toast.error(`全选失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    selectingAll.value = false
  }
}

const deleteMutation = useMutation({
  mutationFn: (payload: { ids: number[]; deleteFiles: boolean }) =>
    batchDeleteImages(payload.ids, payload.deleteFiles),
  onSuccess: (data, payload) => {
    clearSelection()
    queryClient.invalidateQueries({ queryKey: ['history'] })
    // 删除后分面计数会变，不刷的话侧栏数字停在旧值
    queryClient.invalidateQueries({ queryKey: ['facets'] })
    // 勾了「同时删文件」但部分原图已经不在磁盘上时，明确告知实际删掉了几个
    if (payload.deleteFiles) {
      toast.info(`已删除 ${data.deleted} 条记录，清理磁盘文件 ${data.files_deleted ?? 0} 个`)
    }
  },
})

const favoriteMutation = useMutation({
  mutationFn: setImageFavorite,
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['history'] })
    queryClient.invalidateQueries({ queryKey: ['facets'] })
  },
})

async function batchDelete() {
  const ids = Array.from(selected.value)
  if (!ids.length) return
  const { confirmed, checked } = await confirmDialogWithCheckbox({
    title: '删除图片记录',
    content: `确定删除选中的 ${ids.length} 张图片记录吗？`,
    checkboxLabel: '同时删除磁盘上的原图文件（不可恢复）',
    // 勾选态跨弹窗记忆：上次勾过就默认勾上（见 useSettings.deleteFiles）
    defaultChecked: deleteFiles.value,
    positiveText: '删除',
    negativeText: '取消',
  })
  // 无论确认还是取消，都记住这次的选择，下次打开还是这个样子
  deleteFiles.value = checked
  if (!confirmed) return
  deleteMutation.mutate({ ids, deleteFiles: checked })
}

function batchDownload() {
  const targets = items.value.filter((it) => selected.value.has(it.id))
  if (!targets.length) return
  // 浏览器对并发下载有限制，逐个触发并留间隔
  targets.forEach((item, i) => {
    setTimeout(() => window.open(`/api/images/${item.id}/download`, '_blank'), i * 400)
  })
}

// ---------------- 灯箱 ----------------


/**
 * 多图对比：选中 2~4 张后打开对比弹层。
 *
 * 上限 4 张是旧版沿用的限制 —— 再多就没法看了，用户也不需要。
 */
const compareOpen = ref(false)

const compareItems = computed<HistoryItem[]>(() =>
  items.value.filter((it) => selected.value.has(it.id)),
)

function openCompare() {
  if (selected.value.size < 2) {
    toast.info('至少选择 2 张图片才能对比')
    return
  }
  if (selected.value.size > 4) {
    toast.error('对比最多只能选择 4 张图片，请取消部分选择')
    return
  }
  compareOpen.value = true
}

/**
 * 用这张图的提示词重新出图（旧版灯箱里的 🔄）。
 *
 * 走统一的出图入口 useGenerate.run —— 同样的工作流/画质/画幅设置，
 * 进度照旧用 SSE 跟踪。
 */
const { workflowPath, orientation: outOrientation, deleteFiles, outputSubfolder } = useSettings()
const quality = useWorkflowQuality(workflowPath)
const aspectRatio = useWorkflowAspectRatio(workflowPath)
const { revealImage } = useImageLocation()
const { run, runText, busy: regenerating, error: generateError } = useGenerate()

/**
 * 用这张图的记录重新出图。
 *
 * 两条路：
 * - 有 `prompt_id` → `/api/runs`，出图关联回那条提示词
 * - 没有 `prompt_id`（同步进来的图）→ 用 `prompt_params` 里存的文本与参数走
 *   `/api/runs/text`。记录里参数是全的（prompt / seed / model / 宽高），所以
 *   「拿这张图再出一版」不需要先有提示词记录。
 */
async function regenerate(target: HistoryItem) {
  const params = (target.prompt_params ?? {}) as Record<string, unknown>
  try {
    if (target.prompt_id) {
      await run(target.prompt_id, {
        workflowPath: workflowPath.value,
        quality: caps.value.quality ? quality.value : '1.0x',
        orientation: caps.value.orientation ? outOrientation.value : 'keep',
        aspectRatio: aspectRatio.value || defaultRatio.value,
      })
    } else if (typeof params.prompt === 'string' && params.prompt.trim()) {
      await runText({
        prompt: params.prompt,
        negative_prompt: typeof params.negative_prompt === 'string' ? params.negative_prompt : '',
        seed: Number(params.seed) || null,
        workflowPath: workflowPath.value,
        quality: caps.value.quality ? quality.value : '1.0x',
        orientation: caps.value.orientation ? outOrientation.value : 'keep',
        aspectRatio: aspectRatio.value || defaultRatio.value,
      })
    } else {
      toast.error('这张图没有可复用的出图参数')
      return
    }
    // 提交完才关灯箱：期间按钮转圈，关掉后也有 toast，不会出现"点了没反应"
    if (generateError.value) toast.error(`提交失败：${generateError.value}`)
    else toast.success('已提交重新出图，可在「任务」页看进度')
  } finally {
    closeLightbox()
  }
}
/** 画廊向上层抛的事件：跨页跳转（跳到提示词）。 */
const emit = defineEmits<{
  (e: 'jump-to-prompt', promptId: number): void
}>()

/**
 * 批量给选中的图片打标签 / 分类（旧版 bulkAddTag / bulkAddCategory）。
 *
 * 后端只有单张的关联端点（`/api/images/{id}/tags/{tag_id}`），批量就是循环调用；
 * 逐张独立处理，某张失败不影响其它。
 */
const bulkOpen = ref(false)
const bulkTagId = ref<number | null>(null)
const bulkCatId = ref<number | null>(null)
const bulkBusy = ref(false)

const { data: bulkTags } = useQuery({
  queryKey: ['tags', 'bulk'],
  queryFn: () => listTags({ count_scope: 'image' }),
  enabled: computed(() => bulkOpen.value),
})

const { data: bulkCats } = useQuery({
  queryKey: ['categories', 'bulk'],
  queryFn: () => listCategories({ tree: true }),
  enabled: computed(() => bulkOpen.value),
})

const bulkCatList = computed(() => flattenCategories(bulkCats.value?.categories))


/** 批量投喂工作流用：要套哪个工作流。 */
const bulkWf = ref('')

/**
 * 批量把选中的图片投喂给工作流处理（超分 / 重绘等）。
 *
 * 与灯箱里的单张投喂同一个端点 `/api/images/{id}/process`，只是循环调用。
 */
async function applyProcess() {
  if (!bulkWf.value) {
    toast.error('请先选择工作流')
    return
  }
  await applyBulk('/api/images/{id}/process', '处理', {
    workflow_path: bulkWf.value,
    output_subfolder: outputSubfolder.value,
  })
}

/**
 * 批量继承来源分类：把图片对应提示词上的标签/分类继承过来。
 *
 * 同步进来的图片常常没有分类/标签（prompt_id 是空的），继承不了 ——
 * 这种图点了会返回 0，正常。
 */
async function applyInherit() {
  await applyBulk('/api/images/{id}/inherit', '继承分类')
}

/** 一次性给全库缺分类/标签的图片补齐。 */
async function backfillTaxonomy() {
  const ok = await confirmDialog({
    title: '补齐分类 / 标签',
    content: '为所有缺少分类/标签的图片补齐（一次性全库操作，可能要跑一会儿）。继续？',
    positiveText: '开始',
    negativeText: '取消',
    rememberKey: CONFIRM_PROMPTS.backfillTaxonomy.key,
  })
  if (!ok) return
  try {
    const result = await backfillImageTaxonomy()
    toast.success(`已补齐 ${result.backfilled} 张图片的分类/标签`)
    queryClient.invalidateQueries({ queryKey: ['history'] })
    queryClient.invalidateQueries({ queryKey: ['tags'] })
    queryClient.invalidateQueries({ queryKey: ['categories'] })
  } catch (e) {
    toast.error(`补齐失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
async function applyBulkTag() {
  if (!bulkTagId.value) return
  await applyBulk(`/api/images/{id}/tags/${bulkTagId.value}`, '标签')
}

async function applyBulkCat() {
  if (!bulkCatId.value) return
  await applyBulk(`/api/images/{id}/categories/${bulkCatId.value}`, '分类')
}

async function applyBulk(pathTemplate: string, label: string, body?: Record<string, unknown>) {
  bulkBusy.value = true
  const ids = Array.from(selected.value)
  let ok = 0
  let failed = 0
  for (const id of ids) {
    try {
      await apiPost(pathTemplate.replace('{id}', String(id)), body)
      ok++
    } catch {
      failed++
    }
  }
  bulkBusy.value = false
  bulkOpen.value = false
  bulkTagId.value = null
  bulkCatId.value = null
  if (failed) {
    toast.error(`已给 ${ok} 张图片打上${label}，${failed} 张失败`)
  } else {
    toast.success(`已给 ${ok} 张图片打上${label}`)
  }
  queryClient.invalidateQueries({ queryKey: ['history'] })
}
const lightboxIndex = ref<number | null>(null)
// 打开/关闭灯箱都写进会话，刷新后按 id 恢复
watch(lightboxIndex, saveSession)

/** 灯箱里要能直接选工作流（投喂给工作流处理）。 */
const { workflows, allWorkflows } = useWorkflows()
/** 重跑用的是提示词页的工作流；不支持画质/横竖时不发无效参数。 */
const { caps, defaultRatio } = useWorkflowCaps(workflowPath, allWorkflows, aspectRatio)
const lightboxOpen = computed(() => lightboxIndex.value !== null)

function openLightbox(index: number) {
  deepLinkItem.value = null
  lightboxIndex.value = index
}

// ---------------- 筛选 ----------------

function toggleTag(id: number) {
  const idx = selectedTags.value.indexOf(id)
  if (idx >= 0) selectedTags.value.splice(idx, 1)
  else selectedTags.value.push(id)
  page.value = 1
}

function setTagMatch(mode: 'all' | 'any') {
  if (tagMatch.value === mode) return
  tagMatch.value = mode
  page.value = 1
}

function toggleMissing() {
  onlyMissing.value = !onlyMissing.value
  page.value = 1
}

// ---------------- 清理失效 ----------------

const toast = useToast()

const syncing = ref(false)

/**
 * 扫描本地 output 目录，把新图补进库。
 *
 * 页面加载/点刷新时各跑一次增量扫描：新图不再需要等后台每 30 秒的定时同步。
 * 只有确实新增了记录才重拉列表，避免每次进画廊都多一次请求。
 */
async function syncNewImages(showToast = false) {
  if (syncing.value) return
  syncing.value = true
  try {
    const result = await syncImagesLight()
    if (result.added > 0) {
      // 手动刷新发现新图时回到第 1 页，否则用户停在旧页码看不到它们
      if (showToast && page.value !== 1) page.value = 1
      queryClient.invalidateQueries({ queryKey: ['history'] })
      queryClient.invalidateQueries({ queryKey: ['facets'] })
      if (showToast) toast.success(`发现 ${result.added} 张新图`)
    } else if (showToast) {
      toast.info(result.busy ? '后台正在扫描，请稍后再试' : '没有发现新图')
    }
  } catch (e) {
    if (showToast) {
      toast.error(`刷新失败：${e instanceof Error ? e.message : String(e)}`)
    }
  } finally {
    syncing.value = false
  }
}

onMounted(() => {
  void syncNewImages(false)
})

/** 图片文件名点击复制。 */
async function copyFilename(name: string) {
  try {
    await navigator.clipboard.writeText(name)
    toast.success('已复制文件名')
  } catch {
    toast.error('复制失败（浏览器拒绝了剪贴板访问）')
  }
}
const cleaning = ref(false)

/**
 * 清理范围 = 当前筛选，但**刻意不传 missing**。
 *
 * 「只看文件缺失」是"看待清理的清单"，不是"清理范围"；带上它预览恒为 0，
 * 用户会以为功能坏了。
 */
function cleanupScope() {
  return {
    search: search.value.trim(),
    tag_ids: selectedTags.value.join(','),
    tag_match: tagMatch.value,
  }
}

/**
 * 两段式：先预览再执行。
 *
 * 后端默认 dry_run，只返回"将清理多少条 + 样本"，不写库；执行要显式带
 * dry_run=false&confirm=true。缺失占比过半时后端会熔断拒绝（路径解析异常时
 * 一键清空整库是历史事故的根源）。
 */
async function cleanupMissing() {
  if (cleaning.value) return
  cleaning.value = true
  try {
    const preview = await cleanupMissingImages(cleanupScope(), { dryRun: true })

    if (preview.guarded) {
      toast.error(preview.message || '疑似路径异常，已阻止清理')
      return
    }
    if (!preview.will_clean) {
      toast.info(`扫描 ${preview.total} 条记录，文件均存在，无需清理`)
      return
    }

    const samples = preview.samples
      .map((s) => `  · ${s.subfolder ? s.subfolder + '/' : ''}${s.filename}`)
      .join('\n')
    const more = preview.will_clean > 10 ? `\n  … 另有 ${preview.will_clean - 10} 条` : ''
    const allMissing = preview.total > 0 && preview.will_clean === preview.total
    const warn = allMissing
      ? '\n\n⚠ 当前筛选下的记录会【全部】失效，请先确认 ComfyUI output 目录可正常访问。'
      : ''

    const ok = await confirmDialog({
      title: '清理失效记录',
      content:
        `扫描 ${preview.total} 条记录，其中 ${preview.will_clean} 条的文件已不存在：\n\n` +
        `${samples}${more}${warn}` +
        '\n\n这一步只把记录标记为已删除，不动磁盘文件。确认继续？',
      positiveText: '清理',
      negativeText: '取消',
    })
    if (!ok) return

    const data = await cleanupMissingImages(cleanupScope(), { dryRun: false })
    if (!data.success) {
      toast.error(data.message || '清理未执行')
      return
    }
    toast.success(`已清理 ${data.cleaned ?? 0} 条失效记录（共扫描 ${data.total} 条）`)
    queryClient.invalidateQueries({ queryKey: ['history'] })
  } catch (e) {
    toast.error(`清理失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    cleaning.value = false
  }
}

function toggleFacet(key: 'source' | 'date' | 'model' | 'orientation', value: string) {
  const targets = { source, date: dateFacet, model, orientation }
  const target = targets[key]
  target.value = target.value === value ? '' : value
  page.value = 1
}

function onCategoryChange(value: number | null) {
  categoryId.value = value
  page.value = 1
  clearSelection()
}
function clearFilters() {
  selectedTags.value = []
  categoryId.value = null
  tagMatch.value = 'all'
  onlyMissing.value = false
  search.value = ''
  page.value = 1
}
</script>

<template>
  <div class="gallery">
    <GalleryFilterSidebar
      :open="sidebarOpen"
      :filter-badge="filterBadge"
      :total="total"
      :categories="catData?.categories"
      :category-id="categoryId"
      :tags="tagData?.tags ?? []"
      :selected-tags="selectedTags"
      :tag-match="tagMatch"
      :only-missing="onlyMissing"
      :facets="facets"
      :source="source"
      :date-facet="dateFacet"
      :model="model"
      :orientation="orientation"
      @toggle-sidebar="toggleSidebar"
      @select-category="onCategoryChange"
      @toggle-tag="toggleTag"
      @update:tag-match="setTagMatch"
      @toggle-missing="toggleMissing"
      @clear-tags="selectedTags = []; page = 1"
      @clear-filters="clearFilters"
      @toggle-facet="toggleFacet"
    />

    <section class="main">
      <div class="toolbar">
        <button
          class="btn btn-sm"
          :class="{ on: sidebarOpen }"
          :title="sidebarOpen ? '收起筛选侧栏' : '展开筛选侧栏'"
          @click="toggleSidebar"
        >
          ☰ 筛选<span v-if="!sidebarOpen && filterBadge"> · {{ filterBadge }}</span>
        </button>
        <input
          v-model="search"
          class="search"
          type="search"
          placeholder="搜索文件名 / 提示词名称…"
          @input="page = 1"
        />
        <span class="count">
          共 <b>{{ total }}</b> 张
          <span v-if="isFetching" class="fetching">加载中…</span>
        </span>
        <span class="spacer" />
        <div class="density" role="group" aria-label="卡片密度">
          <button
            class="btn btn-sm"
            :class="{ active: density === 'compact' }"
            title="紧凑排列（更多列）"
            @click="setDensity('compact')"
          >
            紧凑
          </button>
          <button
            class="btn btn-sm"
            :class="{ active: density === 'standard' }"
            title="标准排列"
            @click="setDensity('standard')"
          >
            标准
          </button>
        </div>
        <button
          class="btn btn-sm"
          :disabled="syncing"
          title="扫描本地 output 目录，加载新图"
          @click="syncNewImages(true)"
        >
          {{ syncing ? '刷新中…' : '刷新' }}
        </button>
        <select v-model="sortBy" class="mini-select" title="排序">
          <option value="newest">最新优先</option>
          <option value="oldest">最旧优先</option>
          <option value="res_desc">分辨率 大→小</option>
          <option value="res_asc">分辨率 小→大</option>
          <option value="size_desc">体积 大→小</option>
          <option value="size_asc">体积 小→大</option>
        </select>
        <select v-model.number="pageSize" class="mini-select" title="每页条数">
          <option :value="30">30 / 页</option>
          <option :value="60">60 / 页</option>
          <option :value="120">120 / 页</option>
        </select>
        <button
          class="btn btn-sm"
          :disabled="selectingAll"
          title="选中当前筛选下的全部图片（跨页）"
          @click="selectAllMatching"
        >
          全选全部 {{ total }} 张
        </button>
        <button
          class="btn btn-sm"
          :disabled="cleaning"
          title="扫描当前筛选下的记录，先预览再确认；只标记不动磁盘文件"
          @click="cleanupMissing"
        >
          🧹 清理失效
        </button>
        <div class="pager">
          <button class="btn btn-sm" :disabled="page <= 1" @click="page--">上一页</button>
          <span class="page-num">{{ page }} / {{ totalPages }}</span>
          <button class="btn btn-sm" :disabled="page >= totalPages" @click="page++">
            下一页
          </button>
        </div>
      </div>

      <div v-if="selectedCount" class="bulk">
        <span class="bulk-count">已选 <b>{{ selectedCount }}</b> 张</span>
        <button class="btn btn-sm" @click="selectAllOnPage">全选本页</button>
        <button class="btn btn-sm" @click="clearSelection">取消选择</button>
        <span class="spacer" />
        <button class="btn btn-sm" @click="openCompare">对比</button>
        <button class="btn btn-sm" @click="bulkOpen = true">打标签/分类</button>
        <button class="btn btn-sm" title="为全库缺少分类/标签的图片补齐" @click="backfillTaxonomy">
          补齐全库分类
        </button>
        <button class="btn btn-sm" @click="batchDownload">下载选中</button>
        <button class="btn btn-sm danger" :disabled="deleteMutation.isPending.value" @click="batchDelete">
          {{ deleteMutation.isPending.value ? '删除中…' : '删除选中' }}
        </button>
      </div>

      <div v-if="isError" class="error">加载失败：{{ error?.message }}</div>

      <div v-else ref="gridEl" class="grid" @scroll.passive="onGridScroll">
        <GalleryGrid
          :items="items"
          :is-fetching="isFetching"
          :density="density"
          :skeleton-count="skeletonCount"
          :selected="selected"
          @open="openLightbox"
          @toggle-select="toggleSelect"
          @favorite="favoriteMutation.mutate"
          @locate="revealImage"
          @copy-filename="copyFilename"
        />
      </div>
    </section>

    <Transition name="lightbox-fade">
      <Lightbox
        v-if="lightboxOpen"
        :items="viewerItems"
        :index="lightboxIndex!"
        :workflows="workflows"
        :regenerating="regenerating"
        @update:index="lightboxIndex = $event"
        @close="closeLightbox"
        @regenerate="regenerate"
        @jump-to-prompt="(id) => { closeLightbox(); emit('jump-to-prompt', id) }"
        @changed="queryClient.invalidateQueries({ queryKey: ['history'] })"
      />
    </Transition>

    <CompareModal
      :open="compareOpen"
      :items="compareItems"
      @close="compareOpen = false"
    />

    <Modal :open="bulkOpen" title="批量打标签 / 分类" @close="bulkOpen = false">
      <div class="bulk-body">
        <div class="bulk-row">
          <span class="bulk-label">标签</span>
          <select v-model="bulkTagId" class="bulk-select">
            <option :value="null">选择标签…</option>
            <option v-for="t in bulkTags?.tags ?? []" :key="t.id" :value="t.id">
              {{ t.name }}
            </option>
          </select>
          <button class="btn btn-sm" :disabled="bulkBusy || !bulkTagId" @click="applyBulkTag">
            应用到选中的 {{ selectedCount }} 张
          </button>
        </div>
        <div class="bulk-row">
          <span class="bulk-label">继承</span>
          <span class="bulk-hint">把来源提示词的分类/标签继承到选中的图片上</span>
          <button class="btn btn-sm" :disabled="bulkBusy" @click="applyInherit">
            继承分类
          </button>
        </div>
        <div class="bulk-row">
          <span class="bulk-label">处理</span>
          <select v-model="bulkWf" class="bulk-select">
            <option value="">选择工作流…</option>
            <option v-for="wf in workflows ?? []" :key="wf.path" :value="wf.path">
              {{ wf.name }}
            </option>
          </select>
          <button class="btn btn-sm" :disabled="bulkBusy || !bulkWf" @click="applyProcess">
            投喂处理
          </button>
        </div>
        <div class="bulk-row">
          <span class="bulk-label">分类</span>
          <select v-model="bulkCatId" class="bulk-select">
            <option :value="null">选择分类…</option>
            <option v-for="cat in bulkCatList" :key="cat.id" :value="cat.id">
              {{ cat.name }}
            </option>
          </select>
          <button class="btn btn-sm" :disabled="bulkBusy || !bulkCatId" @click="applyBulkCat">
            应用到选中的 {{ selectedCount }} 张
          </button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<style scoped>
.gallery {
  display: flex;
  height: 100%;
  min-height: 0;
}

.mini-select {
  width: auto;
  padding: 2px 6px;
  font-size: var(--fs-xs);
}


.bulk-body {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-lg);
}

.bulk-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.bulk-label {
  width: 40px;
  flex: none;
  font-size: var(--fs-sm);
  color: var(--muted);
}

.bulk-hint {
  flex: 1;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.bulk-select {
  flex: 1;
  min-width: 0;
}
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--gap);
  padding: var(--gap) var(--gap-lg);
  border-bottom: 1px solid var(--border);
}

.toolbar .on {
  color: var(--primary);
}

.search {
  width: 260px;
}

.count {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.count b {
  color: var(--text);
}

.fetching {
  margin-left: var(--gap-sm);
  color: var(--primary);
}

.spacer {
  flex: 1;
}

.pager {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}

.page-num {
  font-size: var(--fs-sm);
  color: var(--muted);
  min-width: 62px;
  text-align: center;
}

.bulk {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap-lg);
  background: var(--primary-soft);
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.bulk-count b {
  color: var(--primary);
}

.btn.danger {
  border-color: var(--danger);
  color: var(--text);
}

.btn.danger:hover {
  background: var(--danger-soft);
}

.grid {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap-lg);
}

.density {
  display: flex;
  gap: var(--gap-xs);
  flex: none;
}

.empty {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.lightbox-fade-enter-active,
.lightbox-fade-leave-active {
  transition: opacity var(--dur) var(--ease);
}

.lightbox-fade-enter-from,
.lightbox-fade-leave-to {
  opacity: 0;
}

.empty.big {
  grid-column: 1 / -1;
  padding: 60px;
  text-align: center;
}

.error {
  margin: var(--gap-lg);
  padding: var(--gap);
  border-radius: var(--radius);
  border: 1px solid var(--danger);
  color: var(--text);
  background: var(--danger-soft);
}
</style>
