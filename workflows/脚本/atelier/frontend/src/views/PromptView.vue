<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useRoute, useRouter } from 'vue-router'

import TagInput from '../components/TagInput.vue'
import MissingImageRunPanel from '../components/MissingImageRunPanel.vue'
import PromptTrialPanel from '../components/PromptTrialPanel.vue'
import PromptCreateModal from '../components/PromptCreateModal.vue'
import PromptImportModal from '../components/PromptImportModal.vue'
import WorkflowPicker from '../components/WorkflowPicker.vue'
import Lightbox from '../components/Lightbox.vue'
import { parseMarkedSegments, renderAllSegments, smartSegmentText } from '../utils/segmentation'
import { confirmDialog } from '../utils/naive'
import { CONFIRM_PROMPTS } from '../utils/confirmKeys'
import { apiDelete, apiPost, thumbnailUrl } from '../api/client'
import { listImages } from '../api/images'
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
import { useWorkflows, useWorkflowValidation } from '../composables/useWorkflows'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { usePromptWorkspace } from '../composables/usePromptWorkspace'
import { usePromptList } from '../composables/usePromptList'
import WorkflowParams from '../components/WorkflowParams.vue'
import BatchReplaceModal from '../components/BatchReplaceModal.vue'
import { statusLabel } from '../utils/format'
import PromptListFooter from '../components/PromptListFooter.vue'
import PromptListRow from '../components/PromptListRow.vue'
import PromptFilterSidebar from '../components/PromptFilterSidebar.vue'
import { flattenCategories } from '../utils/categories'
import type {
  HistoryItem,
  HistoryPage,
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
  error: generateError,
  run,
  runBatch,
  runBatchReplace,
} = useGenerate()

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
/** 负面提示词默认收起：空值不该占一大块；有内容时显示单行摘要。 */
const negativeExpanded = ref(false)

watch(selectedId, () => {
  negativeExpanded.value = false
})

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

function generate() {
  if (!draft.value) return
  if (!caps.value.prompt) {
    toast.error('该工作流不注入提示词（纯图像 / 超分），请换一个工作流')
    return
  }
  run(draft.value.id, {
    workflowPath: workflowPath.value,
    quality: caps.value.quality ? quality.value : '4K',
    orientation: caps.value.orientation ? orientation.value : 'keep',
    aspectRatio: aspectRatio.value || defaultRatio.value,
  })
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

const { data: detail } = useQuery<PromptDetail>({
  queryKey: computed(() => ['prompt', selectedId.value]),
  queryFn: () => getPrompt(selectedId.value as number),
  enabled: computed(() => selectedId.value !== null),
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

function openShot(index: number) {
  shotIndex.value = index
  shotOpen.value = true
}

function regenerateShot() {
  shotOpen.value = false
  generate()
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
    quality: caps.value.quality ? quality.value : '4K',
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
    quality: payload.quality || (caps.value.quality ? quality.value : '4K'),
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

function closeMore() {
  if (moreMenu.value) moreMenu.value.open = false
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

onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
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
            <details ref="moreMenu" class="more-menu">
              <summary class="btn btn-sm" title="更多批量操作">更多 ▾</summary>
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
    </aside>

    <div v-if="!sidebarCollapsed" class="resizer" title="拖动调整侧栏宽度" @mousedown.prevent="startResize" />

    <section class="detail-pane">
      <EmptyState v-if="!draft" size="big" text="选择左侧任意一条提示词" />

      <div v-else class="detail">
        <div class="detail-top">
          <div class="generate-bar">
            <div class="generate-settings">
              <WorkflowPicker v-model="workflowPath" :workflows="workflows" />
              <WorkflowParams
                v-model:quality="quality"
                v-model:orientation="orientation"
                v-model:aspect-ratio="aspectRatio"
                :aspect-ratios="aspectRatios"
                :default-ratio="defaultRatio"
                :workflow-path="workflowPath"
                :caps="caps"
                :quality-options="qualityOptions"
              />
              <span
                v-if="workflowPath && caps.prompt && (!caps.negative || caps.negative_effective === false)"
                class="cap-hint"
                :title="caps.negative_effective === false
                  ? '该工作流有负向字段，但 CFG=1，采样时不会生效'
                  : '该工作流不接收负面提示词'"
              >
                {{ caps.negative_effective === false ? '负向不生效' : '不支持负面' }}
              </span>
              <span
                v-if="workflowPath && !caps.prompt"
                class="cap-hint warn"
                title="该工作流不注入提示词"
              >
                不注入提示词
              </span>
            </div>
            <div class="generate-actions">
              <button class="btn btn-sm" title="按关键词把提示词拆成【类型】结构" @click="smartSegment">
                ✂ 智能分段
              </button>
              <button
                class="btn btn-sm"
                title="只替换这条提示词里的某一类碎片，再出图"
                :disabled="!caps.prompt"
                @click="openReplaceForCurrent"
              >
                替换碎片
              </button>
              <button
                class="btn btn-sm"
                title="用当前草稿试跑，不写回提示词库"
                :disabled="!caps.prompt"
                @click="trialOpen = true"
              >
                🧪 试跑
              </button>
              <button
                class="btn btn-sm"
                title="同一条提示词换种子出多张变体"
                :disabled="!caps.prompt"
                @click="trialOpen = true"
              >
                🎲 变体
              </button>
              <span v-if="wfValidation && !wfValidation.valid" class="gen-error">
                工作流不可用：{{ wfValidation.error }}
              </span>
              <span v-else-if="generateError" class="gen-error">{{ generateError }}</span>
              <span v-else-if="activeJob" class="job-state" :class="activeJob?.status">
                {{ statusLabel(activeJob?.status) }} {{ activeJob?.done_count ?? 0 }}/{{ activeJob?.total ?? 1 }}
              </span>
              <button
                class="btn btn-sm primary"
                :class="{ loading: generating }"
                :disabled="generating || !workflowPath || !caps.prompt"
                @click="generate"
              >
                {{ generating ? '生成中…' : '🚀 出图' }}
              </button>
            </div>
          </div>

          <div class="action-bar">
            <input v-model="draft.name" class="name-input" placeholder="未命名" />
            <span v-if="dirty" class="dirty-badge">● 已修改</span>
            <button
              class="btn btn-sm"
              :class="{ active: draft.is_favorite }"
              title="收藏"
              @click="favoriteMutation.mutate()"
            >
              {{ draft.is_favorite ? '★ 已收藏' : '☆ 收藏' }}
            </button>
            <button
              class="btn btn-sm"
              :class="{ active: draft.is_pinned }"
              :title="draft.is_pinned ? '已置顶，点击取消' : '置顶这条提示词'"
              @click="pinMutation.mutate()"
            >
              {{ draft.is_pinned ? '📌 已置顶' : '📌 置顶' }}
            </button>
            <button class="btn btn-sm" :disabled="!dirty" @click="revert">撤销</button>
            <button
              class="btn btn-sm primary"
              :disabled="!dirty || saveMutation.isPending.value"
              @click="save"
            >
              {{ saveMutation.isPending.value ? '保存中…' : '保存' }}
            </button>
            <button class="btn btn-sm danger" title="删除这条提示词" @click="deletePrompt">
              删除
            </button>
          </div>
        </div>

        <div class="detail-body">
          <main class="detail-main">
            <section class="section">
              <div class="section-head">
                <span>
                  正向提示词
                  <span v-if="dirty" class="dirty-badge">● 已修改</span>
                </span>
                <button class="btn btn-sm" @click="copyText(draft.prompt, '提示词')">复制</button>
              </div>
              <textarea v-model="draft.prompt" class="editor pos" spellcheck="false" />
            </section>

            <section class="section">
              <div class="section-head">
                <span>
                  负面提示词
                  <i v-if="caps.negative_effective === false" class="cap-inline warn">
                    负向不生效
                    <template v-if="typeof caps.negative_cfg === 'number'">（CFG={{ caps.negative_cfg }}）</template>
                  </i>
                  <i v-else-if="!caps.negative" class="cap-inline">该工作流不注入</i>
                </span>
                <div class="section-actions">
                  <button
                    v-if="draft.negative_prompt"
                    class="btn btn-sm"
                    @click="copyText(draft.negative_prompt, '负面提示词')"
                  >
                    复制
                  </button>
                  <button class="btn btn-sm" @click="negativeExpanded = !negativeExpanded">
                    {{ negativeExpanded ? '收起' : draft.negative_prompt ? '展开' : '＋ 添加' }}
                  </button>
                </div>
              </div>
              <textarea
                v-if="negativeExpanded"
                v-model="draft.negative_prompt"
                class="editor neg"
                spellcheck="false"
                placeholder="输入负面提示词…"
              />
              <button v-else class="negative-line" @click="negativeExpanded = true">
                <span :class="{ empty: !draft.negative_prompt }">
                  {{
                    draft.negative_prompt ||
                    (caps.negative_effective === false
                      ? '（空；当前工作流负向不生效，仅归档）'
                      : caps.negative
                        ? '（空）点击添加'
                        : '（空，仅归档，不参与出图）')
                  }}
                </span>
              </button>
            </section>

            <section class="section">
              <div class="section-head"><span>备注</span></div>
              <input v-model="draft.note" class="note-input" placeholder="可留空" />
            </section>
          </main>

          <aside class="detail-rail">
            <div class="rail-rating">
              <span class="label">评级</span>
              <button
                v-for="n in 5"
                :key="n"
                class="star-btn"
                :class="{ on: (draft.rating ?? 0) >= n }"
                @click="rateMutation.mutate(n)"
              >
                ★
              </button>
              <span class="meta">使用 {{ draft.usage_count }} 次</span>
            </div>

            <section class="section">
              <div class="section-head"><span>参数</span></div>
              <div class="params">
              <label class="param-item">
                <span class="param-label">步数</span>
                <input
                  v-model.number="draft.steps"
                  class="param-input"
                  type="number"
                  min="1"
                  placeholder="-"
                />
              </label>
              <label class="param-item">
                <span class="param-label">CFG</span>
                <input
                  v-model.number="draft.cfg_scale"
                  class="param-input"
                  type="number"
                  step="0.1"
                  placeholder="-"
                />
              </label>
              <label class="param-item">
                <span class="param-label">采样器</span>
                <input v-model="draft.sampler" class="param-input" placeholder="-" />
              </label>
              <label class="param-item">
                <span class="param-label">种子</span>
                <input
                  v-model.number="draft.seed"
                  class="param-input"
                  type="number"
                  min="0"
                  placeholder="-"
                />
              </label>
              <div class="param-item">
                <span class="param-label">分辨率</span>
                <span class="param-value">
                  {{ draft.width && draft.height ? `${draft.width}×${draft.height}` : '-' }}
                </span>
              </div>
              <div class="param-item">
                <span class="param-label">模型</span>
                <span class="param-value" :title="draft.model || '-'">{{ draft.model || '-' }}</span>
              </div>
              </div>
            </section>

            <section class="section">
              <div class="section-head"><span>标签</span></div>
              <TagInput v-model="draftTagList" :suggestions="tagData?.tags ?? []" />
            </section>

            <section class="section">
              <div class="section-head">
                <span>分类（已关联 {{ draft.categories?.length ?? 0 }} 个）</span>
                <button
                  class="btn btn-sm"
                  :disabled="autoClassifyMutation.isPending.value"
                  title="按提示词正文里的【类型】数量自动归入 组合 / 单项 / 零散"
                  @click="autoClassifyOne"
                >
                  {{ autoClassifyMutation.isPending.value ? '归类中…' : '自动归类' }}
                </button>
              </div>
              <div class="cat-chips">
                <button
                  v-for="cat in flatCats"
                  :key="cat.id"
                  class="cat-chip"
                  :class="{ on: isLinked(cat.id) }"
                  :style="{ '--c': cat.color }"
                  :title="cat.name"
                  @click="toggleCategory(cat.id)"
                >
                  {{ cat.name }}
                </button>
                <EmptyState v-if="!flatCats.length" text="暂无分类" compact />
              </div>
            </section>

            <section class="section">
              <div class="section-head">
                <span>出图历史（{{ shotItems.length }} 张）</span>
              </div>
              <div v-if="shotItems.length" class="shot-grid">
                <div
                  v-for="(shot, index) in shotItems"
                  :key="shot.id"
                  class="shot"
                  role="button"
                  tabindex="0"
                  :title="`${shot.filename}\n点击查看原图`"
                  @click="openShot(index)"
                  @keydown.enter.prevent="openShot(index)"
                >
                  <img :src="thumbnailUrl(shot, 200)" :alt="shot.filename" loading="lazy" />
                  <button
                    class="shot-locate"
                    title="在资源管理器中定位"
                    @click.stop="revealImage(shot)"
                  >
                    定位
                  </button>
                </div>
              </div>
              <span v-else class="muted">这条提示词还没有出图</span>
            </section>
          </aside>
        </div>

        <div class="timestamps">
          创建 {{ draft.created_at || '未知' }}
          <span v-if="draft.updated_at && draft.updated_at !== draft.created_at">
            · 更新 {{ draft.updated_at }}
          </span>
        </div>
      </div>
    </section>

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
    <PromptTrialPanel
      :open="trialOpen"
      :prompt="draft?.prompt ?? ''"
      :negative-prompt="draft?.negative_prompt ?? ''"
      :prompt-id="draft?.id ?? null"
      @close="trialOpen = false"
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
  width: 150px;
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

.btn.danger {
  border-color: var(--danger);
  color: var(--danger-text-button);
}

.btn.danger:hover {
  background: var(--danger-soft);
}

/* 翻页行：全选 / 总数 / 翻页 / 每页条数，都在侧栏底部一行里 */
.row.locate-flash {
  box-shadow: inset 0 0 0 1px var(--primary);
}

/* ---------- 详情 ---------- */

.detail-pane {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  container-type: inline-size;
}

.detail {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-lg);
}

/* 顶部出图上下文 + 操作，固定住，长正文滚动时不用回顶部 */
.detail-top {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding-bottom: var(--gap-sm);
  background: var(--bg);
}

.generate-bar {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
}

/* 左边设置区先按内容撑开，放不下时由工作流名让出宽度；右边动作组整体不压缩 */
.generate-settings {
  display: flex;
  flex: 1 1 auto;
  min-width: 0;
  flex-wrap: nowrap;
  align-items: center;
  gap: var(--gap-sm);
}

.generate-actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  align-items: center;
  gap: var(--gap-sm);
  margin-left: auto;
}

/* 按钮整组不参与压缩，压缩优先发生在工作流选择器上 */
.generate-settings > .btn,
.generate-actions > .btn {
  flex: none;
  white-space: nowrap;
}

/* 这档宽度下单行放不下全部内容：先收起能力提示（下方负面提示词区有同样信息），
   把宽度留给工作流名和分辨率 */
@container (min-width: 1041px) and (max-width: 1260px) {
  .generate-settings > .cap-hint {
    display: none;
  }
}

/* 详情区不够宽时，整组动作落到下一行，而不是把几个按钮拆散 */
@container (max-width: 1040px) {
  .generate-bar,
  .generate-settings,
  .generate-actions {
    flex-wrap: wrap;
  }
}

/* 正文与元数据分栏：宽屏右栏常驻，窄屏自动落回单列 */
.detail-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: var(--gap-lg);
  align-items: start;
}

.detail-main {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  min-width: 0;
}

.detail-rail {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  min-width: 0;
  padding-left: var(--gap-lg);
  border-left: 1px solid var(--border);
}

@container (max-width: 900px) {
  .detail-body {
    grid-template-columns: 1fr;
  }

  .detail-rail {
    padding-left: 0;
    border-left: none;
  }
}

.cap-hint {
  font-size: var(--fs-xs);
  color: var(--muted);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-pill);
  padding: 1px 7px;
  white-space: nowrap;
  flex: none;
}

.cap-hint.warn {
  color: var(--warn);
  border-color: var(--warn);
}

.gen-error {
  font-size: var(--fs-sm);
  color: var(--danger);
}

.job-state {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.job-state.running,
.job-state.pending {
  color: var(--primary);
}

.job-state.done {
  color: var(--success);
}

.job-state.error {
  color: var(--danger);
}

.action-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-xs);
}

/* 标题输入吃掉剩余宽度，按钮保持单行不拆字 */
.action-bar > .btn {
  flex: none;
  white-space: nowrap;
}

.dirty-badge {
  flex: none;
  padding: 1px 7px;
  border: 1px solid var(--warn);
  border-radius: var(--radius-pill);
  color: var(--warn);
  font-size: var(--fs-xs);
  font-weight: 400;
  white-space: nowrap;
}

.name-input {
  flex: 1;
  min-width: 180px;
  font-size: var(--fs-lg);
  font-weight: 600;
  background: transparent;
  border: 1px solid transparent;
  padding: 4px 6px;
}

.name-input:hover,
.name-input:focus {
  border-color: var(--border);
  background: var(--panel-2);
}

.stars {
  display: flex;
  align-items: center;
  gap: 2px;
}

.rail-rating {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: var(--fs-sm);
  color: var(--muted);
}

.label {
  font-size: var(--fs-sm);
  color: var(--muted);
  margin-right: var(--gap-sm);
}

.star-btn {
  border: none;
  background: transparent;
  /* 未收藏态：深色下沿用边框色，浅色下由令牌换成可辨识的中灰。 */
  color: var(--icon-idle);
  font-size: var(--fs-lg);
  line-height: 1;
  padding: 0 1px;
}

.star-btn.on {
  color: var(--warn);
}

.meta {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.section {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-sm);
  font-size: var(--fs-sm);
  color: var(--muted);
}

.section-actions {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
}

.cap-inline {
  margin-left: 4px;
  font-style: normal;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.cap-inline.warn {
  color: var(--warn);
}

/* 收起状态只占一行：空值不再吃掉 84px */
.negative-line {
  width: 100%;
  padding: 8px 10px;
  text-align: left;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-left: 3px solid var(--danger);
  border-radius: var(--radius-sm);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
}

.negative-line:hover {
  border-color: var(--primary);
  border-left-color: var(--danger);
}

.negative-line span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.negative-line .empty {
  color: var(--muted);
}

.editor {
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
  resize: vertical;
}

/* field-sizing 让输入框跟着内容长；不支持时退化为 min-height + 手动拖拽 */
.editor.pos {
  min-height: 180px;
  field-sizing: content;
  border-left: 3px solid var(--primary);
}

.editor.neg {
  min-height: 72px;
  max-height: 28vh;
  field-sizing: content;
  border-left: 3px solid var(--danger);
  color: var(--danger-text-field);
}

.editor:focus {
  border-color: var(--primary);
}

.params {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: var(--gap-sm);
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--panel-2);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  min-width: 0;
}

.param-label {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.param-value {
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.param-input {
  width: 100%;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  padding: 1px 4px;
  outline: none;
}

.param-input:hover,
.param-input:focus {
  border-color: var(--border);
  background: var(--panel);
}

.note-input {
  width: 100%;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
}

.note-input:focus {
  border-color: var(--primary);
}

.cat-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
}

.cat-chip {
  font-size: var(--fs-xs);
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  transition: 0.12s;
}

.cat-chip:hover {
  border-color: var(--primary);
  color: var(--text);
}

.cat-chip.on {
  background: var(--c, var(--primary));
  border-color: var(--c, var(--primary));
  color: var(--on-primary);
}

/**
 * 浅色主题：分类色来自用户数据，可能是高亮度色，
 * 白字只有 2.15:1。把底色调暗 40%（保留色相）后，8 个默认色板上的白字
 * 均回到 5.4:1 以上。深色主题不命中此规则，外观不变。
 */
:root[data-theme='light'] .cat-chip.on {
  background: color-mix(in srgb, var(--c, var(--primary)) 60%, var(--mix-base-black));
  border-color: color-mix(in srgb, var(--c, var(--primary)) 60%, var(--mix-base-black));
}

.shot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  gap: var(--gap-xs);
}

.shot {
  position: relative;
  display: block;
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--panel-2);
  cursor: pointer;
}

.shot-locate {
  position: absolute;
  right: 2px;
  bottom: 2px;
  padding: 0 4px;
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  background: rgb(22 27 34 / 82%);
  color: var(--text);
  font-size: 10px;
  line-height: 1.5;
  opacity: 0;
  transition: 0.12s;
}

.shot:hover .shot-locate,
.shot:focus-within .shot-locate {
  opacity: 1;
}

.shot img {
  display: block;
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
}

.shot:hover {
  border-color: var(--primary);
}

.muted {
  font-size: var(--fs-sm);
  color: var(--muted);
}

.timestamps {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.spacer {
  flex: 1;
}

.empty.big {
  padding: 60px;
  text-align: center;
}
</style>
