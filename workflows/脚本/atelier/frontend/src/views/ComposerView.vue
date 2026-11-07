<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'

import { useRouter } from 'vue-router'
import TagCloud from '../components/TagCloud.vue'
import CategoryFilter from '../components/CategoryFilter.vue'
import ComposerResultCenterModal from '../components/ComposerResultCenterModal.vue'
import FragmentDetailModal from '../components/FragmentDetailModal.vue'
import Lightbox from '../components/Lightbox.vue'
import ComposerReel from '../components/ComposerReel.vue'
import ComposerControlBar from '../components/ComposerControlBar.vue'
import { apiDelete, apiGet, apiPost } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import Modal from '../components/Modal.vue'
import { useSettings } from '../composables/useSettings'
import { useWorkflowQuality } from '../composables/useWorkflowQuality'
import { useWorkflowAspectRatio } from '../composables/useWorkflowAspectRatio'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { useGenerate } from '../composables/useGenerate'
import { useWorkflows, customWorkflowContent } from '../composables/useWorkflows'
import { FRAGMENT_TYPES } from '../constants'
import { useToast } from '../composables/useToast'
import { useImagePreview } from '../composables/useImagePreview'
import { useComposerCanvas, type CanvasSlot } from '../composables/useComposerCanvas'
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
  source: 'prompt' | 'library' | 'custom'
  dup_count: number
}

// 组合器有自己的一份工作流，不跟提示词页/换脸页联动
const { composerWorkflowPath, orientation } = useSettings()
const quality = useWorkflowQuality(composerWorkflowPath)
const aspectRatio = useWorkflowAspectRatio(composerWorkflowPath)
const workflowPath = composerWorkflowPath
// 'composer' 这个 key 让「最近一次任务」落盘：刷新后结果中心的任务结果页签还能看到它。
// queue: true —— 提交即放行，任务交给 ComfyUI 排队；否则按钮会一直占用到整批跑完，
// 用户没法"再抽一组接着跑"。
const {
  busy: generating,
  job: activeJob,
  // 本次会话提交过的所有任务（新→旧）：结果中心的任务结果页签据此逐条列出
  queue: sessionJobs,
  activeCount,
  error: generateError,
  submitAndTrack,
} = useGenerate('composer', { queue: true })
const { workflows, allWorkflows } = useWorkflows(composerWorkflowPath)
/** 画质档位与横竖按工作流能力生成：不支持的项直接隐藏，不发无效参数。 */
const { caps, qualityOptions, aspectRatios, defaultRatio } = useWorkflowCaps(
  workflowPath, allWorkflows, aspectRatio,
)
const router = useRouter()
/** 灯箱「出图档案」里的来源提示词：交给 App 路由到提示词页。 */
const emit = defineEmits<{ (e: 'jump-to-prompt', promptId: number): void }>()

/**
 * 会话状态：检索条件、负向提示词、随机组数、各列已加载条数，
 * 以及**结果中心本身**（开关 / 页签 / 抽出来的几组）。
 *
 * 之前把它们留在内存里，刷新就等于「关掉弹窗、丢掉刚抽的组合」——用户
 * 一遍遍重抽。凡是"刷新后应该还在眼前"的东西，都归这份快照管。
 */
interface ComposerSession {
  search: string
  categoryId: number | null
  tagIds: number[]
  tagMatch: 'all' | 'any'
  negativePrompt: string
  randomCount: number
  limits: Record<string, number>
  resultOpen: boolean
  resultTab: 'canvas' | 'random' | 'job'
  randomCombos: string[]
  selectedCombos: number[]
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
  resultOpen: false,
  resultTab: 'canvas',
  randomCombos: [],
  selectedCombos: [],
})

const resultOpen = ref(savedSession.resultOpen)
const resultTab = ref<'canvas' | 'random' | 'job'>(savedSession.resultTab)
const randomCombos = ref<string[]>(savedSession.randomCombos)
/** 结果中心随机页里勾选的组（下标）；默认全选。 */
const selectedCombos = ref<number[]>(savedSession.selectedCombos)

/** 检索条常驻在顶部（旧版就是常驻的 25px 条），标签放抽屉。 */
const search = ref(savedSession.search)
const categoryId = ref<number | null>(savedSession.categoryId)
const tagIds = ref<number[]>(savedSession.tagIds)
const tagMatch = ref<'all' | 'any'>(savedSession.tagMatch)
const filtersOpen = ref(false)
const settingsOpen = ref(false)
const filterCount = computed(() => tagIds.value.length + (categoryId.value !== null ? 1 : 0))

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

const {
  canvas,
  pinned,
  canvasTypes,
  canvasCount,
  composedPrompt,
  setSlot,
  removeSlot,
  setCanvas,
  pick,
  togglePin,
} = useComposerCanvas()

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
  setSlot(customType.value, { content: text, promptId: null, source: 'custom' })
  customOpen.value = false
}

/** 把槽位里的自定义碎片存成单块 prompt（α 之后碎片 = 带【类型】的 prompt）。 */
async function saveCustomToLibrary() {
  const type = customType.value
  const text = customText.value.trim()
  if (!text || !type) return
  try {
    await apiPost('/api/prompts', {
      name: '',
      prompt: `【${type}】\n${text}`,
    })
    toast.success(`已存为「${type}」碎片`)
    // 组合器和提示词页是两个缓存根，两边都要刷
    queryClient.invalidateQueries({ queryKey: ['composer-fragments'] })
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
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
  removeSlot(type)
}

const negativePrompt = ref(savedSession.negativePrompt)

/** 负向条件是否真的参与采样；工作流探测不到时保持旧行为（不报警）。 */
const negativeEffective = computed(() => caps.value.negative_effective !== false)

const negativeTip = computed(() =>
  negativeEffective.value
    ? '编辑负面提示词（出图时使用）'
    : '当前工作流不使用负向提示词（不会生效）',
)

const negativeHint = computed(() => {
  if (negativeEffective.value) {
    const cfg = caps.value.negative_cfg
    return typeof cfg === 'number'
      ? `这些内容会在 CFG=${cfg} 的采样中作为负向条件使用。留空 = 不加负面提示词。`
      : '这些内容会作为负向条件提交；留空 = 不加负面提示词。'
  }
  const cfg = caps.value.negative_cfg
  return typeof cfg === 'number'
    ? `当前工作流使用 CFG=${cfg}，负向条件不会参与采样；这里的内容不会影响出图。`
    : '当前工作流没有接入负向条件（negative 已清零）；这里的内容不会影响出图。'
})

interface CompilePreview {
  positive: string
  negative: string
  notes: string[]
  warnings: string[]
  extracted: string[]
  negative_effective: boolean
  negative_cfg: number | null
}

const compileOpen = ref(false)
const compileBusy = ref(false)
const compileError = ref('')
const compileResult = ref<CompilePreview | null>(null)

/** 错误提示统一成「现象 + 原因 + 下一步」。 */
function describeError(symptom: string, error: unknown, next: string): string {
  const reason = error instanceof Error ? error.message : String(error || '未知错误')
  return `现象：${symptom}。原因：${reason}。下一步：${next}`
}

const generateErrorText = computed(() =>
  generateError.value
    ? describeError('出图请求未能完成', generateError.value, '检查后端与 ComfyUI 是否在线，然后重试')
    : '',
)

async function openCompilePreview() {
  if (!composedPrompt.value) {
    toast.error('画布是空的')
    return
  }
  if (!workflowPath.value) {
    toast.error('请先选择工作流')
    return
  }
  compileOpen.value = true
  compileBusy.value = true
  compileError.value = ''
  compileResult.value = null
  try {
    compileResult.value = await apiPost<CompilePreview>('/api/prompts/compile', {
      prompt: composedPrompt.value,
      negative_prompt: negativePrompt.value,
      workflow_path: workflowPath.value,
      workflow_content: customWorkflowContent(workflowPath.value),
    })
  } catch (e) {
    compileError.value = describeError('提示词编译失败', e, '确认提示词与工作流可用后重新编译')
  } finally {
    compileBusy.value = false
  }
}

// ---------------- 跑图 ----------------

/** 画布上的碎片作为"固定碎片"，其余类型由后端随机填充。 */
const randomCount = ref(savedSession.randomCount)

watch(
  [
    search,
    categoryId,
    tagIds,
    tagMatch,
    negativePrompt,
    randomCount,
    limits,
    // 结果中心的开关 / 页签 / 抽出来的组合也一起落盘：刷新不该把弹窗关掉
    resultOpen,
    resultTab,
    randomCombos,
    selectedCombos,
  ],
  () => {
    writeSession(SESSION_KEY, {
      search: search.value,
      categoryId: categoryId.value,
      tagIds: tagIds.value,
      tagMatch: tagMatch.value,
      negativePrompt: negativePrompt.value,
      randomCount: randomCount.value,
      limits: limits.value,
      resultOpen: resultOpen.value,
      resultTab: resultTab.value,
      randomCombos: randomCombos.value,
      selectedCombos: selectedCombos.value,
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

/**
 * 刷新后把「已选碎片」摆回列中间。
 *
 * 之前只有手动随机才滚动，于是固定列刷新后既不在视野里高亮，选中项若排在
 * 首批 40 条之后，卡片甚至根本没渲染（`.card.on` 找不到）。
 * 这里在碎片数据第一次到位时补一次：先把限额提到选中项，再滚到中间。
 */
let pickedRestored = false
watch(
  [grouped, canvas],
  async () => {
    if (pickedRestored || !Object.keys(grouped.value).length) return
    pickedRestored = true
    for (const type of FRAGMENT_TYPES) {
      const slot = canvas.value[type]
      if (!slot) continue
      const index = (grouped.value[type] ?? []).findIndex((f) => f.content === slot.content)
      if (index >= limitOf(type)) {
        limits.value = { ...limits.value, [type]: index + PAGE_SIZE }
      }
    }
    await nextTick()
    for (const type of FRAGMENT_TYPES) {
      const body = reelBodies.get(type)
      // 刷新时不要平滑动画：那一跳应该已经"本来就在那儿"
      body?.querySelector<HTMLElement>('.card.on')?.scrollIntoView?.({ block: 'center' })
    }
  },
  { immediate: true },
)

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
  setCanvas(next)
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
  source: 'prompt' | 'custom'
  promptId: number | null
  promptName: string
  dupCount: number
}

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
    source: item.source === 'custom' ? 'custom' : 'prompt',
    promptId: item.prompt_id,
    promptName: item.prompt_name,
    dupCount: item.dup_count,
  }
  detailOpen.value = true
}

function pickFromDetail() {
  if (!detailFrag.value) return
  const f = detailFrag.value
  setSlot(f.type, { content: f.content, promptId: f.promptId, source: f.source })
  detailOpen.value = false
}

/** 一键把该列已选碎片滚到列表中间；选中项还没加载出来时先补一批。 */
async function locatePicked(type: string) {
  const slot = canvas.value[type]
  if (!slot?.content) {
    toast.error(`「${type}」还没有选碎片，先选一个再定位`)
    return
  }
  if (slot.source !== 'custom') {
    const index = (grouped.value[type] ?? []).findIndex((f) => f.content === slot.content)
    if (index >= limitOf(type)) {
      limits.value = { ...limits.value, [type]: index + PAGE_SIZE }
      await nextTick()
    }
  }
  const body = reelBodies.get(type)
  body?.querySelector<HTMLElement>('.card.on')?.scrollIntoView({
    block: 'center',
    behavior: 'smooth',
  })
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
    setCanvas(next)
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
      aspect_ratio: aspectRatio.value || defaultRatio.value,
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
      idempotent?: boolean
      async?: boolean
      queued?: number
      total?: number
    }>('/api/composer/batch_random_run', {
      count: chosen.length,
      // 用户已经在预览里确认过每一组文本，后端按原样提交，不再二次随机
      composed_prompts: chosen,
      workflow_path: workflowPath.value,
      workflow_content: customWorkflowContent(workflowPath.value),
      quality: caps.value.quality ? quality.value : '4K',
      orientation: caps.value.orientation ? orientation.value : 'keep',
      aspect_ratio: aspectRatio.value || defaultRatio.value,
      negative_prompt: negativePrompt.value,
    })
    if (!result.success) return
    resultTab.value = 'job'
    resultOpen.value = true
    if (result.idempotent) {
      toast.info('该请求已提交过，已接回原任务')
      return
    }
    if (result.async) {
      toast.success(`已加入提交队列（${result.queued ?? result.total ?? 0} 组）`)
      return
    }
    const failed = (result.results ?? []).filter((r) => !r.success)
    const submitted = (result.results ?? []).length - failed.length
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

/** 点顶栏的「队列 N」：直接打开结果中心的任务结果页签。 */
function openJobTab() {
  resultTab.value = 'job'
  resultOpen.value = true
}

/** 任务结果里的缩略图：点开看原图（复用画廊那次灯箱，不另写查看器）。 */
const {
  items: previewItems,
  readonly: previewReadonly,
  open: previewOpen,
  preview: openPreviewImage,
  close: closePreviewImage,
} = useImagePreview()

/** 从灯箱跳画廊：按文件名深链，画廊自己去取那条记录。 */
function openInGallery(filename: string) {
  closePreviewImage()
  router.push({ path: '/gallery', query: { image: filename } })
}

function toggleTag(id: number) {
  const idx = tagIds.value.indexOf(id)
  if (idx >= 0) tagIds.value.splice(idx, 1)
  else tagIds.value.push(id)
}
</script>
<template>
  <div class="composer">
    <ComposerControlBar
      v-model:search="search"
      v-model:workflow-path="workflowPath"
      v-model:quality="quality"
      v-model:orientation="orientation"
      v-model:aspect-ratio="aspectRatio"
      :filters-open="filtersOpen"
      :filter-count="filterCount"
      :fragment-total="fragmentTotal"
      :is-fetching="isFetching"
      :workflows="workflows"
      :aspect-ratios="aspectRatios"
      :default-ratio="defaultRatio"
      :quality-options="qualityOptions"
      :caps="caps"
      :canvas-count="canvasCount"
      :negative-prompt="negativePrompt"
      :negative-effective="negativeEffective"
      :negative-tip="negativeTip"
      :templates-count="templates.length"
      :pinned-count="pinned.length"
      :generating="generating"
      :generate-error-text="generateErrorText"
      :active-count="activeCount"
      :active-job="activeJob"
      @toggle-filters="filtersOpen = !filtersOpen"
      @open-result="openResultCanvas"
      @open-negative="settingsOpen = true"
      @open-compile="openCompilePreview"
      @open-templates="templateOpen = true"
      @roll-one="rollOne"
      @preview-random="openRandomPreview"
      @run-once="runOnce"
      @open-job-tab="openJobTab"
    />

    <Modal
      :open="settingsOpen"
      title="负面提示词"
      width="min(820px, 92vw)"
      height="min(56vh, 520px)"
      @close="settingsOpen = false"
    >
      <div class="neg-panel">
        <p class="neg-hint" :class="{ warn: !negativeEffective }">
          {{ negativeHint }}
        </p>
        <textarea
          v-model="negativePrompt"
          class="neg-text"
          spellcheck="false"
          placeholder="例如：低清晰度、模糊、多余的手指、水印、文字…"
        />
      </div>
      <template #footer>
        <span class="spacer" />
        <button class="btn btn-sm" @click="negativePrompt = ''">清空</button>
        <button class="btn btn-sm primary" @click="settingsOpen = false">确定</button>
      </template>
    </Modal>

    <Modal
      :open="compileOpen"
      title="提示词编译预览"
      width="min(860px, 92vw)"
      height="min(72vh, 720px)"
      @close="compileOpen = false"
    >
      <div class="compile-panel">
        <p v-if="compileBusy" class="compile-status">编译中…</p>
        <p v-else-if="compileError" class="compile-status error">{{ compileError }}</p>
        <template v-else-if="compileResult">
          <p class="compile-meta">
            负向通道：
            <b>{{ compileResult.negative_effective ? '生效' : '不生效' }}</b>
            <span v-if="compileResult.negative_cfg != null">
              （CFG={{ compileResult.negative_cfg }}）
            </span>
          </p>
          <section class="compile-block">
            <h4>正向（提交）</h4>
            <pre>{{ compileResult.positive }}</pre>
          </section>
          <section class="compile-block">
            <h4>负向（{{ compileResult.negative_effective ? '提交' : '不提交' }}）</h4>
            <pre>{{ compileResult.negative || '（空）' }}</pre>
          </section>
          <section v-if="compileResult.notes.length" class="compile-block">
            <h4>改写</h4>
            <ul>
              <li v-for="(note, i) in compileResult.notes" :key="`note-${i}`">{{ note }}</li>
            </ul>
          </section>
          <section v-if="compileResult.warnings.length" class="compile-block warn">
            <h4>提醒</h4>
            <ul>
              <li v-for="(item, i) in compileResult.warnings" :key="`warn-${i}`">{{ item }}</li>
            </ul>
          </section>
        </template>
      </div>
    </Modal>

    <div v-if="filtersOpen" class="filter-drawer">
      <div class="drawer-head">
        <span>分类 / 标签筛选</span>
        <button class="close" @click="filtersOpen = false">✕</button>
      </div>
      <CategoryFilter
        :categories="catData?.categories"
        v-model="categoryId"
        all-label="全部分类"
        show-count
      />
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
      <ComposerReel
        v-for="type in FRAGMENT_TYPES"
        :key="type"
        :type="type"
        :items="visibleFrags(type)"
        :total-count="(grouped[type] ?? []).length"
        :pinned="pinned.includes(type)"
        :slot="canvas[type]"
        :keyword="keyword"
        :register-body="(el) => setReelBody(type, el)"
        :register-more="(el) => setMoreEl(type, el)"
        @toggle-lock="toggleLock"
        @locate="locatePicked"
        @unpick="unpick"
        @pick="pick"
        @open-custom="openCustom"
        @open-detail="openDetail"
        @load-more="loadMore"
      />
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
          title="把这段存成一块【类型】提示词，之后可以像别的碎片一样用"
          @click="saveCustomToLibrary"
        >
          存为碎片
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
          <EmptyState
            v-if="!filteredTemplates.length"
            compact
            text="没有匹配的模板"
            hint="换个关键词，或先存一份当前组合为模板。"
            action-text="清空搜索"
            @action="templateSearch = ''"
          />
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
      :jobs="sessionJobs"
      :count="randomCount"
      :canvas-count="canvasCount"
      :fixed-count="pinned.length"
      :generating="generating"
      :active-count="activeCount"
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
      @preview-image="openPreviewImage($event)"
    />

    <Lightbox
      v-if="previewOpen"
      :items="previewItems"
      :index="0"
      :readonly="previewReadonly"
      :workflows="workflows"
      can-open-gallery
      @close="closePreviewImage"
      @open-in-gallery="openInGallery"
      @jump-to-prompt="(id) => { closePreviewImage(); emit('jump-to-prompt', id) }"
      @changed="queryClient.invalidateQueries({ queryKey: ['history'] })"
    />

    <FragmentDetailModal
      :open="detailOpen"
      :fragment="detailFrag"
      @close="detailOpen = false"
      @pick="pickFromDetail"
      @jump="(id, fragType) => { detailOpen = false; router.push({ path: `/prompt/${id}`, query: { frag_type: fragType } }) }"
    />
  </div>
</template>

<style scoped>
.btn {
  transition:
    color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.composer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  position: relative;
}

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
  box-shadow: var(--shadow-2);
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
  transition: color var(--dur-fast) var(--ease);
}

.drawer-head .close:hover {
  color: var(--text);
}

/* 负面提示词弹窗：整块可用区域都给文本框，不再挤在 320px 的小抽屉里 */
.neg-panel {
  height: 100%;
  box-sizing: border-box;
  padding: var(--gap);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.neg-hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.neg-hint.warn {
  color: var(--warn);
}

.neg-text {
  flex: 1;
  min-height: 0;
  width: 100%;
  box-sizing: border-box;
  resize: none;
  font: inherit;
  line-height: 1.6;
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
}

/* 编译预览：只读，不写库；整块可滚动，长提示词不会撑破弹窗 */
.compile-panel {
  height: 100%;
  box-sizing: border-box;
  padding: var(--gap);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap);
}

.compile-status {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--muted);
}

.compile-status.error {
  color: var(--danger);
}

.compile-meta {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--muted);
}

.compile-block h4 {
  margin: 0 0 6px;
  font-size: var(--fs-xs);
  color: var(--muted);
  font-weight: 600;
}

.compile-block pre {
  margin: 0;
  padding: 10px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  font: inherit;
  color: var(--text);
}

.compile-block ul {
  margin: 0;
  padding-left: 18px;
  font-size: var(--fs-xs);
  line-height: 1.7;
  color: var(--text);
}

.compile-block.warn h4 {
  color: var(--warn);
}

/* 8 条并列滚筒：每列独立滚动，候选与选中项同列 */
.reels {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: var(--gap-xs);
  padding: var(--gap-sm);
  overflow-x: auto;
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
  gap: var(--gap-xs);
  max-height: 56vh;
  overflow-y: auto;
}

.tpl-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: var(--gap-xs) var(--gap-sm);
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

</style>

