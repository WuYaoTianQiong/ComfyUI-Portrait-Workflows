<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import TagCloud from '../components/TagCloud.vue'
import TagInput from '../components/TagInput.vue'
import MissingImageRunPanel from '../components/MissingImageRunPanel.vue'
import PromptTrialPanel from '../components/PromptTrialPanel.vue'
import PromptCreateModal from '../components/PromptCreateModal.vue'
import PromptImportModal from '../components/PromptImportModal.vue'
import WorkflowPicker from '../components/WorkflowPicker.vue'
import { parseMarkedSegments, renderAllSegments, smartSegmentText } from '../utils/segmentation'
import { confirmDialog } from '../utils/naive'
import { apiDelete, apiGet, apiPost, apiPut } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import { useSettings } from '../composables/useSettings'
import { useGenerate } from '../composables/useGenerate'
import { useToast } from '../composables/useToast'
import { useWorkflows, useWorkflowValidation } from '../composables/useWorkflows'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { readSession, writeSession } from '../composables/useSessionState'
import WorkflowParams from '../components/WorkflowParams.vue'
import BatchReplaceModal from '../components/BatchReplaceModal.vue'
import { statusLabel } from '../utils/format'
import Pager from '../components/Pager.vue'
import { flattenCategories } from '../utils/categories'
import type { CategoryNode, PromptDetail, PromptListPage, PromptListItem, TagRow } from '../api/types'

const { workflowPath, quality, orientation } = useSettings()
const {
  busy: generating,
  job: activeJob,
  error: generateError,
  run,
  runBatch,
  runBatchReplace,
} = useGenerate()

/**
 * 侧栏状态：宽度、折叠、每页条数、排序。
 *
 * 这些是"这台机器的浏览偏好"，不该每次刷新都回到默认值；
 * 存 localStorage，键名统一 `pb.promptUi`。
 */
const UI_KEY = 'pb.promptUi'

interface PromptUi {
  pageSize: number
  sort: string
  order: 'asc' | 'desc'
  collapsed: boolean
  width: number
}

function readUi(): Partial<PromptUi> {
  try {
    const raw = localStorage.getItem(UI_KEY)
    return raw ? (JSON.parse(raw) as Partial<PromptUi>) : {}
  } catch {
    return {}
  }
}

const savedUi = readUi()
const pageSize = ref(savedUi.pageSize ?? 50)
const sort = ref(savedUi.sort ?? 'default')
const order = ref<'asc' | 'desc'>(savedUi.order ?? 'desc')
const sidebarCollapsed = ref(savedUi.collapsed ?? false)
const sidebarWidth = ref(Math.min(600, Math.max(280, savedUi.width ?? 380)))

function saveUi() {
  try {
    localStorage.setItem(
      UI_KEY,
      JSON.stringify({
        pageSize: pageSize.value,
        sort: sort.value,
        order: order.value,
        collapsed: sidebarCollapsed.value,
        width: sidebarWidth.value,
      }),
    )
  } catch {
    /* 隐私模式下忽略 */
  }
}

watch([pageSize, sort, order, sidebarCollapsed, sidebarWidth], saveUi)

const SORT_OPTIONS = [
  { value: 'default', label: '默认' },
  { value: 'created', label: '创建时间' },
  { value: 'name', label: '名称' },
  { value: 'usage', label: '使用次数' },
  { value: 'rating', label: '评级' },
]
const PAGE_SIZES = [20, 50, 100, 200]

/**
 * 会话状态：筛选 / 页码 / 选中项 / 滚动位置。
 *
 * 切页或刷新后回到上次的样子；`pb.promptUi` 只管侧栏布局，这份管"看到哪儿"。
 */
interface PromptSession {
  page: number
  search: string
  categoryId: number | null
  tagIds: number[]
  tagMatch: 'all' | 'any'
  selectedId: number | null
  scrollTop: number
}

const SESSION_KEY = 'pb.session.prompt'
const savedSession = readSession<PromptSession>(SESSION_KEY, {
  page: 1,
  search: '',
  categoryId: null,
  tagIds: [],
  tagMatch: 'all',
  selectedId: null,
  scrollTop: 0,
})

const page = ref(savedSession.page)
const search = ref(savedSession.search)
const categoryId = ref<number | null>(savedSession.categoryId)
const missingOpen = ref(false)
const replaceOpen = ref(false)
const tagIds = ref<number[]>(savedSession.tagIds)
const tagMatch = ref<'all' | 'any'>(savedSession.tagMatch)
const tagPanelOpen = ref(false)
const selectedId = ref<number | null>(savedSession.selectedId)
/** 外部跳转的目标 id：列表变化时据此保留选中，不抢着改选第一条。 */
const jumpTargetId = ref<number | null>(null)
/** 负面提示词默认收起：空值不该占一大块；有内容时显示单行摘要。 */
const negativeExpanded = ref(false)
/** 草稿恢复只针对"刚打开这条提示词"；详情因收藏/置顶等 refetch 时不再弹窗。 */
const draftRestoredFor = ref<number | null>(null)

watch(selectedId, () => {
  negativeExpanded.value = false
  draftRestoredFor.value = null
})

const listEl = ref<HTMLElement | null>(null)
let scrollSaveTimer: number | undefined

function saveSession() {
  writeSession(SESSION_KEY, {
    page: page.value,
    search: search.value,
    categoryId: categoryId.value,
    tagIds: tagIds.value,
    tagMatch: tagMatch.value,
    selectedId: selectedId.value,
    scrollTop: listEl.value?.scrollTop ?? savedSession.scrollTop,
  })
}

watch(
  () =>
    [
      page.value,
      search.value,
      categoryId.value,
      tagIds.value.join(','),
      tagMatch.value,
      selectedId.value,
    ].join('|'),
  saveSession,
)

/** 滚动很频繁，节流后再写，避免每滚一像素都序列化一次。 */
function onListScroll() {
  if (scrollSaveTimer) return
  scrollSaveTimer = window.setTimeout(() => {
    scrollSaveTimer = undefined
    saveSession()
  }, 300)
}

const queryClient = useQueryClient()

const listKey = computed(() => [
  'prompts',
  page.value,
  pageSize.value,
  search.value.trim(),
  categoryId.value,
  tagIds.value.slice().sort((a, b) => a - b).join(','),
  tagMatch.value,
  sort.value,
  order.value,
])

const { data: listData, isFetching } = useQuery<PromptListPage>({
  queryKey: listKey,
  queryFn: () =>
    apiGet<PromptListPage>('/api/prompts', {
      page: page.value,
      page_size: pageSize.value,
      search: search.value.trim(),
      category_id: categoryId.value ?? undefined,
      tag_ids: tagIds.value.join(','),
      tag_match: tagMatch.value,
      sort: sort.value,
      order: order.value,
    }),
  placeholderData: (prev) => prev,
})

const list = computed(() => listData.value?.prompts ?? [])
const total = computed(() => listData.value?.total ?? 0)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

/** 列表数据到位后再恢复滚动位置，否则容器还没高度，scrollTop 会被清 0。 */
let scrollRestored = false
watch(list, async () => {
  if (scrollRestored || !savedSession.scrollTop) return
  scrollRestored = true
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = savedSession.scrollTop
})

const { data: catData } = useQuery<{ categories: CategoryNode[] }>({
  queryKey: ['categories', 'prompt'],
  queryFn: () =>
    apiGet<{ categories: CategoryNode[] }>('/api/categories', {
      tree: true,
      count_scope: 'prompt',
    }),
})

const { data: tagData } = useQuery<{ tags: TagRow[] }>({
  queryKey: ['tags', 'prompt'],
  queryFn: () => apiGet<{ tags: TagRow[] }>('/api/tags', { count_scope: 'prompt' }),
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
const { caps, params } = useWorkflowCaps(workflowPath, allWorkflows)

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
  })
}

/** 树拍平成一维，带 depth 做缩进 —— 分类层级只有两级，递归组件是过度设计。 */
const flatCats = computed(() => flattenCategories(catData.value?.categories))

// ---------------- 详情 ----------------

const { data: detail } = useQuery<PromptDetail>({
  queryKey: computed(() => ['prompt', selectedId.value]),
  queryFn: () => apiGet<PromptDetail>(`/api/prompts/${selectedId.value}`),
  enabled: computed(() => selectedId.value !== null),
})

const draft = ref<PromptDetail | null>(null)

const DRAFT_KEY = (id: number) => `pb.draft.${id}`

function readSavedDraft(id: number): Partial<PromptDetail> | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY(id))
    return raw ? (JSON.parse(raw) as Partial<PromptDetail>) : null
  } catch {
    return null
  }
}

/** 只有这些字段算"用户编辑"；收藏/置顶/评级等元数据变化不应触发脏状态。 */
function editableSnapshot(value: PromptDetail): Partial<PromptDetail> {
  return {
    name: value.name,
    tags: value.tags,
    prompt: value.prompt,
    negative_prompt: value.negative_prompt,
    note: value.note,
    steps: value.steps,
    cfg_scale: value.cfg_scale,
    sampler: value.sampler,
    seed: value.seed,
  }
}

function sameEditable(
  a: Partial<PromptDetail>,
  b: Partial<PromptDetail>,
): boolean {
  const keys: Array<keyof PromptDetail> = [
    'name',
    'tags',
    'prompt',
    'negative_prompt',
    'note',
    'steps',
    'cfg_scale',
    'sampler',
    'seed',
  ]
  return keys.every((key) => a[key] === b[key])
}

/**
 * 详情到达后初始化草稿；只有"首次打开这条提示词"才检查本地草稿。
 *
 * 收藏/置顶/评级等操作会触发详情 refetch，如果每次都弹"恢复草稿"，
 * 用户会被无休止打断。这里用 `draftRestoredFor` 保证每条提示词只问一次。
 */
watch(
  detail,
  async (value) => {
    if (!value) {
      draft.value = null
      return
    }
    const id = selectedId.value
    if (id === null) {
      draft.value = { ...value }
      return
    }

    // 已有未保存编辑：只同步服务端元数据，绝不能用服务端正文覆盖本地正文
    if (draft.value && dirty.value) {
      draft.value = {
        ...draft.value,
        is_favorite: value.is_favorite,
        is_pinned: value.is_pinned,
        rating: value.rating,
        usage_count: value.usage_count,
        updated_at: value.updated_at,
      }
      return
    }

    draft.value = { ...value }
    if (draftRestoredFor.value === id) return
    draftRestoredFor.value = id

    const saved = readSavedDraft(id)
    if (!saved) return
    if (sameEditable(saved, editableSnapshot(value))) {
      localStorage.removeItem(DRAFT_KEY(id))
      return
    }
    const restore = await confirmDialog({
      title: '发现本地草稿',
      content: '这条提示词有未保存的草稿，要恢复吗？',
      positiveText: '恢复草稿',
      negativeText: '丢弃',
      type: 'info',
    })
    if (restore) draft.value = { ...value, ...saved }
    else localStorage.removeItem(DRAFT_KEY(id))
  },
  { immediate: true },
)

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

const dirty = computed(() => {
  if (!draft.value || !detail.value) return false
  return !sameEditable(editableSnapshot(draft.value), editableSnapshot(detail.value))
})

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

/**
 * 标签数组 ↔ `prompts.tags` 文本互转。
 *
 * 拆分规则必须与后端 `services/taxonomy.split_tags` 一致：只按中英文逗号与分号拆，
 * **不拆空格** —— 库里有 "Moody Photography" 这种带空格的标签，拆开就是两个垃圾标签。
 */
function splitTagText(text: string): string[] {
  return text
    .split(/[,，;；]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

const draftTagList = computed<string[]>({
  get: () => splitTagText(draft.value?.tags ?? ''),
  set: (list: string[]) => {
    if (draft.value) draft.value.tags = list.join(',')
  },
})

/** 单条自动归类：按提示词正文里的【类型】数量归入 组合/单项/零散。 */
const autoClassifyMutation = useMutation({
  mutationFn: (id: number) => apiPost(`/api/categories/auto-classify/${id}`),
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

/**
 * 外部（画廊）要求定位到某条提示词时切过去。
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
 * 走 `/api/prompts/{id}/history` —— 从图片跳到提示词之后，最自然的下一步就是
 * 想看看"它到底长什么样"。
 */
interface PromptShot {
  id: number
  filename: string
  subfolder: string
  img_type: string
  width?: number | null
  height?: number | null
}

const { data: shotHistory } = useQuery<{ items: PromptShot[] }>({
  queryKey: computed(() => ['prompt-history', selectedId.value]),
  queryFn: () => apiGet(`/api/prompts/${selectedId.value}/history`, { limit: 24 }),
  enabled: computed(() => selectedId.value !== null),
})

function shotThumb(item: PromptShot): string {
  return `/api/thumbnail?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || '')}&type=${encodeURIComponent(item.img_type || 'output')}&size=200`
}

function shotFull(item: PromptShot): string {
  return `/api/image?filename=${encodeURIComponent(item.filename)}&subfolder=${encodeURIComponent(item.subfolder || '')}&type=${encodeURIComponent(item.img_type || 'output')}`
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
  const { marked, leftover } = parseMarkedSegments(text)
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
  const rendered = renderAllSegments(merged)
  if (!rendered) {
    toast.error('分段结果为空')
    return
  }
  const ok = await confirmDialog({
    title: '智能分段',
    content: `将整理为 ${keys.length} 类：${keys.join('、')}。\n用分段结果替换当前提示词？`,
    positiveText: '替换',
    negativeText: '取消',
  })
  if (!ok || !draft.value) return
  draft.value.prompt = rendered
  toast.success('已按类型分段')
}

/**
 * 草稿自动保存。
 *
 * 编辑到一半刷新页面 / 误关标签，草稿会丢 —— 存一份到 localStorage，
 * 重新打开这条提示词时问要不要恢复。存的是"这台机器上的临时状态"，
 * 不进数据库。
 */
let draftTimer: number | undefined

watch(
  draft,
  (value) => {
    if (!value || selectedId.value === null) return
    // 定时器触发时 selectedId 可能已经切走，必须锁定当时的 id
    const id = selectedId.value
    window.clearTimeout(draftTimer)
    draftTimer = window.setTimeout(() => {
      const snapshot = editableSnapshot(value)
      const server = detail.value ? editableSnapshot(detail.value) : null
      try {
        if (server && sameEditable(snapshot, server)) {
          localStorage.removeItem(DRAFT_KEY(id))
          return
        }
        // 只存可编辑字段，不存 is_pinned / is_favorite 这类元数据
        localStorage.setItem(DRAFT_KEY(id), JSON.stringify(snapshot))
      } catch {
        /* 隐私模式下不可用，忽略 */
      }
    }, 800)
  },
  { deep: true },
)

const saveMutation = useMutation({
  mutationFn: (payload: Partial<PromptDetail>) =>
    apiPut<{ success: boolean }>(`/api/prompts/${selectedId.value}`, payload),
  onSuccess: () => {
    window.clearTimeout(draftTimer)
    const id = selectedId.value
    if (id !== null) localStorage.removeItem(DRAFT_KEY(id))
    invalidateAll(id)
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

function revert() {
  draft.value = detail.value ? { ...detail.value } : null
}

/**
 * 收藏 / 置顶 / 评级只改元数据：本地更新即可。
 * 之前每次都 invalidateAll → 重拉详情 → 触发"恢复草稿"弹窗，纯属自找麻烦。
 */
const favoriteMutation = useMutation({
  mutationFn: () =>
    apiPost<{ success: boolean; is_favorite: boolean }>(
      `/api/prompts/${selectedId.value}/favorite`,
    ),
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
  mutationFn: () =>
    apiPost<{ success: boolean; is_pinned: boolean }>(`/api/prompts/${selectedId.value}/pin`),
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
  mutationFn: (rating: number) =>
    apiPost<{ success: boolean; rating: number }>(
      `/api/prompts/${selectedId.value}/rate`,
      undefined,
      { rating },
    ),
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
  mutationFn: (id: number) => apiDelete(`/api/prompts/${id}`),
  onSuccess: () => {
    selectedId.value = null
    jumpTargetId.value = null
    draft.value = null
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

const selectedIds = ref<Set<number>>(new Set())
/** 批量替换弹窗要读"左侧勾选了哪些"，Set 在模板里不好直接展开。 */
const selectedPromptIds = computed(() => Array.from(selectedIds.value))
const selectedCount = computed(() => selectedIds.value.size)
const allOnPageSelected = computed(
  () => list.value.length > 0 && list.value.every((it) => selectedIds.value.has(it.id)),
)

function toggleSelect(id: number) {
  if (selectedIds.value.has(id)) selectedIds.value.delete(id)
  else selectedIds.value.add(id)
  selectedIds.value = new Set(selectedIds.value)
}

function selectAllOnPage() {
  selectedIds.value = new Set(list.value.map((it) => it.id))
}

function clearSelection() {
  selectedIds.value = new Set()
}

const batchFavoriteMutation = useMutation({
  mutationFn: (ids: number[]) =>
    apiPost<{ success: boolean }>('/api/prompts/batch_favorite', { ids }, { favorite: true }),
  onSuccess: () => {
    clearSelection()
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
  },
})

const batchDeleteMutation = useMutation({
  mutationFn: (ids: number[]) =>
    apiPost<{ success: boolean; deleted: number }>('/api/prompts/batch_delete', { ids }),
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
  })
  if (!ok) return
  runBatch(ids, {
    workflowPath: workflowPath.value,
    quality: caps.value.quality ? quality.value : '4K',
    orientation: caps.value.orientation ? orientation.value : 'keep',
  })
}

/**
 * 批量替换碎片后出图：只替换本次注入的文本，不写回提示词库。
 *
 * 每条提示词仍用自己保存的 seed/steps/cfg，便于对比"换了一片之后"的效果。
 */
async function onBatchReplace(payload: {
  type: string
  items: Array<{ promptId: number; seed: number; promptOverride: string }>
}) {
  if (!workflowPath.value) {
    toast.error('请先选择工作流')
    return
  }
  if (!caps.value.prompt) {
    toast.error('该工作流不注入提示词，无法替换出图')
    return
  }
  if (!payload.items.length) return
  const wfName = workflowPath.value.split(/[\\/]/).pop() || '未选择'
  const ok = await confirmDialog({
    title: '批量替换碎片并出图',
    content:
      `把 ${payload.items.length} 条提示词里的【${payload.type}】替换成同一段内容，` +
      `用「${wfName}」出图。\n\n只影响本次出图，不会写回提示词库。`,
    positiveText: '开始出图',
    negativeText: '取消',
  })
  if (!ok) return
  runBatchReplace(payload.items, {
    workflowPath: workflowPath.value,
    quality: caps.value.quality ? quality.value : '4K',
    orientation: caps.value.orientation ? orientation.value : 'keep',
    title: `批量替换【${payload.type}】 ${payload.items.length} 条`,
  })
  replaceOpen.value = false
  toast.success(`已提交 ${payload.items.length} 条替换任务`)
}

// ---------------- 导入 / 导出 ----------------

const fileInput = ref<HTMLInputElement | null>(null)
const importMessage = ref('')

function exportPrompts() {
  window.open('/api/prompts/export', '_blank')
}

const importMutation = useMutation({
  mutationFn: (prompts: unknown[]) =>
    apiPost<{ success: boolean; imported: number; message: string }>('/api/prompts/import', {
      prompts,
    }),
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

function onCategorySelect(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  selectCategory(value ? Number(value) : null)
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

const tagById = computed(() => new Map((tagData.value?.tags ?? []).map((t) => [t.id, t])))
const activeCategory = computed(() => flatCats.value.find((c) => c.id === categoryId.value) ?? null)

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
  if (scrollSaveTimer) window.clearTimeout(scrollSaveTimer)
  saveSession()
  stopResize()
})
</script>

<template>
  <div class="prompt-page">
    <aside v-if="!sidebarCollapsed" class="sidebar" :style="{ width: `${sidebarWidth}px` }">
      <div class="side-head">
        <button
          class="btn btn-sm collapse-btn"
          title="收起侧栏"
          @click="sidebarCollapsed = true"
        >
          «
        </button>
        <input
          v-model="search"
          class="search"
          type="search"
          placeholder="搜索名称 / 内容 / 标签 / 备注…"
          @input="page = 1"
        />
      </div>

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
        <button
          class="btn btn-sm"
          title="批量粘贴 AI 润色后的多条提示词，自动分段后入库"
          @click="importOpen = true"
        >
          智能导入
        </button>
        <button
          class="btn btn-sm"
          title="给「有提示词但没出图」的条目补图"
          @click="missingOpen = true"
        >
          补跑缺图
        </button>
        <button
          class="btn btn-sm"
          title="把当前筛选下所有提示词的某一类碎片换成同一段，再批量出图（不写回库）"
          @click="replaceOpen = true"
        >
          批量替换
        </button>
        <input
          ref="fileInput"
          type="file"
          accept="application/json,.json"
          hidden
          @change="onImportFile"
        />
      </div>

      <div class="side-filters">
        <select class="cat-select" :value="categoryId ?? ''" title="分类" @change="onCategorySelect">
          <option value="">全部分类</option>
          <option v-for="cat in flatCats" :key="cat.id" :value="cat.id">
            {{ '　'.repeat(cat.depth) }}{{ cat.name }}（{{ cat.prompt_count }}）
          </option>
        </select>

        <select v-model="sort" title="排序" @change="page = 1">
          <option v-for="opt in SORT_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
        <button
          v-if="sort !== 'default'"
          class="btn btn-sm order-btn"
          :title="order === 'desc' ? '降序（点切换）' : '升序（点切换）'"
          @click="order = order === 'desc' ? 'asc' : 'desc'"
        >
          {{ order === 'desc' ? '↓' : '↑' }}
        </button>
        <button
          class="btn btn-sm tag-toggle"
          :class="{ active: tagPanelOpen }"
          title="标签筛选"
          @click="tagPanelOpen = !tagPanelOpen"
        >
          标签<span v-if="tagIds.length" class="badge">{{ tagIds.length }}</span>
        </button>
      </div>

      <div v-if="tagPanelOpen" class="tag-panel">
        <TagCloud
          :tags="tagData?.tags ?? []"
          :selected="tagIds"
          :match="tagMatch"
          empty-text="暂无带提示词的标签"
          @toggle="toggleTag"
          @update:match="(m) => { tagMatch = m; page = 1 }"
        />
        <button class="btn btn-sm full" @click="tagIds = []; page = 1">清空标签</button>
      </div>

      <div
        v-if="categoryId !== null || tagIds.length"
        class="active-filters"
      >
        <button
          v-if="activeCategory"
          class="filter-chip"
          :title="`清除分类：${activeCategory.name}`"
          @click="selectCategory(null)"
        >
          {{ activeCategory.name }} ×
        </button>
        <button
          v-for="id in tagIds"
          :key="id"
          class="filter-chip"
          :title="`清除标签：${tagById.get(id)?.name ?? id}`"
          @click="toggleTag(id)"
        >
          {{ tagById.get(id)?.name ?? `#${id}` }} ×
        </button>
        <button class="btn btn-sm ghost" @click="clearFilters">全部清除</button>
      </div>

      <div v-if="importMessage" class="import-line">{{ importMessage }}</div>

      <div v-if="selectedCount" class="bulk">
        <span class="bulk-count">已选 <b>{{ selectedCount }}</b> 条</span>
        <button class="btn btn-sm" @click="selectAllOnPage">全选本页</button>
        <button class="btn btn-sm" @click="clearSelection">取消</button>
        <span class="spacer" />
        <button class="btn btn-sm" @click="batchFavorite">收藏</button>
        <button
          class="btn btn-sm primary"
          :class="{ loading: generating }"
          :disabled="generating"
          @click="batchGenerate"
        >
          批量出图
        </button>
        <button class="btn btn-sm danger" @click="batchDelete">删除</button>
      </div>

      <div ref="listEl" class="list" @scroll.passive="onListScroll">
        <div
          v-for="item in list"
          :key="item.id"
          class="row"
          :class="{ active: selectedId === item.id, picked: selectedIds.has(item.id) }"
          @click="selectRow(item.id)"
        >
          <button
            class="row-check"
            :class="{ on: selectedIds.has(item.id) }"
            :title="selectedIds.has(item.id) ? '取消选择' : '选择'"
            @click.stop="toggleSelect(item.id)"
          >
            ✓
          </button>
          <div class="row-body">
            <div class="row-title">
              <span v-if="item.is_pinned" class="pin" title="置顶">📌</span>
              <span v-if="item.is_favorite" class="star" title="收藏">★</span>
              <span class="name">{{ item.name || `#${item.id}` }}</span>
              <span v-if="item.rating" class="rating">{{ '★'.repeat(item.rating) }}</span>
            </div>
            <div class="row-preview">{{ item.prompt_preview }}</div>
            <div class="row-meta">
              <span v-if="item.steps" class="badge">{{ item.steps }}步</span>
              <span v-if="item.sampler" class="sampler">{{ item.sampler }}</span>
              <span v-for="tag in rowTags(item)" :key="tag" class="tag">{{ tag }}</span>
            </div>
          </div>
        </div>

        <EmptyState v-if="!list.length && !isFetching" size="big" text="没有符合条件的提示词" />
      </div>

      <div class="pager-row">
        <button
          class="btn btn-sm select-all"
          :title="allOnPageSelected ? '取消本页选择' : '选中当前页全部条目'"
          @click="allOnPageSelected ? clearSelection() : selectAllOnPage()"
        >
          {{ allOnPageSelected ? '取消本页' : '全选本页' }}
        </button>
        <span class="count">{{ total }} 条<span v-if="isFetching"> · 加载中</span></span>
        <span class="spacer" />
        <Pager compact :page="page" :total-pages="totalPages" @update:page="page = $event" />
        <select v-model.number="pageSize" class="page-size" title="每页条数" @change="page = 1">
          <option v-for="size in PAGE_SIZES" :key="size" :value="size">{{ size }} 条/页</option>
        </select>
      </div>
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
            <WorkflowPicker v-model="workflowPath" :workflows="workflows" />
            <WorkflowParams
              v-model:quality="quality"
              v-model:orientation="orientation"
              :workflow-path="workflowPath"
              :caps="caps"
              :params="params"
            />
            <span
              v-if="workflowPath && caps.prompt && !caps.negative"
              class="cap-hint"
              title="该工作流不接收负面提示词"
            >
              不支持负面
            </span>
            <span
              v-if="workflowPath && !caps.prompt"
              class="cap-hint warn"
              title="该工作流不注入提示词"
            >
              不注入提示词
            </span>
            <button
              class="btn btn-sm"
              title="复制正向提示词"
              @click="copyText(draft.prompt, '提示词')"
            >
              复制
            </button>
            <button class="btn btn-sm" title="按关键词把提示词拆成【类型】结构" @click="smartSegment">
              ✂ 智能分段
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
            <span class="spacer" />
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
                  <i v-if="!caps.negative" class="cap-inline">该工作流不注入</i>
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
                    (caps.negative ? '（空）点击添加' : '（空，仅归档，不参与出图）')
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
                <span>出图历史（{{ shotHistory?.items?.length ?? 0 }} 张）</span>
              </div>
              <div v-if="shotHistory?.items?.length" class="shot-grid">
                <a
                  v-for="shot in shotHistory.items"
                  :key="shot.id"
                  class="shot"
                  :href="shotFull(shot)"
                  target="_blank"
                  :title="shot.filename"
                >
                  <img :src="shotThumb(shot)" :alt="shot.filename" loading="lazy" />
                </a>
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
      :selected-ids="selectedPromptIds"
      :workflow-path="workflowPath"
      :quality="quality"
      :orientation="orientation"
      :caps="caps"
      @close="replaceOpen = false"
      @submit="onBatchReplace"
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

.side-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
}

.collapse-btn {
  flex: none;
}

.search {
  flex: 1;
  min-width: 0;
}

/* 5 个按钮平分整行宽度；侧栏拖窄时自动折成多行，仍然等宽 */
.side-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(60px, 1fr));
  gap: var(--gap-xs);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
}

.side-actions .btn {
  width: 100%;
  min-width: 0;
  padding: 3px 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.side-filters {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
}

.side-filters select {
  min-width: 0;
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px 6px;
  font: inherit;
  font-size: var(--fs-sm);
}

.cat-select {
  flex: 1;
}

.order-btn {
  flex: none;
  padding: 2px 7px;
}

.tag-toggle {
  flex: none;
}

.tag-toggle.active {
  border-color: var(--primary);
  color: var(--primary);
}

.tag-panel {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap);
  border-bottom: 1px solid var(--border);
  background: var(--panel-2);
  max-height: 42vh;
  overflow-y: auto;
}

.tag-panel .full {
  width: 100%;
}

.badge {
  display: inline-grid;
  place-items: center;
  min-width: 15px;
  height: 15px;
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  line-height: 1;
}

.active-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  padding: var(--gap-xs) var(--gap);
  border-bottom: 1px solid var(--border);
}

.filter-chip {
  border: 1px solid var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
  border-radius: 999px;
  padding: 1px 8px;
  font-size: var(--fs-xs);
}

.btn.ghost {
  border-color: transparent;
  color: var(--muted);
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

.list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* 批量操作条：浮在页面底部居中。 */
.bulk {
  position: fixed;
  bottom: 22px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 50;
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm) var(--gap-lg);
  border-radius: 999px;
  background: var(--panel-3);
  border: 1px solid var(--border-strong);
  box-shadow: var(--shadow);
  font-size: var(--fs-sm);
  white-space: nowrap;
}

.bulk > button {
  flex: none;
}

.bulk-count b {
  color: var(--primary);
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.btn.primary:disabled {
  opacity: 0.4;
}

.btn.danger {
  border-color: var(--danger);
  color: #fecaca;
}

.btn.danger:hover {
  background: var(--danger-soft);
}

.row {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-sm);
  border-bottom: 1px solid var(--border);
  padding: var(--gap-sm) var(--gap);
  transition: 0.1s;
  cursor: pointer;
}

.row:hover {
  background: var(--panel-2);
}

.row.active {
  background: var(--primary-soft);
  box-shadow: inset 2px 0 0 var(--primary);
}

.row.picked {
  background: rgba(99, 102, 241, 0.08);
}

.row-check {
  flex: none;
  width: 18px;
  height: 18px;
  margin-top: 2px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  background: transparent;
  color: transparent;
  font-size: var(--fs-xs);
  transition: 0.12s;
}

.row:hover .row-check,
.row-check.on {
  border-color: var(--primary);
}

.row-check.on {
  background: var(--primary);
  color: #fff;
}

.row-body {
  flex: 1;
  min-width: 0;
}

.row-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-sm);
  font-weight: 600;
}

.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pin,
.star {
  font-size: var(--fs-xs);
  color: #fbbf24;
}

.rating {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: #fbbf24;
}

/* 旧版是 2 行截断；单行时一页能看更多，但辨识度差很多 */
.row-preview {
  font-size: var(--fs-sm);
  color: var(--muted);
  line-height: 1.45;
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.row-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 5px;
  font-size: var(--fs-xs);
}

.row-meta .badge {
  margin: 0;
  min-width: 0;
  height: auto;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(34, 197, 94, 0.14);
  color: var(--success);
}

.sampler {
  color: var(--muted);
}

.row-meta .tag {
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(99, 102, 241, 0.12);
  color: var(--primary);
}

/* 翻页行：全选 / 总数 / 翻页 / 每页条数，都在侧栏底部一行里 */
.pager-row {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  padding: var(--gap-sm) var(--gap);
  border-top: 1px solid var(--border);
}

.select-all {
  flex: none;
  white-space: nowrap;
}

.page-size {
  flex: none;
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px 4px;
  font: inherit;
  font-size: var(--fs-xs);
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
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-sm);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
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
  border-radius: 999px;
  padding: 1px 7px;
  white-space: nowrap;
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

.dirty-badge {
  flex: none;
  padding: 1px 7px;
  border: 1px solid var(--warn);
  border-radius: 999px;
  color: var(--warn);
  font-size: var(--fs-xs);
  font-weight: 400;
  white-space: nowrap;
}

.name-input {
  flex: 1;
  min-width: 0;
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
  color: var(--border-strong);
  font-size: var(--fs-lg);
  line-height: 1;
  padding: 0 1px;
}

.star-btn.on {
  color: #fbbf24;
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
  color: #f5a0a0;
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
  gap: 4px;
}

.cat-chip {
  font-size: var(--fs-xs);
  padding: 2px 9px;
  border-radius: 999px;
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
  color: #fff;
}

.shot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  gap: 4px;
}

.shot {
  display: block;
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--panel-2);
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
