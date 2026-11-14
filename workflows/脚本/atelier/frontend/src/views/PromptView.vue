<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useRoute, useRouter } from 'vue-router'

import MissingImageRunPanel from '../components/MissingImageRunPanel.vue'
import PromptTrialPanel from '../components/PromptTrialPanel.vue'
import Icon from '../components/Icon.vue'
import PromptCreateModal from '../components/PromptCreateModal.vue'
import PromptImportModal from '../components/PromptImportModal.vue'
import Lightbox from '../components/Lightbox.vue'
import CompareModal from '../components/CompareModal.vue'
import { parseMarkedSegments, renderAllSegments, smartSegmentText } from '../utils/segmentation'
import { confirmDialog } from '../utils/naive'
import { CONFIRM_PROMPTS } from '../utils/confirmKeys'
import { apiDelete, apiGet, apiPost } from '../api/client'
import { listImages, setImageFavorite } from '../api/images'
import {
  PROMPT_EXPORT_URL,
  batchDeletePrompts,
  batchFavoritePrompts,
  deletePrompt as deletePromptRequest,
  getPrompt,
  getPromptHistoryRefs,
  importPrompts,
  ratePrompt,
  setPromptFavorite,
  setPromptPinned,
  updatePrompt,
} from '../api/prompts'
import { autoClassifyPrompt, listCategories, listTags } from '../api/taxonomy'
import EmptyState from '../components/EmptyState.vue'
import QueryState from '../components/QueryState.vue'
import Skeleton from '../components/Skeleton.vue'
import { useSettings } from '../composables/useSettings'
import { useWorkflowQuality } from '../composables/useWorkflowQuality'
import { useWorkflowAspectRatio } from '../composables/useWorkflowAspectRatio'
import { useGenerate } from '../composables/useGenerate'
import { useImageLocation } from '../composables/useImageLocation'
import { usePromptDraft, splitTagText } from '../composables/usePromptDraft'
import { useToast } from '../composables/useToast'
import { useWorkflows, useWorkflowValidation, customWorkflowContent } from '../composables/useWorkflows'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { usePromptWorkspace } from '../composables/usePromptWorkspace'
import { usePromptList } from '../composables/usePromptList'
import { usePromptMatrix } from '../composables/usePromptMatrix'
import { resolveHistoryItems } from '../composables/useImagePreview'
import type { MatrixImage } from '../composables/useWorkflowMatrix'
import BatchReplaceModal from '../components/BatchReplaceModal.vue'
import PromptListFooter from '../components/PromptListFooter.vue'
import PromptListRow from '../components/PromptListRow.vue'
import PromptFilterSidebar from '../components/PromptFilterSidebar.vue'
import PromptDetailPane from '../components/PromptDetailPane.vue'
import { flattenCategories } from '../utils/categories'
import type {
  HistoryItem,
  HistoryPage,
  JobSnapshot,
  PromptDetail,
  PromptListItem,
} from '../api/types'

const { workflowPath, orientation } = useSettings()
const router = useRouter()
const quality = useWorkflowQuality(workflowPath)
const aspectRatio = useWorkflowAspectRatio(workflowPath)
const {
  busy: generating,
  job: activeJob,
  queue: jobQueue,
  error: generateError,
  run,
  runBatch,
  runBatchReplace,
  submitAndTrack,
  trackQueued,
} = useGenerate('', { queue: true })

const {
  pageSize,
  sort,
  order,
  sidebarCollapsed,
  sidebarWidth,
  page,
  search,
  categoryId,
  tagIds,
  tagMatch,
  fragmentType,
  fragmentMatch,
  selectedId,
  selectedIds,
  listEl,
  savedSession,
  saveUi,
  saveSession,
  onListScroll,
  cancelScrollSave,
  PAGE_SIZES,
} = usePromptWorkspace()

const missingOpen = ref(false)
const replaceOpen = ref(false)
const replaceTargetId = ref<number | null>(null)
/** 最近一次「替换碎片出图」的任务 id：弹窗靠它订阅进度、刷新后也能接回来。 */
const replaceJobId = ref<number | null>(null)
/** 外部跳转的目标 id：列表变化时据此保留选中，不抢着改选第一条。 */
const jumpTargetId = ref<number | null>(null)

const queryClient = useQueryClient()

const {
  list,
  total,
  totalPages,
  isFetching,
  listError,
  listErr,
  refetchList,
} = usePromptList({
  page,
  pageSize,
  search,
  categoryId,
  tagIds,
  tagMatch,
  fragmentType,
  fragmentMatch,
  sort,
  order,
})

/** 列表数据到位后再恢复滚动位置，否则容器还没高度，scrollTop 会被清 0。 */
let scrollRestored = false
watch(list, async () => {
  if (scrollRestored || !savedSession.scrollTop) return
  scrollRestored = true
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = savedSession.scrollTop
})

const { data: catData } = useQuery({
  queryKey: ['categories', 'prompt'],
  queryFn: () => listCategories({ tree: true, count_scope: 'prompt' }),
})

const { data: tagData } = useQuery({
  queryKey: ['tags', 'prompt'],
  queryFn: () => listTags({ count_scope: 'prompt' }),
})

const { workflows, allWorkflows } = useWorkflows()
const toast = useToast()
const createOpen = ref(false)
const importOpen = ref(false)
const { data: wfValidation } = useWorkflowValidation(workflowPath)

/**
 * 当前工作流的能力与真实档位：不支持画质 / 横竖时隐藏对应控件，
 * 档位按工作流的实际作用方式生成（不是固定的 2K..12K）。
 */
const { caps, qualityOptions, aspectRatios, defaultRatio } = useWorkflowCaps(
  workflowPath, allWorkflows, aspectRatio,
)

function generate(options: { count: number; seed: number | null }) {
  if (!draft.value) return
  if (!caps.value.prompt) {
    toast.error('该工作流不注入提示词（纯图像 / 超分），请换一个工作流')
    return
  }
  const count = Math.min(4, Math.max(1, options.count))
  // 多张必须给确定底种子：空输入时取提示词种子或随机数，依次 +1，
  // 否则后端回退到同一个保存种子，N 张出出来全一样。
  const base = options.seed ?? (
    count > 1 ? (draft.value.seed || Math.floor(Math.random() * 2 ** 31)) : null
  )
  for (let i = 0; i < count; i++) {
    run(draft.value.id, {
      workflowPath: workflowPath.value,
      quality: caps.value.quality ? quality.value : '1.0x',
      orientation: caps.value.orientation ? orientation.value : 'keep',
      aspectRatio: aspectRatio.value || defaultRatio.value,
      seed: base === null ? null : base + i,
      promptOverride: draft.value.prompt,
      negativePromptOverride: draft.value.negative_prompt,
    })
  }
}

/** 单条提示词的「替换碎片出图」入口；批量替换走左侧勾选栏。 */
function openReplaceForCurrent() {
  if (!draft.value) return
  replaceTargetId.value = draft.value.id
  replaceOpen.value = true
}

function openReplaceForSelection() {
  replaceTargetId.value = null
  replaceOpen.value = true
}

function closeReplace() {
  replaceOpen.value = false
  replaceTargetId.value = null
}

/** 树拍平成一维，带 depth 做缩进 —— 分类层级只有两级，递归组件是过度设计。 */
const flatCats = computed(() => flattenCategories(catData.value?.categories))

// ---------------- 详情 ----------------

const {
  data: detail,
  error: detailError,
  refetch: refetchDetail,
} = useQuery<PromptDetail>({
  queryKey: computed(() => ['prompt', selectedId.value]),
  queryFn: () => getPrompt(selectedId.value as number),
  enabled: computed(() => selectedId.value !== null),
})

/**
 * 选中了但详情还没到 = 加载中，不是「没选」。
 *
 * 切换条目时 vue-query 会把 data 置空，旧写法直接渲染空态，
 * 于是右侧闪成「选择左侧任意一条提示词」；请求失败时更是永远停在那句话上。
 */
const detailLoading = computed(
  () => selectedId.value !== null && !detail.value && !detailError.value,
)

/** 选中的条目已被删除（另一个标签页 / 补跑清理）：换选一条，别把用户留在死胡同。 */
watch(detailError, (err) => {
  if ((err as { status?: number } | null)?.status !== 404) return
  const stale = selectedId.value
  const next = list.value.find((it) => it.id !== stale)
  selectedId.value = next ? next.id : null
  queryClient.invalidateQueries({ queryKey: ['prompts'] })
})

/**
 * 列表变化后保证"总有一条被选中"，避免右侧空着。
 *
 * 外部跳转定位的条目可能不在当前页/当前筛选里，这时不能抢着改选第一条。
 */
watch(
  list,
  (items) => {
    if (!items.length) return
    const inList = selectedId.value !== null && items.some((it) => it.id === selectedId.value)
    if (inList) return
    if (selectedId.value !== null && selectedId.value === jumpTargetId.value) return
    selectedId.value = items[0].id
  },
  { immediate: true },
)

const {
  draft,
  dirty,
  draftTagList,
  revert,
  markSaved,
  clearDraft,
} = usePromptDraft(detail, selectedId)

function invalidateAll(id: number | null) {
  queryClient.invalidateQueries({ queryKey: ['prompts'] })
  if (id !== null) {
    queryClient.invalidateQueries({ queryKey: ['prompt', id] })
    // 出图/保存后「出图历史」也会变，之前漏刷导致缩略图停在旧状态
    queryClient.invalidateQueries({ queryKey: ['prompt-history', id] })
  }
  queryClient.invalidateQueries({ queryKey: ['tags'] })
}

/**
 * 关联 / 取消关联分类。
 *
 * 分类没有文本字段，关联只存在于 prompt_categories 表，所以必须走专用端点；
 * 不像标签那样"改文本再同步"。成功后同时失效详情与列表缓存 —— 分类计数会变。
 */
const categoryMutation = useMutation({
  mutationFn: (payload: { catId: number; attach: boolean }) =>
    payload.attach
      ? apiPost(`/api/categories/${payload.catId}/prompts/${selectedId.value}`)
      : apiDelete(`/api/categories/${payload.catId}/prompts/${selectedId.value}`),
  onSuccess: () => {
    if (selectedId.value !== null) {
      queryClient.invalidateQueries({ queryKey: ['prompt', selectedId.value] })
    }
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['categories'] })
  },
})

function isLinked(catId: number): boolean {
  return (detail.value?.categories ?? []).some((c) => c.id === catId)
}

function toggleCategory(catId: number) {
  if (selectedId.value === null) return
  categoryMutation.mutate({ catId, attach: !isLinked(catId) })
}

/** 单条自动归类：按提示词正文里的【类型】数量归入 组合/单项/零散。 */
const autoClassifyMutation = useMutation({
  mutationFn: autoClassifyPrompt,
  onSuccess: () => {
    if (selectedId.value !== null) {
      queryClient.invalidateQueries({ queryKey: ['prompt', selectedId.value] })
    }
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['categories'] })
  },
})

function autoClassifyOne() {
  if (selectedId.value === null) return
  autoClassifyMutation.mutate(selectedId.value)
}

/** 外部要求选中的提示词（路由 `/prompt/:id` 传入）。 */
const props = defineProps<{ selectId?: number | null }>()

const route = useRoute()
/** 从组合器跳过来编辑碎片时带的类型（`?frag_type=人物面部`），用于定位并高亮正文里的那一段。 */
const fragTypeFromJump = computed(() => String(route.query.frag_type || ''))

/**
 * 外部（画廊/组合器）要求定位到某条提示词时切过去。
 *
 * - `immediate`：PromptView 是切页后才挂载的，没有它首帧不会触发；
 * - 清空筛选并记下目标：目标可能被筛选挡住，列表 watcher 据此保留选中。
 */
watch(
  () => props.selectId,
  (id) => {
    if (!id) return
    jumpTargetId.value = id
    search.value = ''
    categoryId.value = null
    tagIds.value = []
    page.value = 1
    selectedId.value = id
  },
  { immediate: true },
)

/**
 * 左侧列表滚动定位到选中行（外部跳转时列表默认停在顶部，看不到高亮）。
 * 只在外部跳转时触发，避免用户自己点列表时被强行拉滚动条。
 */
watch(
  () => [selectedId.value, list.value.length] as const,
  async ([id, len]) => {
    if (!id || !len || selectedId.value !== jumpTargetId.value) return
    await nextTick()
    const row = listEl.value?.querySelector(`.row[data-id="${id}"]`)
    row?.scrollIntoView({ block: 'center' })
    jumpTargetId.value = null // 只滚一次
  },
)

/** 手动把左侧列表滚到当前选中的提示词；不在本页时给出提示。 */
async function locateSelected() {
  const id = selectedId.value
  if (id === null) return
  await nextTick()
  const row = listEl.value?.querySelector(`.row[data-id="${id}"]`)
  if (!row) {
    toast.info('当前提示词不在这一页')
    return
  }
  row.scrollIntoView({ block: 'center' })
  row.classList.add('locate-flash')
  window.setTimeout(() => row.classList.remove('locate-flash'), 900)
}

/**
 * 从组合器跳来编辑碎片：正文里选中并滚动到 `【frag_type】` 那一段，
 * 用户一眼看到要改哪里。用完即抹掉参数，刷新不再重复高亮。
 */
watch(
  [() => draft.value?.prompt, fragTypeFromJump],
  async ([text, fragType]) => {
    if (!text || !fragType) return
    const marker = `【${fragType}】`
    const idx = text.indexOf(marker)
    if (idx === -1) return
    // 只在首次进入时高亮（draft 变化会重复触发，但抹掉参数后 fragTypeFromJump 变空就不会再进）
    await nextTick()
    const ta = document.querySelector<HTMLTextAreaElement>('.editor.pos')
    if (!ta) return
    const contentStart = idx + marker.length
    const nextMarker = text.indexOf('【', contentStart)
    const end = nextMarker === -1 ? text.length : nextMarker
    ta.focus()
    ta.setSelectionRange(contentStart, Math.max(contentStart, end))
    // 抹掉 query，避免刷新/后退重复高亮
    route.query.frag_type && window.history.replaceState(null, '', route.path)
  },
  { immediate: true },
)

/** 复制文本到剪贴板（旧版提示词页的「复制」，正向/负向各一个按钮）。 */
async function copyText(text: string, label: string) {
  if (!text.trim()) {
    toast.error(`没有可复制的${label}`)
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    toast.success(`已复制${label}`)
  } catch {
    toast.error('复制失败（浏览器拒绝了剪贴板访问）')
  }
}

/**
 * 这条提示词已经出过哪些图。
 *
 * 先取 id，再走画廊同一个 `/api/images` 序列化入口 —— 缩略图、灯箱、收藏/删除/
 * 定位全部复用画廊组件，不再在这里手拼 URL 和 `<a target=_blank>`。
 */
const { data: shotHistory } = useQuery<HistoryPage>({
  queryKey: computed(() => ['prompt-history', selectedId.value]),
  queryFn: async () => {
    const empty: HistoryPage = { items: [], total: 0, page: 1, page_size: 24 }
    const id = selectedId.value
    if (!id) return empty
    const refs = await getPromptHistoryRefs(id, 24)
    const ids = refs.items.map((it) => it.id)
    if (!ids.length) return empty
    return listImages({
      ids: ids.join(','),
      page: 1,
      page_size: ids.length,
      sort: 'newest',
    })
  },
  enabled: computed(() => selectedId.value !== null),
})

const shotItems = computed<HistoryItem[]>(() => shotHistory.value?.items ?? [])
const shotOpen = ref(false)
const shotIndex = ref(0)
const { revealImage } = useImageLocation()

const linkedCategoryIds = computed(() => (detail.value?.categories ?? []).map((c) => c.id))

function openShot(index: number) {
  shotIndex.value = index
  shotOpen.value = true
}

function regenerateShot() {
  shotOpen.value = false
  generate({ count: 1, seed: null })
}

/** 档案里点「来源提示词」：关灯箱并切到那条提示词（沿用未保存修改的确认）。 */
async function jumpToPrompt(id: number) {
  shotOpen.value = false
  await selectRow(id)
}

function onShotChanged() {
  queryClient.invalidateQueries({ queryKey: ['prompt-history', selectedId.value] })
  queryClient.invalidateQueries({ queryKey: ['prompts'] })
}

// ---------------- 横评：同一提示词 × 多工作流 ----------------

/**
 * 一格一 job：图片的工作流归属取 job 级字段，混流塞进一个 batch job
 * 会让灯箱把模型标错。提交仍走 useGenerate 的共享底座（幂等键 / 输出目录 / SSE）。
 */
const matrix = usePromptMatrix({
  scope: () => (selectedId.value === null ? '' : `p:${selectedId.value}`),
  promptText: () => draft.value?.prompt ?? '',
  negativeText: () => draft.value?.negative_prompt ?? '',
  savedSeed: () => draft.value?.seed ?? null,
  workflows: () => workflows.value,
  currentWorkflow: () => workflowPath.value,
  ratio: () => aspectRatio.value || defaultRatio.value,
  tier: () => quality.value,
  orientation: () => orientation.value,
  submit: (req) =>
    submitAndTrack<{ success: boolean; job_id?: number | null }>('/api/runs', {
      id: selectedId.value,
      workflow_path: req.path,
      workflow_content: customWorkflowContent(req.path),
      quality: req.tier,
      orientation: req.orientation,
      aspect_ratio: req.ratio,
      seed: req.seed,
      prompt_override: req.prompt,
      negative_prompt_override: req.negative,
    }),
  track: trackQueued,
  fetchJob: (id) => apiGet<JobSnapshot>(`/api/jobs/${id}`).catch(() => null),
  jobs: () => jobQueue.value,
  shots: () => shotItems.value,
  refreshShots: () => {
    queryClient.invalidateQueries({ queryKey: ['prompt-history', selectedId.value] })
    queryClient.invalidateQueries({ queryKey: ['history'] })
  },
  useWorkflow: (path) => {
    workflowPath.value = path
  },
  notify: (kind, message) => {
    if (kind === 'error') toast.error(message)
    else if (kind === 'success') toast.success(message)
    else toast.info(message)
  },
})

const favoriteImageMutation = useMutation({
  mutationFn: (id: number) => setImageFavorite(id),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ['prompt-history', selectedId.value] })
    queryClient.invalidateQueries({ queryKey: ['history'] })
  },
})

/** 矩阵的看图/对比：格子只带文件名，先按名取回完整记录再喂给画廊组件。 */
const matrixCompareOpen = ref(false)
const matrixCompareItems = ref<HistoryItem[]>([])
const matrixShotOpen = ref(false)
const matrixShotItems = ref<HistoryItem[]>([])
const matrixShotIndex = ref(0)

function matrixImageRef(image: { filename: string; subfolder?: string | null; img_type?: string | null }) {
  return { filename: image.filename, subfolder: image.subfolder, type: image.img_type }
}

async function openMatrixCompare(images: MatrixImage[]) {
  if (images.length < 2) return
  matrixCompareItems.value = await resolveHistoryItems(images.slice(0, 4).map(matrixImageRef))
  matrixCompareOpen.value = true
}

async function openMatrixImage(payload: { items: MatrixImage[]; index: number }) {
  matrixShotItems.value = await resolveHistoryItems(payload.items.map(matrixImageRef))
  matrixShotIndex.value = Math.min(payload.index, Math.max(0, matrixShotItems.value.length - 1))
  matrixShotOpen.value = true
}



// ---------------- 智能分段 / 试跑 / 草稿 ----------------

const trialOpen = ref(false)

/**
 * 智能分段：把一整段提示词按关键词拆成【类型】结构。
 *
 * 库里很多提示词是「一整段话」，拆完之后才能直接喂给组合器 —— 组合器
 * 认的就是【类型】格式。
 */
async function smartSegment() {
  const text = draft.value?.prompt ?? ''
  if (!text.trim()) {
    toast.error('提示词是空的')
    return
  }
  const { marked, leftover } = await parseMarkedSegments(text)
  if (!leftover.trim() && Object.keys(marked).length) {
    toast.info('这条提示词已经是【类型】分段格式，无需再次分段')
    return
  }

  // 只对未标记文字分段，已有的【类型】块原样保留
  const fresh = leftover.trim() ? smartSegmentText(leftover) : {}
  const merged = { ...marked, ...fresh }
  const keys = Object.keys(merged)
  if (!keys.length) {
    toast.error('没能分出类型（文本里没命中任何关键词）')
    return
  }
  const rendered = await renderAllSegments(merged)
  if (!rendered) {
    toast.error('分段结果为空')
    return
  }
  const ok = await confirmDialog({
    title: '智能分段',
    content: `将整理为 ${keys.length} 类：${keys.join('、')}。\n用分段结果替换当前提示词？`,
    positiveText: '替换',
    negativeText: '取消',
    rememberKey: CONFIRM_PROMPTS.smartSegment.key,
  })
  if (!ok || !draft.value) return
  draft.value.prompt = rendered
  toast.success('已按类型分段')
}

const saveMutation = useMutation({
  mutationFn: (payload: Partial<PromptDetail>) =>
    updatePrompt(selectedId.value as number, payload),
  onSuccess: () => {
    markSaved()
    invalidateAll(selectedId.value)
  },
})

/** 输入框清空时 Vue 会给出空字符串，直接发给后端会被 Pydantic 拒掉。 */
function asNumberOrNull(value: unknown): number | null {
  if (value === '' || value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function save() {
  if (!draft.value) return
  saveMutation.mutate({
    name: draft.value.name,
    tags: draft.value.tags,
    prompt: draft.value.prompt,
    negative_prompt: draft.value.negative_prompt,
    note: draft.value.note,
    steps: asNumberOrNull(draft.value.steps),
    cfg_scale: asNumberOrNull(draft.value.cfg_scale),
    sampler: draft.value.sampler,
    seed: asNumberOrNull(draft.value.seed),
  })
}

/**
 * 收藏 / 置顶 / 评级只改元数据：本地更新即可。
 * 之前每次都 invalidateAll → 重拉详情 → 触发"恢复草稿"弹窗，纯属自找麻烦。
 */
const favoriteMutation = useMutation({
  mutationFn: () => setPromptFavorite(selectedId.value as number),
  onSuccess: (result) => {
    if (draft.value) draft.value.is_favorite = result.is_favorite
    const id = selectedId.value
    if (id !== null) {
      queryClient.setQueryData(['prompt', id], (old: PromptDetail | undefined) =>
        old ? { ...old, is_favorite: result.is_favorite } : old,
      )
    }
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
  },
})

const pinMutation = useMutation({
  mutationFn: () => setPromptPinned(selectedId.value as number),
  onSuccess: (result) => {
    if (draft.value) draft.value.is_pinned = result.is_pinned
    const id = selectedId.value
    if (id !== null) {
      queryClient.setQueryData(['prompt', id], (old: PromptDetail | undefined) =>
        old ? { ...old, is_pinned: result.is_pinned } : old,
      )
    }
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
  },
})

const rateMutation = useMutation({
  mutationFn: (rating: number) => ratePrompt(selectedId.value as number, rating),
  onSuccess: (result) => {
    if (draft.value) draft.value.rating = result.rating
    const id = selectedId.value
    if (id !== null) {
      queryClient.setQueryData(['prompt', id], (old: PromptDetail | undefined) =>
        old ? { ...old, rating: result.rating } : old,
      )
    }
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
  },
})

/** 单条删除（旧版详情页的「删除」）。删完清空选中，列表 watcher 会选下一条。 */
const deleteMutation = useMutation({
  mutationFn: deletePromptRequest,
  onSuccess: () => {
    selectedId.value = null
    jumpTargetId.value = null
    clearDraft()
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['tags'] })
    queryClient.invalidateQueries({ queryKey: ['categories'] })
    queryClient.invalidateQueries({ queryKey: ['history'] })
  },
})

async function deletePrompt() {
  if (!draft.value) return
  const id = draft.value.id
  const ok = await confirmDialog({
    title: '删除提示词',
    content: `确定删除「${draft.value.name || `#${id}`}」吗？\n\n出图记录会保留在画廊（只解除关联）。`,
    positiveText: '删除',
    negativeText: '取消',
  })
  if (!ok) return
  deleteMutation.mutate(id)
}

// ---------------- 多选与批量 ----------------

/** 批量替换弹窗要读"左侧勾选了哪些"，Set 在模板里不好直接展开。 */
const selectedPromptIds = computed(() => Array.from(selectedIds.value))
const selectedCount = computed(() => selectedIds.value.size)

function toggleSelect(id: number) {
  if (selectedIds.value.has(id)) selectedIds.value.delete(id)
  else selectedIds.value.add(id)
  selectedIds.value = new Set(selectedIds.value)
}

function selectAllOnPage() {
  selectedIds.value = new Set(list.value.map((it) => it.id))
}

function onPageSizeChange(size: number) {
  pageSize.value = size
  page.value = 1
}

function clearSelection() {
  selectedIds.value = new Set()
}

const batchFavoriteMutation = useMutation({
  mutationFn: batchFavoritePrompts,
  onSuccess: () => {
    clearSelection()
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
  },
})

const batchDeleteMutation = useMutation({
  mutationFn: batchDeletePrompts,
  onSuccess: () => {
    clearSelection()
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['history'] })
    queryClient.invalidateQueries({ queryKey: ['tags'] })
  },
})

function batchFavorite() {
  if (!selectedIds.value.size) return
  batchFavoriteMutation.mutate(Array.from(selectedIds.value))
}

async function batchDelete() {
  const ids = Array.from(selectedIds.value)
  if (!ids.length) return
  const ok = await confirmDialog({
    title: '批量删除提示词',
    content: `确定删除选中的 ${ids.length} 条提示词吗？\n\n出图记录会保留在画廊（只解除关联），不会一起删除。`,
    positiveText: '删除',
    negativeText: '取消',
  })
  if (!ok) return
  batchDeleteMutation.mutate(ids)
}

async function batchGenerate() {
  const ids = Array.from(selectedIds.value)
  if (!ids.length) return
  if (!caps.value.prompt) {
    toast.error('该工作流不注入提示词（纯图像 / 超分），请换一个工作流')
    return
  }
  const ok = await confirmDialog({
    title: '批量出图',
    content: `用「${workflowPath.value.split('\\').pop() || '未选择'}」出图 ${ids.length} 张？（画质 ${quality.value}）`,
    positiveText: '开始出图',
    negativeText: '取消',
    rememberKey: CONFIRM_PROMPTS.batchGenerate.key,
  })
  if (!ok) return
  runBatch(ids, {
    workflowPath: workflowPath.value,
    quality: caps.value.quality ? quality.value : '1.0x',
    orientation: caps.value.orientation ? orientation.value : 'keep',
    aspectRatio: aspectRatio.value || defaultRatio.value,
  })
}

/**
 * 批量替换碎片后出图：只替换本次注入的文本，不写回提示词库。
 *
 * 每条提示词仍用自己保存的 seed/steps/cfg，便于对比"换了一片之后"的效果。
 */
async function onBatchReplace(payload: {
  types: string[]
  workflowPath: string
  quality?: string
  aspectRatio?: string
  items: Array<{ promptId: number; seed: number | null; promptOverride: string }>
}) {
  if (!payload.workflowPath) {
    toast.error('请先选择工作流')
    return
  }
  if (!caps.value.prompt) {
    toast.error('该工作流不注入提示词，无法替换出图')
    return
  }
  if (!payload.items.length) return
  const single = payload.items.length === 1 && replaceTargetId.value !== null
  const wfName = payload.workflowPath.split(/[\\/]/).pop() || '未选择'
  const typeText = payload.types.map((t) => `【${t}】`).join('、')
  const ok = await confirmDialog({
    title: single ? '替换碎片出图' : '批量替换碎片并出图',
    content:
      `按替换清单修改 ${payload.items.length} 条提示词里的 ${typeText}（各自按设定的跳过/追加策略），` +
      `用「${wfName}」出图。\n\n只影响本次出图，不会写回提示词库；` +
      `生成的图片会作为「临时提示词」保留实际替换文本，不挂到原提示词名下。`,
    positiveText: '开始出图',
    negativeText: '取消',
    rememberKey: CONFIRM_PROMPTS.batchReplace.key,
  })
  if (!ok) return
  const jobId = await runBatchReplace(payload.items, {
    workflowPath: payload.workflowPath,
    quality: payload.quality || (caps.value.quality ? quality.value : '1.0x'),
    orientation: caps.value.orientation ? orientation.value : 'keep',
    aspectRatio: payload.aspectRatio || aspectRatio.value || defaultRatio.value,
    title: single
      ? '替换碎片出图'
      : payload.types.length > 1
        ? `替换 ${payload.types.length} 类碎片 ${payload.items.length} 条`
        : `批量替换${typeText} ${payload.items.length} 条`,
  })
  if (jobId) {
    // 弹窗不关：切到「任务与结果」页签，继续看进度与出图
    replaceJobId.value = jobId
    toast.success(`已提交 ${payload.items.length} 条替换任务`)
  }
}

// ---------------- 导入 / 导出 ----------------

const fileInput = ref<HTMLInputElement | null>(null)
const moreMenu = ref<HTMLDetailsElement | null>(null)
const moreOpen = ref(false)

function closeMore() {
  if (moreMenu.value) moreMenu.value.open = false
  moreOpen.value = false
}

/** `<details>` 原生不会点外面关闭，菜单会一直盖在列表上。 */
function onDocPointerDown(event: PointerEvent) {
  if (!moreOpen.value) return
  const root = moreMenu.value
  if (root && !root.contains(event.target as Node)) closeMore()
}

function onDocKeyDown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !moreOpen.value) return
  closeMore()
  moreMenu.value?.querySelector('summary')?.focus()
}
const importMessage = ref('')

function exportPrompts() {
  window.open(PROMPT_EXPORT_URL, '_blank')
}

const importMutation = useMutation({
  mutationFn: importPrompts,
  onSuccess: (result) => {
    importMessage.value = result.message
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['tags'] })
    queryClient.invalidateQueries({ queryKey: ['categories'] })
  },
})

async function onImportFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  importMessage.value = ''
  try {
    const parsed = JSON.parse(await file.text())
    const rows = Array.isArray(parsed) ? parsed : parsed.prompts
    if (!Array.isArray(rows) || !rows.length) {
      importMessage.value = '文件里没有找到 prompts 数组'
      return
    }
    importMutation.mutate(rows)
  } catch (e) {
    importMessage.value = `解析失败：${e instanceof Error ? e.message : String(e)}`
  }
}

/** 新建完成：直接选中新条目，并防止列表 watcher 抢改。 */
function onCreated(id: number) {
  jumpTargetId.value = id
  selectedId.value = id
  invalidateAll(id)
}

/** 智能导入完成：刷新列表/标签/分类，不抢当前选中。 */
function onImported() {
  queryClient.invalidateQueries({ queryKey: ['prompts'] })
  queryClient.invalidateQueries({ queryKey: ['tags'] })
  queryClient.invalidateQueries({ queryKey: ['categories'] })
}

// ---------------- 筛选 ----------------

function selectCategory(id: number | null) {
  categoryId.value = id
  page.value = 1
}

function onSearchInput(value: string) {
  search.value = value
  page.value = 1
}

function onSortChange(value: string) {
  sort.value = value
  page.value = 1
}

function toggleOrder() {
  order.value = order.value === 'desc' ? 'asc' : 'desc'
}

function onTagMatchChange(value: 'all' | 'any') {
  tagMatch.value = value
  page.value = 1
}

function onFragmentTypeChange(value: string) {
  fragmentType.value = value
  page.value = 1
}

function onFragmentMatchChange(value: 'has' | 'only') {
  fragmentMatch.value = value
  page.value = 1
}

function onClearTags() {
  tagIds.value = []
  page.value = 1
}

function onClearFragment() {
  fragmentType.value = ''
  fragmentMatch.value = 'has'
  page.value = 1
}


function toggleTag(id: number) {
  const idx = tagIds.value.indexOf(id)
  if (idx >= 0) tagIds.value.splice(idx, 1)
  else tagIds.value.push(id)
  page.value = 1
}

function clearFilters() {
  search.value = ''
  categoryId.value = null
  tagIds.value = []
  tagMatch.value = 'all'
  fragmentType.value = ''
  fragmentMatch.value = 'has'
  page.value = 1
}

/** 切换提示词前拦住未保存修改，避免点一下列表就静默丢稿。 */
async function selectRow(id: number) {
  if (id === selectedId.value) return
  if (dirty.value) {
    const ok = await confirmDialog({
      title: '有未保存的修改',
      content: '切换提示词会放弃当前未保存的修改，继续吗？',
      positiveText: '放弃并切换',
      negativeText: '留在当前',
    })
    if (!ok) return
  }
  selectedId.value = id
}

/** 列表行里的标签 chip：只显示前 4 个，避免把行撑高。 */
function rowTags(item: PromptListItem): string[] {
  const tags = splitTagText(item.tags)
  return tags.length > 4 ? [...tags.slice(0, 4), `+${tags.length - 4}`] : tags
}

// ---------------- 侧栏折叠 / 拖宽 ----------------

let resizing = false
let resizeStartX = 0
let resizeStartWidth = 0

function startResize(event: MouseEvent) {
  resizing = true
  resizeStartX = event.clientX
  resizeStartWidth = sidebarWidth.value
  document.body.style.cursor = 'col-resize'
  window.addEventListener('mousemove', onResize)
  window.addEventListener('mouseup', stopResize)
}

function onResize(event: MouseEvent) {
  if (!resizing) return
  sidebarWidth.value = Math.min(
    600,
    Math.max(280, resizeStartWidth + event.clientX - resizeStartX),
  )
}

function stopResize() {
  if (!resizing) return
  resizing = false
  document.body.style.cursor = ''
  window.removeEventListener('mousemove', onResize)
  window.removeEventListener('mouseup', stopResize)
  saveUi()
}

function onBeforeUnload(event: BeforeUnloadEvent) {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => {
  window.addEventListener('beforeunload', onBeforeUnload)
  document.addEventListener('pointerdown', onDocPointerDown)
  document.addEventListener('keydown', onDocKeyDown)
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  document.removeEventListener('pointerdown', onDocPointerDown)
  document.removeEventListener('keydown', onDocKeyDown)
  cancelScrollSave()
  saveSession()
  stopResize()
})
</script>

<template>
  <div class="prompt-page">
    <aside v-if="!sidebarCollapsed" class="sidebar" :style="{ width: `${sidebarWidth}px` }">
      <PromptFilterSidebar
        :search="search"
        :categories="catData?.categories"
        :category-id="categoryId"
        :tags="tagData?.tags ?? []"
        :tag-ids="tagIds"
        :tag-match="tagMatch"
        :sort="sort"
        :order="order"
        :fragment-type="fragmentType"
        :fragment-match="fragmentMatch"
        @collapse="sidebarCollapsed = true"
        @update:search="onSearchInput"
        @select-category="selectCategory"
        @update:sort="onSortChange"
        @toggle-order="toggleOrder"
        @update:tag-match="onTagMatchChange"
        @toggle-tag="toggleTag"
        @set-fragment-type="onFragmentTypeChange"
        @set-fragment-match="onFragmentMatchChange"
        @clear-tags="onClearTags"
        @clear-fragment="onClearFragment"
        @clear-filters="clearFilters"
      >
        <template #actions>
          <div class="side-actions">
            <button class="btn btn-sm primary" title="新建提示词" @click="createOpen = true">
              ＋ 新建
            </button>
            <button class="btn btn-sm" title="从 JSON 导入提示词" @click="fileInput?.click()">
              导入
            </button>
            <button class="btn btn-sm" title="导出全部提示词为 JSON" @click="exportPrompts">
              导出
            </button>
            <button class="btn btn-sm" title="临时试跑：粘贴外来提示词直接出图，不写回提示词库" @click="trialOpen = true">
              <Icon name="flask-conical" /> 试跑
            </button>
            <details
              ref="moreMenu"
              class="more-menu"
              @toggle="moreOpen = ($event.target as HTMLDetailsElement).open"
            >
              <summary class="btn btn-sm" title="更多批量操作" :aria-expanded="moreOpen">更多 ▾</summary>
              <div class="more-pop">
                <button class="btn btn-sm" title="批量粘贴 AI 润色后的多条提示词，自动分段后入库" @click="closeMore(); importOpen = true">
                  智能导入
                </button>
                <button class="btn btn-sm" title="给「有提示词但没出图」的条目补图" @click="closeMore(); missingOpen = true">
                  补跑缺图
                </button>
              </div>
            </details>
            <input
              ref="fileInput"
              type="file"
              accept="application/json,.json"
              hidden
              @change="onImportFile"
            />
          </div>
        </template>
      </PromptFilterSidebar>

      <div v-if="importMessage" class="import-line">{{ importMessage }}</div>

      <QueryState v-if="listError" :error="listErr" @retry="refetchList" />

      <div class="list-head">
        <span class="list-title">提示词</span>
        <span class="list-total">
          共 {{ total }} 条<span v-if="isFetching"> · 加载中</span>
        </span>
      </div>

      <div ref="listEl" class="list" :class="{ 'has-bulk': selectedCount }" @scroll.passive="onListScroll">
        <PromptListRow
          v-for="item in list"
          :key="item.id"
          :item="item"
          :active="selectedId === item.id"
          :picked="selectedIds.has(item.id)"
          :tags="rowTags(item)"
          @select="selectRow"
          @toggle="toggleSelect"
        />

        <Skeleton v-if="isFetching && !list.length" class="list-skeleton" variant="block" :count="5" />
        <EmptyState
          v-if="!list.length && !isFetching"
          size="big"
          icon="⌕"
          text="没有符合条件的提示词"
          hint="换个关键词，或清空当前筛选"
          action-text="清空筛选"
          @action="clearFilters"
        />
      </div>

      <PromptListFooter
        :selected-count="selectedCount"
        :generating="generating"
        :page="page"
        :total-pages="totalPages"
        :page-size="pageSize"
        :selected-id="selectedId"
        :page-sizes="PAGE_SIZES"
        @select-all="selectAllOnPage"
        @clear-selection="clearSelection"
        @batch-favorite="batchFavorite"
        @batch-replace="openReplaceForSelection"
        @batch-generate="batchGenerate"
        @batch-delete="batchDelete"
        @update:page="page = $event"
        @page-size-change="onPageSizeChange"
        @locate="locateSelected"
      />
    </aside>

    <aside v-else class="rail">
      <button class="btn btn-sm" title="展开侧栏" @click="sidebarCollapsed = false">»</button>
      <span class="rail-count" :title="`共 ${total} 条`">{{ total }}</span>
      <button class="btn btn-sm" title="新建提示词" @click="createOpen = true">＋</button>
      <button class="btn btn-sm" title="临时试跑" @click="trialOpen = true"><Icon name="flask-conical" /></button>
    </aside>

    <div v-if="!sidebarCollapsed" class="resizer" title="拖动调整侧栏宽度" @mousedown.prevent="startResize" />

    <PromptDetailPane
      v-model:workflow-path="workflowPath"
      v-model:quality="quality"
      v-model:orientation="orientation"
      v-model:aspect-ratio="aspectRatio"
      v-model:draft-tag-list="draftTagList"
      :draft="draft"
      :loading="detailLoading"
      :error="detailError"
      :dirty="dirty"
      :saving="saveMutation.isPending.value"
      :classifying="autoClassifyMutation.isPending.value"
      :generating="generating"
      :workflows="workflows"
      :aspect-ratios="aspectRatios"
      :default-ratio="defaultRatio"
      :quality-options="qualityOptions"
      :caps="caps"
      :wf-validation="wfValidation"
      :generate-error="generateError"
      :active-job="activeJob"
      :flat-cats="flatCats"
      :tags="tagData?.tags ?? []"
      :linked-category-ids="linkedCategoryIds"
      :shot-items="shotItems"
      :matrix="matrix"
      @favorite-image="$event.id && favoriteImageMutation.mutate($event.id)"
      @matrix-compare="openMatrixCompare($event)"
      @matrix-open-image="openMatrixImage($event)"
      @generate="generate"
      @retry="refetchDetail()"
      @smart-segment="smartSegment"
      @replace-fragment="openReplaceForCurrent"
      @favorite="favoriteMutation.mutate()"
      @pin="pinMutation.mutate()"
      @revert="revert"
      @save="save"
      @delete-prompt="deletePrompt"
      @copy="copyText"
      @rate="rateMutation.mutate"
      @auto-classify="autoClassifyOne"
      @toggle-category="toggleCategory"
      @open-shot="openShot"
      @reveal="revealImage"
    />

    <MissingImageRunPanel :open="missingOpen" @close="missingOpen = false" />
    <Lightbox
      v-if="shotOpen"
      :items="shotItems"
      :index="shotIndex"
      :workflows="workflows"
      @update:index="shotIndex = $event"
      @close="shotOpen = false"
      @regenerate="regenerateShot"
      @jump-to-prompt="jumpToPrompt"
      @changed="onShotChanged"
    />
    <CompareModal
      :open="matrixCompareOpen"
      :items="matrixCompareItems"
      @close="matrixCompareOpen = false"
    />
    <Lightbox
      v-if="matrixShotOpen"
      :items="matrixShotItems"
      :index="matrixShotIndex"
      :workflows="workflows"
      @update:index="matrixShotIndex = $event"
      @close="matrixShotOpen = false"
      @changed="onShotChanged"
    />
    <PromptTrialPanel
      :open="trialOpen"
      :prompt-id="draft?.id ?? null"
      :prompt-name="draft?.name ?? ''"
      @close="trialOpen = false"
      @created="onCreated"
    />
    <PromptCreateModal :open="createOpen" @close="createOpen = false" @created="onCreated" />
    <PromptImportModal :open="importOpen" @close="importOpen = false" @imported="onImported" />
    <BatchReplaceModal
      :open="replaceOpen"
      :search="search"
      :category-id="categoryId"
      :tag-ids="tagIds"
      :tag-match="tagMatch"
      :fragment-types="fragmentType ? [fragmentType] : []"
      :fragment-match="fragmentMatch"
      :selected-ids="selectedPromptIds"
      :workflow-path="workflowPath"
      :lock-prompt-id="replaceTargetId"
      :lock-prompt-name="replaceTargetId !== null ? (draft?.name ?? '') : ''"
      :job-id="replaceJobId"
      @close="closeReplace"
      @submit="onBatchReplace"
      @go-jobs="closeReplace(); router.push('/jobs')"
      @jump-to-prompt="(id) => { closeReplace(); jumpToPrompt(id) }"
    />
  </div>
</template>

<style scoped>
.prompt-page {
  display: flex;
  height: 100%;
  min-height: 0;
}

/* ---------- 侧栏（列表 + 筛选） ---------- */

.sidebar {
  flex: none;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--border);
  background: var(--panel);
}

.rail {
  flex: none;
  width: 44px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) 0;
  border-right: 1px solid var(--border);
  background: var(--panel);
}

.rail-count {
  font-size: var(--fs-xs);
  color: var(--muted);
  writing-mode: vertical-rl;
  letter-spacing: 1px;
}

.resizer {
  flex: none;
  width: 5px;
  cursor: col-resize;
  background: transparent;
}

.resizer:hover {
  background: var(--primary-soft);
}

/* 4 个入口平分整行宽度；其余低频操作收进「更多」，避免工具栏占两行 */
.side-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(60px, 1fr));
  gap: var(--gap-xs);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
}

.more-menu {
  position: relative;
  min-width: 0;
}

.more-menu > summary {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  list-style: none;
  cursor: pointer;
}

.more-menu > summary::-webkit-details-marker {
  display: none;
}

.more-pop {
  position: absolute;
  top: calc(100% + var(--gap-xs));
  right: 0;
  z-index: var(--z-modal);
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  /* 按最长菜单项收窄：写死 150px 时两个四字项的菜单比触发器宽一倍还多 */
  width: max-content;
  min-width: 100%;
  max-width: min(240px, calc(100vw - 24px));
  padding: var(--gap-xs);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  box-shadow: var(--shadow-2);
}

.more-pop .btn {
  justify-content: flex-start;
  text-align: left;
}

.side-actions .btn {
  width: 100%;
  min-width: 0;
  padding: 3px 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.import-line {
  padding: var(--gap-xs) var(--gap);
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-xs);
  color: var(--primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--muted);
  white-space: nowrap;
}

.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-sm);
  padding: var(--gap-xs) var(--gap);
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-xs);
}

.list-title {
  color: var(--text);
  font-weight: 600;
}

.list-total {
  color: var(--muted);
  white-space: nowrap;
}

.list-skeleton {
  padding: var(--gap);
}

.list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* 批量操作条：浮在页面底部居中。 */
.list.has-bulk {
  /* 给底部悬浮条留出滚动空间，最后一条能被滚到它上方 */
  padding-bottom: var(--gap-2xl);
}

@media (max-width: 640px) {
  .bulk {
    width: calc(100vw - var(--gap-lg) - var(--gap-xs));
    flex-wrap: wrap;
    justify-content: center;
    border-radius: var(--radius-lg);
    white-space: normal;
  }

  .list.has-bulk {
    padding-bottom: 104px;
  }
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: rgb(255 255 255);
}

.btn.primary:disabled {
  opacity: 0.4;
}

/* 翻页行：全选 / 总数 / 翻页 / 每页条数，都在侧栏底部一行里 */
.row.locate-flash {
  box-shadow: inset 0 0 0 1px var(--primary);
}

.spacer {
  flex: 1;
}

.empty.big {
  padding: 60px;
  text-align: center;
}
</style>
