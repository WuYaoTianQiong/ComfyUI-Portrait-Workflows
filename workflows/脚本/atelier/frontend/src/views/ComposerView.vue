<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'

import { useRouter } from 'vue-router'
import TagCloud from '../components/TagCloud.vue'
import ComposerResultCenterModal from '../components/ComposerResultCenterModal.vue'
import WorkflowPicker from '../components/WorkflowPicker.vue'
import FragmentDetailModal from '../components/FragmentDetailModal.vue'
import { flattenCategories } from '../utils/categories'
import { apiDelete, apiGet, apiPost } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import Modal from '../components/Modal.vue'
import { useSettings } from '../composables/useSettings'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import WorkflowParams from '../components/WorkflowParams.vue'
import { useGenerate } from '../composables/useGenerate'
import { useWorkflows, customWorkflowContent } from '../composables/useWorkflows'
import { FRAGMENT_TYPES } from '../constants'
import { useToast } from '../composables/useToast'
import { readSession, writeSession } from '../composables/useSessionState'
import { confirmDialog, inputDialog } from '../utils/naive'
import type { CategoryNode, TagRow } from '../api/types'

interface FragmentItem {
  fragment_id?: number
  prompt_id: number | null
  prompt_name: string
  type: string
  content: string
  tags: string
  source: 'prompt' | 'library'
  dup_count: number
}

// 组合器有自己的一份工作流，不跟提示词页/换脸页联动
const { composerWorkflowPath, quality, orientation } = useSettings()
const workflowPath = composerWorkflowPath
const { busy: generating, job: activeJob, error: generateError, submitAndTrack } = useGenerate()
const { workflows, allWorkflows } = useWorkflows(composerWorkflowPath)
/** 画质档位与横竖按工作流能力生成：不支持的项直接隐藏，不发无效参数。 */
const { caps, qualityOptions } = useWorkflowCaps(workflowPath, allWorkflows)
const router = useRouter()
const resultOpen = ref(false)
const resultTab = ref<'canvas' | 'random' | 'job'>('canvas')

/** 会话状态：检索条件、负向提示词、随机组数、各列已加载条数。 */
interface ComposerSession {
  search: string
  categoryId: number | null
  tagIds: number[]
  tagMatch: 'all' | 'any'
  negativePrompt: string
  randomCount: number
  limits: Record<string, number>
}

const SESSION_KEY = 'pb.session.composer'
const savedSession = readSession<ComposerSession>(SESSION_KEY, {
  search: '',
  categoryId: null,
  tagIds: [],
  tagMatch: 'all',
  negativePrompt: '',
  randomCount: 1,
  limits: {},
})

/** 检索条常驻在顶部（旧版就是常驻的 25px 条），标签放抽屉。 */
const search = ref(savedSession.search)
const categoryId = ref<number | null>(savedSession.categoryId)
const tagIds = ref<number[]>(savedSession.tagIds)
const tagMatch = ref<'all' | 'any'>(savedSession.tagMatch)
const filtersOpen = ref(false)
const settingsOpen = ref(false)

const toast = useToast()

// ---------------- 碎片池 ----------------

const { data: fragmentData, isFetching } = useQuery<{
  grouped: Record<string, FragmentItem[]>
  fragment_count: number
}>({
  queryKey: computed(() => [
    'composer-fragments',
    search.value.trim(),
    categoryId.value,
    tagIds.value.slice().sort((a, b) => a - b).join(','),
  ]),
  queryFn: () =>
    apiGet('/api/composer/fragments', {
      search: search.value.trim(),
      category_id: categoryId.value ?? undefined,
      tag_ids: tagIds.value.length ? tagIds.value.join(',') : undefined,
    }),
})

const grouped = computed<Record<string, FragmentItem[]>>(() => fragmentData.value?.grouped ?? {})
const fragmentTotal = computed(() => fragmentData.value?.fragment_count ?? 0)

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

const flatCats = computed(() => flattenCategories(catData.value?.categories))

/**
 * 每列分批加载：首屏 40 个，滚到列底自动再加载 40 个。
 *
 * 线上碎片池有 2100+ 个（8 类各 230–300），8 列全铺会产生 6000+ DOM 节点，
 * 首屏会卡；旧版要求滚到列底再手动点「展开全部」，既难发现又会一次性铺满。
 */
const PAGE_SIZE = 40
/** 每列已加载条数，缺省 40；触底时按 PAGE_SIZE 递增。 */
const limits = ref<Record<string, number>>(savedSession.limits)

function limitOf(type: string): number {
  return limits.value[type] ?? PAGE_SIZE
}

function visibleFrags(type: string): FragmentItem[] {
  return (grouped.value[type] ?? []).slice(0, limitOf(type))
}

function hasMore(type: string): boolean {
  return (grouped.value[type] ?? []).length > limitOf(type)
}

function loadMore(type: string) {
  if (!hasMore(type)) return
  limits.value = { ...limits.value, [type]: limitOf(type) + PAGE_SIZE }
}

/** 筛选条件变了就从第一批重新开始，免得沿用上一轮很深的加载量。 */
watch(
  () => [
    search.value,
    categoryId.value,
    tagIds.value.slice().sort((a, b) => a - b).join(','),
  ].join('|'),
  () => {
    limits.value = {}
  },
)

/**
 * 触底自动加载：列底那个「加载更多」按钮同时是 observer 的哨兵。
 * 按钮保留下来当兜底（observer 不可用 / 没滚到位时仍可手动点）。
 */
const moreEls = new Map<string, HTMLElement>()
let moreObserver: IntersectionObserver | null = null

function setMoreEl(type: string, el: Element | ComponentPublicInstance | null) {
  const prev = moreEls.get(type)
  if (prev) moreObserver?.unobserve(prev)
  if (el instanceof HTMLElement) {
    moreEls.set(type, el)
    moreObserver?.observe(el)
  } else {
    moreEls.delete(type)
  }
}

onMounted(() => {
  // happy-dom / 老浏览器没有 IntersectionObserver：保留手动按钮即可
  if (typeof IntersectionObserver === 'undefined') return
  moreObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const type = (entry.target as HTMLElement).dataset.type
        if (entry.isIntersecting && type) loadMore(type)
      }
    },
    // 提前一屏左右触发，滚动到底时下一批通常已经在了
    { rootMargin: '160px' },
  )
  for (const el of moreEls.values()) moreObserver.observe(el)
})

onBeforeUnmount(() => {
  moreObserver?.disconnect()
  moreObserver = null
  moreEls.clear()
})

// ---------------- 画布 ----------------

/** 画布槽位：除了内容还要记住来源，保存模板时要用 prompt_id 建立引用关系。 */
interface CanvasSlot {
  content: string
  promptId: number | null
  source: 'prompt' | 'library' | 'custom'
}

/** 每个类型一列；同类型只能有一个碎片（这是【类型】格式的约束）。 */
const CANVAS_KEY = 'pb.composerCanvas'

function readCanvas(): Record<string, CanvasSlot> {
  try {
    const raw = localStorage.getItem(CANVAS_KEY)
    const parsed = raw ? (JSON.parse(raw) as Record<string, CanvasSlot>) : {}
    if (!parsed || typeof parsed !== 'object') return {}
    const out: Record<string, CanvasSlot> = {}
    for (const [type, slot] of Object.entries(parsed)) {
      if ((FRAGMENT_TYPES as readonly string[]).includes(type) && slot?.content) out[type] = slot
    }
    return out
  } catch {
    return {}
  }
}

const canvas = ref<Record<string, CanvasSlot>>(readCanvas())

// 刷新/切页不再丢画布（旧版把选中状态存进 UiState，重构时漏了）
watch(
  canvas,
  (value: Record<string, CanvasSlot>) => {
    try {
      localStorage.setItem(CANVAS_KEY, JSON.stringify(value))
    } catch {
      /* 隐私模式下忽略 */
    }
  },
  { deep: true },
)

const canvasTypes = computed(() => FRAGMENT_TYPES.filter((t) => canvas.value[t]))
const canvasCount = computed(() => canvasTypes.value.length)

/** 渲染成标准文本：与后端 `composition.render` 完全一致的格式。 */
const composedPrompt = computed(() =>
  canvasTypes.value.map((t) => `【${t}】\n${canvas.value[t].content}`).join('\n\n'),
)

function pick(item: FragmentItem) {
  canvas.value = {
    ...canvas.value,
    [item.type]: { content: item.content, promptId: item.prompt_id, source: item.source },
  }
}

// ---------------- 自定义碎片 / 复制 / 存为提示词 ----------------

/**
 * 自定义碎片：直接手写一段填进某个槽位。
 *
 * 旧版有「自定义碎片」（`_addCustomFragment`）：既不来自提示词也不来自碎片库，
 * 就是用户当场写的一段；写完还能「存进碎片库」（`_saveCustomFragmentToLibrary`）。
 * 新前端之前两样都没有 —— 画布只能填现成的碎片，拼不出"自己写的那一段"。
 */
const customType = ref('')
const customText = ref('')
const customOpen = ref(false)

function openCustom(type: string) {
  customType.value = type
  const slot = canvas.value[type]
  customText.value = slot && slot.source === 'custom' ? slot.content : ''
  customOpen.value = true
}

function applyCustom() {
  const text = customText.value.trim()
  if (!text || !customType.value) return
  canvas.value = {
    ...canvas.value,
    [customType.value]: { content: text, promptId: null, source: 'custom' },
  }
  customOpen.value = false
}

/** 把槽位里的自定义碎片存进碎片库（之后就能像别的碎片一样用）。 */
async function saveCustomToLibrary() {
  const type = customType.value
  const text = customText.value.trim()
  if (!text || !type) return
  try {
    await apiPost('/api/fragments', {
      name: '',
      fragment_type: type,
      content: text,
      tags: '',
    })
    toast.success(`已存进碎片库（${type}）`)
    // 分类与标签页的碎片列表是另一个缓存根，两边都要刷
    queryClient.invalidateQueries({ queryKey: ['composer-fragments'] })
    queryClient.invalidateQueries({ queryKey: ['fragments'] })
  } catch (e) {
    toast.error(`存库失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

/** 复制到剪贴板（组合结果 / 单个槽位）。 */
async function copyText(text: string, label: string) {
  if (!text) {
    toast.error('没有可复制的内容')
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
 * 把画布上的组合结果存成一条提示词。
 *
 * 与「另存为模板」不同：模板存的是**碎片引用**（要求每片都来自提示词，否则
 * 建不了引用关系），这里存的是**组合好的文本** —— 所以碎片库碎片和自定义碎片
 * 都能存进去。
 */
async function saveAsPrompt() {
  if (!composedPrompt.value) {
    toast.error('画布是空的')
    return
  }
  const name = await inputDialog({
    title: '存为提示词',
    placeholder: '提示词名称',
    positiveText: '保存',
    negativeText: '取消',
  })
  if (!name) return
  try {
    await apiPost('/api/prompts', {
      name: name.trim(),
      prompt: composedPrompt.value,
      negative_prompt: negativePrompt.value,
      auto_categorize: true,
    })
    toast.success('已存进提示词库')
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    // 新提示词会带标签，标签云与分类计数都会变
    queryClient.invalidateQueries({ queryKey: ['tags'] })
    queryClient.invalidateQueries({ queryKey: ['categories'] })
  } catch (e) {
    toast.error(`保存失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

function unpick(type: string) {
  const next = { ...canvas.value }
  delete next[type]
  canvas.value = next
}

const negativePrompt = ref(savedSession.negativePrompt)

// ---------------- 跑图 ----------------

/** 画布上的碎片作为"固定碎片"，其余类型由后端随机填充。 */
const randomCount = ref(savedSession.randomCount)

watch(
  [search, categoryId, tagIds, tagMatch, negativePrompt, randomCount, limits],
  () => {
    writeSession(SESSION_KEY, {
      search: search.value,
      categoryId: categoryId.value,
      tagIds: tagIds.value,
      tagMatch: tagMatch.value,
      negativePrompt: negativePrompt.value,
      randomCount: randomCount.value,
      limits: limits.value,
    })
  },
  { deep: true },
)

/**
 * 固定列：随机组合时该列保持当前选中，不参与随机。
 *
 * 与旧版 `_composerFixed` 等价；只把**固定且有内容**的列发给后端，
 * 未固定的列即使画布里有内容也会被随机替换 —— 这正是"随机"的语义。
 */
const PIN_KEY = 'pb.composerPinned'
const pinned = ref<string[]>([])

try {
  const raw = localStorage.getItem(PIN_KEY)
  const parsed = raw ? (JSON.parse(raw) as string[]) : []
  pinned.value = Array.isArray(parsed)
    ? parsed.filter((t) => (FRAGMENT_TYPES as readonly string[]).includes(t))
    : []
} catch {
  pinned.value = []
}

function togglePin(type: string) {
  pinned.value = pinned.value.includes(type)
    ? pinned.value.filter((t) => t !== type)
    : [...pinned.value, type]
  try {
    localStorage.setItem(PIN_KEY, JSON.stringify(pinned.value))
  } catch {
    /* 忽略 */
  }
}

/** 每列滚动容器：随机后把选中卡片滚到可视区中间。 */
const reelBodies = new Map<string, HTMLElement>()

function setReelBody(type: string, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLElement) reelBodies.set(type, el)
  else reelBodies.delete(type)
}

interface Picked {
  content: string
  promptId: number | null
  source: CanvasSlot['source']
  index: number
}

/**
 * 为某一列抽一个碎片：固定列沿用画布内容，其余从当前筛选结果里随机。
 * `index` 是它在 grouped 里的位置，用来在渲染后滚动定位。
 */
function pickForType(type: string): Picked | null {
  const slot = canvas.value[type]
  const list = grouped.value[type] ?? []
  if (pinned.value.includes(type) && slot?.content) {
    return {
      content: slot.content,
      promptId: slot.promptId,
      source: slot.source,
      index: list.findIndex((f) => f.content === slot.content),
    }
  }
  if (!list.length) {
    return slot?.content ? { ...slot, index: -1 } : null
  }
  const i = Math.floor(Math.random() * list.length)
  const item = list[i]
  return { content: item.content, promptId: item.prompt_id, source: item.source, index: i }
}

/** 拼成与后端 `composition.render` 一致的【类型】格式。 */
function buildCombo(): string {
  const parts: string[] = []
  for (const type of FRAGMENT_TYPES) {
    const picked = pickForType(type)
    if (picked?.content) parts.push(`【${type}】\n${picked.content}`)
  }
  return parts.join('\n\n')
}

/**
 * 🎲 随机一版：本地抽，不提交任务。
 *
 * 旧版 `randomComposer` 的"老虎机"体验：抽完每列滚到选中卡片并高亮。
 */
async function rollOne() {
  const next = { ...canvas.value }
  for (const type of FRAGMENT_TYPES) {
    const picked = pickForType(type)
    if (!picked?.content) continue
    next[type] = {
      content: picked.content,
      promptId: picked.promptId,
      source: picked.source,
    }
    // 抽到当前批次之后时，先把该列加载到那一批，否则卡片根本没渲染，无法滚动定位
    if (picked.index >= limitOf(type)) {
      limits.value = { ...limits.value, [type]: picked.index + PAGE_SIZE }
    }
  }
  canvas.value = next
  await nextTick()
  for (const type of FRAGMENT_TYPES) {
    const body = reelBodies.get(type)
    body?.querySelector<HTMLElement>('.card.on')?.scrollIntoView({
      block: 'center',
      behavior: 'smooth',
    })
  }
  toast.info('已随机组合一版（未出图）')
}

// ---------------- 批量随机：先预览，确认后才出图 ----------------

/** 碎片全文弹层的数据形状（与 FragmentDetailModal 的结构一致）。 */
interface FragmentDetail {
  type: string
  content: string
  source: 'prompt' | 'library' | 'custom'
  promptId: number | null
  promptName: string
  dupCount: number
}

const randomCombos = ref<string[]>([])
/** 结果中心随机页里勾选的组（下标）；默认全选。 */
const selectedCombos = ref<number[]>([])
const detailOpen = ref(false)
const detailFrag = ref<FragmentDetail | null>(null)

/** 打开结果中心（画布页）。 */
function openResultCanvas() {
  resultTab.value = 'canvas'
  resultOpen.value = true
}

function openRandomPreview() {
  randomCombos.value = Array.from({ length: randomCount.value }, buildCombo)
  selectedCombos.value = randomCombos.value.map((_, i) => i)
  resultTab.value = 'random'
  resultOpen.value = true
}

/** 结果中心里改了组数后重新生成。 */
function regenerateCombos() {
  randomCombos.value = Array.from({ length: randomCount.value }, buildCombo)
  selectedCombos.value = randomCombos.value.map((_, i) => i)
}

function setRandomCount(n: number) {
  randomCount.value = n
}

function rerollCombo(index: number) {
  const next = [...randomCombos.value]
  next[index] = buildCombo()
  randomCombos.value = next
}

function removeCombo(index: number) {
  randomCombos.value = randomCombos.value.filter((_, i) => i !== index)
  // 删除后下标会前移，勾选集合要同步调整
  selectedCombos.value = selectedCombos.value
    .filter((i) => i !== index)
    .map((i) => (i > index ? i - 1 : i))
}

function toggleCombo(index: number) {
  selectedCombos.value = selectedCombos.value.includes(index)
    ? selectedCombos.value.filter((i) => i !== index)
    : [...selectedCombos.value, index]
}

/** 双击卡片查看全文（卡片只有 3 行，长碎片看不全）。 */
function openDetail(item: FragmentItem) {
  detailFrag.value = {
    type: item.type,
    content: item.content,
    source: item.source,
    promptId: item.prompt_id,
    promptName: item.prompt_name,
    dupCount: item.dup_count,
  }
  detailOpen.value = true
}

function pickFromDetail() {
  if (!detailFrag.value) return
  const f = detailFrag.value
  canvas.value = {
    ...canvas.value,
    [f.type]: { content: f.content, promptId: f.promptId, source: f.source },
  }
  detailOpen.value = false
}

/** 锁定/解锁一列；锁定前必须有内容，否则随机时会静默失效。 */
function toggleLock(type: string) {
  if (!pinned.value.includes(type) && !canvas.value[type]?.content) {
    toast.error(`「${type}」还没有选碎片，先选一个再锁定`)
    return
  }
  togglePin(type)
}

// ---------------- 检索高亮与定位 ----------------

const keyword = computed(() => search.value.trim())

function isHit(content: string): boolean {
  const k = keyword.value.toLowerCase()
  return !!k && content.toLowerCase().includes(k)
}

/** 把正文按关键词切成片段，命中的片段单独着色（不拼 HTML，避免 XSS）。 */
function textParts(text: string): Array<{ text: string; hit: boolean }> {
  const k = keyword.value
  if (!k) return [{ text, hit: false }]
  const parts: Array<{ text: string; hit: boolean }> = []
  const lower = text.toLowerCase()
  const kl = k.toLowerCase()
  let from = 0
  while (from < text.length) {
    const at = lower.indexOf(kl, from)
    if (at < 0) break
    if (at > from) parts.push({ text: text.slice(from, at), hit: false })
    parts.push({ text: text.slice(at, at + k.length), hit: true })
    from = at + k.length
  }
  if (from < text.length) parts.push({ text: text.slice(from), hit: false })
  return parts.length ? parts : [{ text, hit: false }]
}

/** 搜索后把每列第一条命中的卡片滚到可视区。 */
async function locateFirstHit() {
  if (!keyword.value) return
  await nextTick()
  for (const type of FRAGMENT_TYPES) {
    const body = reelBodies.get(type)
    body?.querySelector<HTMLElement>('.card.hit')?.scrollIntoView({ block: 'center' })
  }
}

watch(() => fragmentData.value, () => void locateFirstHit())

// ---------------- 组合模板 ----------------

interface TemplateFragmentRow {
  id: number
  prompt_id: number | null
  fragment_type: string
  content: string
  source_exists: boolean
  source_name: string
}

interface TemplateRow {
  id: number
  name: string
  fragment_count: number
  fragments?: TemplateFragmentRow[]
}

const queryClient = useQueryClient()

const { data: templateData } = useQuery<{ templates: TemplateRow[] }>({
  queryKey: ['templates'],
  queryFn: () => apiGet('/api/templates'),
})

const templates = computed(() => templateData.value?.templates ?? [])
const selectedTemplateId = ref<number | null>(null)
const templateSearch = ref('')
const templateOpen = ref(false)

/** 线上有 381 个模板，下拉直接铺开根本找不到；加本地过滤（数据量小，不必走接口）。 */
const filteredTemplates = computed(() => {
  const keyword = templateSearch.value.trim()
  if (!keyword) return templates.value
  return templates.value.filter((t) => t.name.includes(keyword))
})

/**
 * 套用模板：把模板里的碎片引用填回画布。
 *
 * 模板是**引用式**的（存 prompt_id + 类型，内容实时解析），所以套用拿到的是
 * 提示词当前的内容，而不是保存模板那一刻的快照 —— 源提示词改过，模板会跟着变。
 */
async function applyTemplate() {
  const id = selectedTemplateId.value
  if (!id) return
  try {
    const result = await apiGet<{ template: TemplateRow }>(`/api/templates/${id}`)
    const next: Record<string, CanvasSlot> = {}
    for (const fragment of result.template.fragments ?? []) {
      next[fragment.fragment_type] = {
        content: fragment.content,
        promptId: fragment.prompt_id,
        source: fragment.prompt_id ? 'prompt' : 'library',
      }
    }
    canvas.value = next
  } catch (e) {
    toast.error(`套用失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

/** 把当前画布保存成模板。只有来自提示词的碎片能建立引用，碎片库碎片会被跳过。 */
async function saveTemplate() {
  const usable = canvasTypes.value.filter(
    (t) => canvas.value[t].source === 'prompt' && canvas.value[t].promptId,
  )
  if (!usable.length) {
    toast.error('画布里的碎片都来自"碎片库"，无法建立引用关系，请至少放入一个来自提示词的碎片')
    return
  }
  const skipped = canvasTypes.value.length - usable.length
  const name = await inputDialog({
    title: skipped ? `模板名称（${skipped} 个碎片库碎片不会被保存）` : '模板名称',
    placeholder: '给这个组合模板起个名字',
    positiveText: '保存',
    negativeText: '取消',
  })
  if (!name) return
  try {
    await apiPost('/api/templates', {
      name,
      fragments: usable.map((t) => ({
        prompt_id: canvas.value[t].promptId,
        fragment_type: t,
      })),
    })
    queryClient.invalidateQueries({ queryKey: ['templates'] })
  } catch (e) {
    toast.error(`保存失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

/**
 * 从旧前端的 localStorage 导入组合模板。
 *
 * 旧前端把模板存在 `composerTemplates_v4`（同源同端口，所以新前端读得到），
 * 结构是 `{name, fragments: {类型: {prompt_id, content}}}`。
 * 后端 `batch_import` 要的是 `{name, fragments: [{prompt_id, fragment_type}]}`，
 * 这里做一次转换 —— 没有 prompt_id 的碎片建立不了引用，跳过。
 */
async function importLegacyTemplates() {
  let legacy: Array<{ name?: string; fragments?: Record<string, { prompt_id?: number }> }> = []
  try {
    legacy = JSON.parse(localStorage.getItem('composerTemplates_v4') || '[]')
  } catch {
    legacy = []
  }
  if (!Array.isArray(legacy) || !legacy.length) {
    toast.info('没有找到旧版模板数据（localStorage 里没有 composerTemplates_v4）')
    return
  }
  const items = legacy
    .map((tpl) => ({
      name: tpl.name ?? '(未命名)',
      fragments: Object.entries(tpl.fragments ?? {})
        .filter(([, frag]) => frag && frag.prompt_id)
        .map(([type, frag]) => ({ prompt_id: frag.prompt_id, fragment_type: type })),
    }))
    .filter((tpl) => tpl.fragments.length)
  if (!items.length) {
    toast.info('旧模板里没有可导入的碎片引用（都需要 prompt_id）')
    return
  }
  try {
    const result = await apiPost<{ imported: number }>('/api/templates/batch_import', { items })
    localStorage.removeItem('composerTemplates_v4')
    toast.success(`已迁移 ${result.imported} 个旧模板`)
    queryClient.invalidateQueries({ queryKey: ['templates'] })
  } catch (e) {
    toast.error(`导入失败：${e instanceof Error ? e.message : String(e)}`)
  }
}
async function deleteTemplateById(id: number) {
  const ok = await confirmDialog({
    title: '删除模板',
    content: '确定删除这个模板吗？（不会删除来源提示词）',
    positiveText: '删除',
    negativeText: '取消',
  })
  if (!ok) return
  try {
    await apiDelete(`/api/templates/${id}`)
    if (selectedTemplateId.value === id) selectedTemplateId.value = null
    queryClient.invalidateQueries({ queryKey: ['templates'] })
  } catch (e) {
    toast.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

/** 模板面板里点「套用」：先选中再复用原有解析逻辑。 */
async function applyTemplateById(id: number) {
  selectedTemplateId.value = id
  await applyTemplate()
  templateOpen.value = false
}

async function runOnce() {
  if (!composedPrompt.value) return
  if (!workflowPath.value) {
    toast.error('请先选择工作流')
    return
  }
  try {
    const result = await submitAndTrack<{ success: boolean; job_id: number }>('/api/composer/run', {
      prompt: composedPrompt.value,
      negative_prompt: negativePrompt.value,
      workflow_path: workflowPath.value,
      // 自定义工作流不在后端磁盘上，内容必须一起带过去
      workflow_content: customWorkflowContent(workflowPath.value),
      quality: caps.value.quality ? quality.value : '4K',
      orientation: caps.value.orientation ? orientation.value : 'keep',
    })
    if (!result.success) toast.error('提交失败')
  } catch (e) {
    toast.error(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

async function confirmRandomRun() {
  if (!workflowPath.value) {
    toast.error('请先选择工作流')
    return
  }
  const chosen = randomCombos.value.filter((_, i) => selectedCombos.value.includes(i))
  if (!chosen.length) {
    toast.error('请至少勾选一组')
    return
  }
  try {
    const result = await submitAndTrack<{
      success: boolean
      job_id: number
      results?: Array<{ index: number; success: boolean; error?: string }>
    }>('/api/composer/batch_random_run', {
      count: chosen.length,
      // 用户已经在预览里确认过每一组文本，后端按原样提交，不再二次随机
      composed_prompts: chosen,
      workflow_path: workflowPath.value,
      workflow_content: customWorkflowContent(workflowPath.value),
      quality: caps.value.quality ? quality.value : '4K',
      orientation: caps.value.orientation ? orientation.value : 'keep',
      negative_prompt: negativePrompt.value,
    })
    if (!result.success) return
    const failed = (result.results ?? []).filter((r) => !r.success)
    const submitted = (result.results ?? []).length - failed.length
    // submitAndTrack 已在提交成功后订阅进度，这里只切页签
    resultTab.value = 'job'
    resultOpen.value = true
    if (failed.length && !submitted) {
      toast.error(`全部提交失败：${failed[0]?.error ?? '未知错误'}`)
    } else if (failed.length) {
      toast.info(`已提交 ${submitted} 组，${failed.length} 组失败（详见结果面板）`)
    } else {
      toast.success(`已提交 ${submitted} 组`)
    }
  } catch (e) {
    toast.error(`提交失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

watch(
  () => activeJob.value?.status,
  (status, prev) => {
    if (status === 'done' && prev && prev !== 'done') toast.success('随机组合已完成')
  },
)

function goJobs() {
  resultOpen.value = false
  router.push('/jobs')
}

function toggleTag(id: number) {
  const idx = tagIds.value.indexOf(id)
  if (idx >= 0) tagIds.value.splice(idx, 1)
  else tagIds.value.push(id)
}
</script>
<template>
  <div class="composer">
    <div class="composer-bar">
      <input
        v-model="search"
        class="bar-search"
        type="search"
        placeholder="检索碎片内容…"
      />
      <select v-model="categoryId" class="bar-select" title="按分类筛选碎片">
        <option :value="null">全部分类</option>
        <option v-for="cat in flatCats" :key="cat.id" :value="cat.id">
          {{ '　'.repeat(cat.depth) + cat.name }}
        </option>
      </select>
      <button
        class="btn btn-sm"
        :class="{ on: filtersOpen || tagIds.length }"
        @click="filtersOpen = !filtersOpen"
      >
        标签{{ tagIds.length ? ` · ${tagIds.length}` : '' }}
      </button>
      <span class="count">
        碎片 {{ fragmentTotal }}<span v-if="isFetching"> · 加载中</span>
      </span>
      <div class="bar-wf">
        <WorkflowPicker v-model="workflowPath" :workflows="workflows" />
      </div>
      <WorkflowParams
        v-model:quality="quality"
        v-model:orientation="orientation"
        :workflow-path="workflowPath"
        :caps="caps"
        :quality-options="qualityOptions"
      />
      <button
        class="btn btn-sm"
        :class="{ on: canvasCount }"
        title="查看组合结果（画布 / 随机组 / 任务结果）"
        @click="openResultCanvas"
      >
        组合结果 · {{ canvasCount }} 个碎片
      </button>
      <button
        class="btn btn-sm"
        :class="{ on: settingsOpen }"
        title="负向提示词"
        @click="settingsOpen = !settingsOpen"
      >
        ⚙ 高级
      </button>
      <button class="btn btn-sm" @click="templateOpen = true">
        📚 模板 {{ templates.length }}
      </button>
      <button class="btn btn-sm" title="随机抽一版并滚动定位，不出图" @click="rollOne">
        🎲 随机一版
      </button>
      <button
        class="btn btn-sm"
        :disabled="generating"
        :title="pinned.length ? `锁定 ${pinned.length} 列，其余随机` : '预览随机组合，确认后才出图'"
        @click="openRandomPreview"
      >
        🎲 预览
      </button>
      <button
        class="btn btn-sm primary"
        :class="{ loading: generating }"
        :disabled="generating || !canvasCount"
        @click="runOnce"
      >
        {{ generating ? '生成中…' : '🚀 试跑' }}
      </button>
      <span v-if="generateError" class="gen-error">{{ generateError }}</span>
      <span v-else-if="activeJob" class="job-state" :class="activeJob.status">
        {{ activeJob.status }} {{ activeJob.done_count ?? 0 }}/{{ activeJob.total ?? 1 }}
      </span>
    </div>

    <div v-if="settingsOpen" class="settings-panel">
      <div class="drawer-head">
        <span>高级设置</span>
        <button class="close" @click="settingsOpen = false">✕</button>
      </div>
      <label class="field">
        <span>负向提示词</span>
        <textarea v-model="negativePrompt" />
      </label>
    </div>

    <div v-if="filtersOpen" class="filter-drawer">
      <div class="drawer-head">
        <span>标签筛选</span>
        <button class="close" @click="filtersOpen = false">✕</button>
      </div>
      <section class="group">
        <TagCloud
          :tags="tagData?.tags ?? []"
          :selected="tagIds"
          :match="tagMatch"
          empty-text="暂无带提示词的标签"
          @toggle="toggleTag"
          @update:match="tagMatch = $event"
        />
      </section>
    </div>

    <div class="reels">
      <section v-for="type in FRAGMENT_TYPES" :key="type" class="reel">
        <header
          class="reel-head"
          :class="{ on: pinned.includes(type) }"
          :title="
            pinned.includes(type)
              ? `已锁定：${type}（随机时保持不变，点击解锁）`
              : `锁定「${type}」：随机时保持不变`
          "
          @click="toggleLock(type)"
        >
          <span class="pin-ico">{{ pinned.includes(type) ? '🔒' : '🔓' }}</span>
          <span class="reel-type">{{ type }}</span>
          <span class="reel-count">{{ (grouped[type] ?? []).length }}</span>
        </header>

        <div v-if="canvas[type]" class="reel-picked" :title="canvas[type].content">
          <span class="picked-label">已选</span>
          <span class="picked-text">{{ canvas[type].content }}</span>
          <button class="picked-x" title="清空这一列" @click="unpick(type)">✕</button>
        </div>

        <div class="reel-body" :ref="(el) => setReelBody(type, el)">
          <button
            v-if="canvas[type]?.source === 'custom'"
            class="card on custom"
            @click="openCustom(type)"
          >
            <span class="card-text">{{ canvas[type].content }}</span>
            <span class="card-meta">自定义<span class="tag-self">自</span></span>
          </button>

          <button
            v-for="(item, idx) in visibleFrags(type)"
            :key="`${type}-${item.fragment_id ?? item.prompt_id}-${idx}`"
            class="card"
            :class="{
              on: canvas[type]?.source !== 'custom' && canvas[type]?.content === item.content,
              hit: isHit(item.content),
            }"
            :title="`双击查看全文：${item.content}`"
            @click="pick(item)"
            @dblclick.stop="openDetail(item)"
          >
            <span class="card-text">
              <span
                v-for="(part, pi) in textParts(item.content)"
                :key="pi"
                :class="{ mark: part.hit }"
              >{{ part.text }}</span>
            </span>
            <span class="card-meta">
              {{ item.source === 'library' ? '碎片库' : item.prompt_name || '提示词' }}
              <i v-if="item.dup_count > 1">×{{ item.dup_count }}</i>
            </span>
          </button>

          <!-- 滚到列底会自动加载下一批；这个按钮是兜底，不要求用户先滚到底 -->
          <button
            v-if="hasMore(type)"
            :ref="(el) => setMoreEl(type, el)"
            :data-type="type"
            class="more"
            @click="loadMore(type)"
          >
            加载更多 · 还有 {{ (grouped[type] ?? []).length - limitOf(type) }} 个
          </button>
          <EmptyState
            v-if="!(grouped[type] ?? []).length && !canvas[type]"
            compact
            text="暂无碎片"
          />

          <button class="card add" @click="openCustom(type)">✎ 自定义…</button>
        </div>
      </section>
    </div>

    <Modal :open="customOpen" :title="`自定义碎片 · ${customType}`" @close="customOpen = false">
      <div class="custom-body">
        <textarea
          v-model="customText"
          spellcheck="false"
          :placeholder="`直接写一段内容，会填进「${customType}」列…`"
        />
      </div>
      <template #footer>
        <span class="spacer" />
        <button
          class="btn btn-sm"
          :disabled="!customText.trim()"
          title="把这段存进碎片库，之后可以像别的碎片一样用"
          @click="saveCustomToLibrary"
        >
          存进碎片库
        </button>
        <button class="btn btn-sm primary" :disabled="!customText.trim()" @click="applyCustom">
          填入画布
        </button>
      </template>
    </Modal>

    <Modal
      :open="templateOpen"
      title="组合模板"
      width="min(680px, 94vw)"
      @close="templateOpen = false"
    >
      <div class="tpl-panel">
        <input v-model="templateSearch" type="search" placeholder="搜索模板名…" />
        <div class="tpl-list">
          <div v-for="tpl in filteredTemplates" :key="tpl.id" class="tpl-row">
            <span class="tpl-name" :title="tpl.name">{{ tpl.name }}</span>
            <span class="count">{{ tpl.fragment_count }} 片</span>
            <button class="btn btn-sm" @click="applyTemplateById(tpl.id)">套用</button>
            <button class="btn btn-sm danger" @click="deleteTemplateById(tpl.id)">删</button>
          </div>
          <EmptyState v-if="!filteredTemplates.length" compact text="没有匹配的模板" />
        </div>
      </div>
      <template #footer>
        <button class="btn btn-sm" @click="saveTemplate">存为模板</button>
        <button
          class="btn btn-sm"
          title="把旧前端存在 localStorage 里的模板导入到数据库"
          @click="importLegacyTemplates"
        >
          导入旧模板
        </button>
        <span class="spacer" />
        <button class="btn btn-sm" @click="templateOpen = false">关闭</button>
      </template>
    </Modal>

    <ComposerResultCenterModal
      :open="resultOpen"
      :tab="resultTab"
      :composed="composedPrompt"
      :combos="randomCombos"
      :selected="selectedCombos"
      :job="activeJob"
      :count="randomCount"
      :canvas-count="canvasCount"
      :fixed-count="pinned.length"
      :generating="generating"
      @close="resultOpen = false"
      @set-tab="resultTab = $event"
      @set-count="setRandomCount"
      @regenerate="regenerateCombos"
      @confirm="confirmRandomRun"
      @reroll="rerollCombo"
      @remove="removeCombo"
      @toggle="toggleCombo"
      @run-canvas="runOnce"
      @copy-canvas="copyText(composedPrompt, '组合结果')"
      @save-prompt="saveAsPrompt"
      @go-jobs="goJobs"
    />

    <FragmentDetailModal
      :open="detailOpen"
      :fragment="detailFrag"
      @close="detailOpen = false"
      @pick="pickFromDetail"
      @jump="(id) => { detailOpen = false; router.push(`/prompt/${id}`) }"
    />
  </div>
</template>

<style scoped>
.composer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  position: relative;
}

.composer-bar {
  flex: none;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--gap);
  padding: 6px var(--gap-lg);
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.composer-bar .on {
  color: var(--primary);
}

.bar-search {
  flex: 1 1 220px;
  min-width: 160px;
}

.bar-select {
  max-width: 190px;
}

/* 工作流和画质是出图时始终有效的状态，常驻控制条中段（原来收在设置浮层里，
   宽屏时控制条中间反而空出一大块）。WorkflowPicker 自带可搜索下拉，比原生 select 好认长文件名。
   搜索框和它一起做弹性项，把剩余宽度分摊掉，避免行尾留白。 */
.bar-wf {
  flex: 1 1 220px;
  min-width: 150px;
}

/* 组件自带的 max-width 会在超宽屏下卡住选择器、反而在行尾留白 */
.bar-wf :deep(.wf-picker) {
  max-width: none;
}

/* 筛选改成抽屉：常驻会让首屏少掉 1/3 高度 */
.filter-drawer {
  position: absolute;
  top: 41px;
  left: 8px;
  z-index: 20;
  width: 268px;
  max-height: 72vh;
  overflow-y: auto;
  padding: var(--gap);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.drawer-head .close {
  border: none;
  background: transparent;
  color: var(--muted);
}

/* 高级设置浮层：与筛选抽屉同款，但贴右侧 */
.settings-panel {
  position: absolute;
  top: 41px;
  right: 8px;
  z-index: 20;
  width: 320px;
  max-height: 72vh;
  overflow-y: auto;
  padding: var(--gap);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

/* 8 条并列滚筒：每列独立滚动，候选与选中项同列 */
.reels {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 5px;
  padding: 6px;
  overflow-x: auto;
}

.reel {
  flex: 1 1 0;
  min-width: 148px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  overflow: hidden;
}

.reel-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 8px;
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
  cursor: pointer;
  user-select: none;
}

/* 整行表头都能切锁定，不必去点小图标 */
.reel-head:hover {
  background: var(--panel-2);
}

.reel-type {
  font-weight: 600;
}

.reel-count {
  color: var(--muted);
  font-size: var(--fs-xs);
  margin-left: auto;
}

.pin-ico {
  flex: none;
  color: var(--muted);
  font-size: 12px;
  line-height: 1;
}

.reel-head.on .pin-ico {
  color: var(--warn);
}

/* 列头下方：当前选中的碎片，替代旧版底部 8/8 的信息 */
.reel-picked {
  flex: none;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.picked-label {
  flex: none;
  color: var(--primary);
}

.picked-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picked-x {
  flex: none;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.picked-x:hover {
  color: var(--danger);
}

.tpl-panel {
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap-lg);
}

.tpl-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 56vh;
  overflow-y: auto;
}

.tpl-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  font-size: var(--fs-sm);
}

.tpl-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reel-body {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 4px;
}

.card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: left;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  padding: 5px 7px;
  transition: 0.12s;
}

.card:hover {
  border-color: var(--primary);
  background: var(--panel-3);
}

.card.on {
  border-color: var(--primary);
  background: var(--primary-soft);
}

/* 检索命中：整卡描边 + 关键词着色，便于定位 */
.card.hit {
  border-color: var(--warn);
}

.card-text .mark {
  color: var(--warn);
  font-weight: 600;
}

.card.custom {
  border-color: var(--warn);
}

.card-text {
  font-size: var(--fs-xs);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-meta {
  font-size: 10px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-self {
  color: var(--primary);
  border: 1px solid currentColor;
  border-radius: 3px;
  padding: 0 2px;
  margin-left: 4px;
}

.more {
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--muted);
  font-size: var(--fs-xs);
  padding: 4px;
}

.more:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.card.add {
  color: var(--muted);
  border-style: dashed;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.field select {
  width: 100%;
  box-sizing: border-box;
}

.field textarea {
  width: 100%;
  box-sizing: border-box;
  min-height: 44px;
  max-height: 66px;
  resize: vertical;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px 6px;
}

.gen-error {
  color: var(--danger);
  font-size: var(--fs-xs);
}

.job-state {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.custom-body {
  padding: var(--gap-lg);
}

.custom-body textarea {
  width: 100%;
  min-height: 140px;
  resize: vertical;
  font: inherit;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-sm);
  outline: none;
}

.spacer {
  flex: 1;
}

.count {
  color: var(--muted);
  font-size: var(--fs-xs);
}

/* 1366 / 1024 收一档：窄屏时控制条自动换行，滚筒再窄一点 */
@media (max-width: 1280px) {
  .reel {
    min-width: 132px;
  }
}
</style>

