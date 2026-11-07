<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import Modal from './Modal.vue'
import WorkflowPicker from './WorkflowPicker.vue'
import WorkflowParams from './WorkflowParams.vue'
import Lightbox from './Lightbox.vue'
import { apiGet, thumbnailUrl } from '../api/client'
import { FRAGMENT_TYPES } from '../constants'
import { batchReplaceSegments, type ReplacementItem, type TypeOutcome } from '../utils/segmentation'
import { formatDateTime, formatElapsed, statusLabel } from '../utils/format'
import { useSettings } from '../composables/useSettings'
import { useWorkflows } from '../composables/useWorkflows'
import { useWorkflowCaps } from '../composables/useWorkflowCaps'
import { useWorkflowQuality } from '../composables/useWorkflowQuality'
import { useWorkflowAspectRatio } from '../composables/useWorkflowAspectRatio'
import { useJobStream } from '../composables/useJobStream'
import { useImageLocation } from '../composables/useImageLocation'
import { useImagePreview } from '../composables/useImagePreview'
import type { JobSnapshot } from '../api/types'

/**
 * 批量替换碎片：把提示词里的多个碎片类型各自换成一段内容后出图。
 *
 * 候选碎片来自"所有提示词里出现过的同类碎片 + 碎片库"，所以能搜到具体那一段；
 * 范围优先用左侧已勾选，没勾选才用当前筛选全部；不写回提示词库。
 */
interface FullPromptRow {
  id: number
  name: string
  prompt: string
  seed: number | null
}

interface CandidateRow {
  fragment_id?: number
  prompt_id: number | null
  prompt_name: string
  type: string
  content: string
  source: 'prompt' | 'library'
  dup_count: number
}

const props = defineProps<{
  open: boolean
  search: string
  categoryId: number | null
  tagIds: number[]
  tagMatch: 'all' | 'any'
  /** 碎片筛选（与左侧列表同一份条件，否则"看到的"和"替换的"不是一批） */
  fragmentTypes: string[]
  fragmentMatch: 'has' | 'only'
  selectedIds: number[]
  /** 页面当前的工作流；设置里还没选过时作为兜底。 */
  workflowPath: string
  /** 锁定到单条提示词（提示词详情里的「替换碎片」入口）。 */
  lockPromptId?: number | null
  lockPromptName?: string
  /** 最近一次替换出图的任务 id；有值时「任务与结果」页签可以接回来。 */
  jobId?: number | null
}>()

const emit = defineEmits<{
  close: []
  'go-jobs': []
  'jump-to-prompt': [promptId: number]
  submit: [
    payload: {
      /** 本次清单里的类型（用于确认文案与任务标题） */
      types: string[]
      workflowPath: string
      quality: string
      aspectRatio: string
      items: Array<{ promptId: number; seed: number | null; promptOverride: string }>
    },
  ]
}>()

/**
 * 工作流与页面共用 settings 里那一份（同一个 ref）：
 * 在弹窗里换工作流，页面顶部的工作流也跟着换，关闭后再打开不会各说各话。
 * 设置里还没选过时退回父组件传来的值，测试与首次加载都能显示。
 */
const { workflowPath: settingsWorkflowPath, orientation } = useSettings()
const wfPath = computed<string>({
  get: () => settingsWorkflowPath.value || props.workflowPath,
  set: (value) => {
    settingsWorkflowPath.value = value
  },
})
const { workflows, allWorkflows } = useWorkflows()
const quality = useWorkflowQuality(wfPath)
const aspectRatio = useWorkflowAspectRatio(wfPath)
const { caps, qualityOptions, aspectRatios, defaultRatio } = useWorkflowCaps(
  wfPath, allWorkflows, aspectRatio,
)

// ---------------------------------------------------------------------------
// 提交后的任务进度与结果
// ---------------------------------------------------------------------------

const TERMINAL = new Set(['done', 'error', 'cancelled', 'stopped'])
const LAST_JOB_KEY = 'pb.batchReplace.lastJobId'
const tab = ref<'config' | 'job'>('config')
const job = ref<JobSnapshot | null>(null)
const jobLoading = ref(false)

function readLastJobId(): number | null {
  try {
    const parsed = Number(localStorage.getItem(LAST_JOB_KEY) ?? '')
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null
  } catch {
    return null
  }
}

function rememberLastJobId(id: number | null) {
  try {
    if (id) localStorage.setItem(LAST_JOB_KEY, String(id))
    else localStorage.removeItem(LAST_JOB_KEY)
  } catch {
    /* localStorage 不可用时忽略 */
  }
}

const stream = useJobStream((snapshot) => {
  job.value = snapshot
})

/** 打开弹窗时接回最近一次任务；有新提交（jobId 变化）时自动切到结果页签。 */
watch(
  [() => props.open, () => props.jobId],
  async ([open, id]) => {
    if (!open) {
      stream.close()
      return
    }
    const target = id ?? readLastJobId()
    if (!target) {
      job.value = null
      return
    }
    jobLoading.value = true
    try {
      const snapshot = await apiGet<JobSnapshot>(`/api/jobs/${target}`)
      job.value = snapshot
      if (!TERMINAL.has(snapshot.status)) stream.open([target])
      rememberLastJobId(target)
    } catch {
      job.value = null
      rememberLastJobId(null)
    } finally {
      jobLoading.value = false
    }
  },
  { immediate: true },
)

watch(
  () => props.jobId,
  (id) => {
    if (id) tab.value = 'job'
  },
)
watch(
  () => props.open,
  (open) => {
    if (open) tab.value = 'config'
  },
)

function elapsedText(item: JobSnapshot): string {
  const start = Date.parse(item.created_at)
  if (!start) return ''
  const end = TERMINAL.has(item.status) ? Date.parse(item.updated_at) : Date.now()
  if (!end) return ''
  return formatElapsed(Math.max(0, (end - start) / 1000))
}

function finishText(item: JobSnapshot): string {
  if (!item.updated_at) return ''
  return TERMINAL.has(item.status)
    ? formatDateTime(item.updated_at, true)
    : `更新于 ${formatDateTime(item.updated_at)}`
}

function workflowName(path?: string | null): string {
  const raw = path || ''
  if (!raw) return ''
  if (raw.startsWith('custom://')) return raw.slice('custom://'.length)
  const base = raw.replace(/\\/g, '/').split('/').pop() || raw
  return base.replace(/\.json$/i, '')
}

function jobPercent(item: JobSnapshot): number {
  if (!item.total) return item.status === 'done' ? 100 : 0
  return Math.min(100, Math.round(((item.done_count ?? 0) / item.total) * 100))
}

function thumbUrl(image: { filename: string; subfolder?: string | null; type?: string | null }): string {
  return thumbnailUrl({ filename: image.filename, subfolder: image.subfolder, img_type: image.type }, 200)
}

const {
  items: previewItems,
  readonly: previewReadonly,
  open: previewOpen,
  preview: previewImage,
  close: closePreviewImage,
} = useImagePreview()
const { revealImage } = useImageLocation()


interface ReplaceRow {
  key: number
  type: string
  content: string
  missing: 'skip' | 'append'
}

let rowSeq = 0

function makeRow(type = '', content = '', missing: 'skip' | 'append' = 'skip'): ReplaceRow {
  return { key: ++rowSeq, type, content, missing }
}

const rows = ref<ReplaceRow[]>([])
const activeKey = ref<number | null>(null)
const fragQuery = ref('')
const promptQuery = ref('')
const selected = ref<Set<number>>(new Set())
const fullOpen = ref<Set<number>>(new Set())

/** 勾选优先：左侧有勾选就只看勾选项，没勾选才用当前筛选全部。 */
const scope = ref<'selected' | 'filtered'>(
  props.selectedIds.length ? 'selected' : 'filtered',
)

const activeRow = computed(() => rows.value.find((r) => r.key === activeKey.value) ?? null)
const activeType = computed(() => activeRow.value?.type ?? '')
const activeContent = computed(() => activeRow.value?.content.trim() ?? '')

const usedTypes = computed(() => new Set(rows.value.map((r) => r.type).filter(Boolean)))
const addableTypes = computed(() => FRAGMENT_TYPES.filter((t) => !usedTypes.value.has(t)))

/** 同一类型只允许出现一次：下拉里排除其他行已占用的类型。 */
function selectableTypes(row: ReplaceRow): readonly string[] {
  const others = new Set(
    rows.value.filter((r) => r.key !== row.key).map((r) => r.type).filter(Boolean),
  )
  return FRAGMENT_TYPES.filter((t) => !others.has(t))
}

function addRow(type: string) {
  if (!type || usedTypes.value.has(type)) return
  const row = makeRow(type)
  rows.value = [...rows.value, row]
  activeKey.value = row.key
}

function onAddType(event: Event) {
  const select = event.target as HTMLSelectElement
  addRow(select.value)
  select.value = ''
}

function removeRow(key: number) {
  rows.value = rows.value.filter((r) => r.key !== key)
  if (activeKey.value === key) activeKey.value = rows.value[0]?.key ?? null
}

function activate(key: number) {
  activeKey.value = key
}

/** 只有类型和内容都填好的行才参与预览与提交。 */
const validReplacements = computed<ReplacementItem[]>(() =>
  rows.value
    .filter((r) => r.type && r.content.trim())
    .map((r) => ({ type: r.type, content: r.content.trim(), missing: r.missing })),
)

const OPTIONS_KEY = 'pb.batchReplace'

interface SavedRow {
  type: string
  content: string
  missing: 'skip' | 'append'
}

function readSavedRows(): SavedRow[] {
  try {
    const raw = localStorage.getItem(OPTIONS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as { rows?: unknown }
    if (!Array.isArray(parsed.rows)) return []
    const seen = new Set<string>()
    const saved: SavedRow[] = []
    for (const item of parsed.rows) {
      if (!item || typeof item !== 'object') continue
      const row = item as Partial<SavedRow>
      if (typeof row.type !== 'string') continue
      if (!(FRAGMENT_TYPES as readonly string[]).includes(row.type)) continue
      if (seen.has(row.type)) continue
      seen.add(row.type)
      saved.push({
        type: row.type,
        content: typeof row.content === 'string' ? row.content : '',
        missing: row.missing === 'append' ? 'append' : 'skip',
      })
    }
    return saved
  } catch {
    return []
  }
}

let saveTimer: number | undefined

function scheduleSave() {
  if (typeof window === 'undefined') return
  window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    try {
      localStorage.setItem(OPTIONS_KEY, JSON.stringify({
        rows: rows.value.map((r) => ({ type: r.type, content: r.content, missing: r.missing })),
      }))
    } catch {
      /* localStorage 不可用时忽略 */
    }
  }, 300)
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    rows.value = readSavedRows().map((r) => makeRow(r.type, r.content, r.missing))
    activeKey.value = rows.value[0]?.key ?? null
    // 范围不记忆：左侧勾选是本次打开时刚做出的明确选择，不能被上次的
    // 「当前筛选全部」盖掉，否则会出现"勾了 9 条却处理全部 304 条"。
    scope.value = props.selectedIds.length ? 'selected' : 'filtered'
    fragQuery.value = ''
    promptQuery.value = ''
    selected.value = new Set()
    fullOpen.value = new Set()
  },
  { immediate: true },
)

watch(rows, scheduleSave, { deep: true })

function resetOptions() {
  rows.value = []
  activeKey.value = null
  scope.value = props.selectedIds.length ? 'selected' : 'filtered'
  fullOpen.value = new Set()
  try {
    localStorage.removeItem(OPTIONS_KEY)
  } catch {
    /* localStorage 不可用时忽略 */
  }
}

const lockedId = computed(() => props.lockPromptId ?? null)
const usingSelected = computed(() => lockedId.value !== null || scope.value === 'selected')
const effectiveIds = computed(() =>
  lockedId.value !== null ? [lockedId.value] : props.selectedIds,
)

const { data: fullData } = useQuery<{ items: FullPromptRow[]; total: number }>({
  queryKey: computed(() =>
    usingSelected.value
      ? ['prompts-full', 'ids', effectiveIds.value.slice().sort((a, b) => a - b).join(',')]
      : [
          'prompts-full',
          'filter',
          props.search.trim(),
          props.categoryId,
          props.tagIds.slice().sort((a, b) => a - b).join(','),
          props.tagMatch,
          props.fragmentTypes.join(','),
          props.fragmentMatch,
        ],
  ),
  queryFn: () =>
    usingSelected.value
      ? apiGet('/api/prompts/full', { ids: effectiveIds.value.join(',') })
      : apiGet('/api/prompts/full', {
          search: props.search.trim(),
          category_id: props.categoryId ?? undefined,
          tag_ids: props.tagIds.length ? props.tagIds.join(',') : undefined,
          tag_match: props.tagMatch,
          fragment_types: props.fragmentTypes.join(','),
          fragment_match: props.fragmentMatch,
        }),
  enabled: computed(
    () => props.open && (!usingSelected.value || effectiveIds.value.length > 0),
  ),
})

/** 候选 = 所有提示词里的同类碎片 + 碎片库，后端已按内容去重；跟随当前选中的替换行。 */
const { data: candidateData, isFetching: candidatesLoading } = useQuery<{
  grouped: Record<string, CandidateRow[]>
}>({
  queryKey: computed(() => ['replace-candidates', activeType.value]),
  queryFn: () =>
    apiGet('/api/composer/fragments', { fragment_type: activeType.value }),
  enabled: computed(() => props.open && !!activeType.value),
})

const candidates = computed(
  () => candidateData.value?.grouped?.[activeType.value] ?? [],
)

const filteredCandidates = computed(() => {
  const q = fragQuery.value.trim().toLowerCase()
  if (!q) return candidates.value
  return candidates.value.filter((c) =>
    `${c.content} ${c.prompt_name} ${c.type}`.toLowerCase().includes(q),
  )
})

function useCandidate(c: CandidateRow) {
  if (activeRow.value) activeRow.value.content = c.content
}

watch(activeType, () => {
  fragQuery.value = ''
})

interface DiffOutcome extends TypeOutcome {
  content: string
}

interface MatchedRow {
  id: number
  name: string
  seed: number | null
  replaced: string
  /** 实际发生的替换/追加，按清单顺序 */
  outcomes: DiffOutcome[]
  /** 该提示词没有、且这一项选择跳过的类型 */
  skipped: string[]
  replacedCount: number
  appendedCount: number
}

/**
 * 命中清单任一类型的提示词进入替换列表；每个类型按自己的缺失策略决定
 * 替换 / 追加 / 跳过。预览由后端算（`POST /api/composition/batch_replace`）——
 * `【类型】` 语法只有后端一份实现，其他块原样保留。
 * 用递增序号丢弃过期响应：用户连续修改内容时，先发的请求可能后到。
 */
const previewRows = ref<MatchedRow[]>([])
let previewSeq = 0

watch(
  [validReplacements, () => fullData.value?.items],
  async ([specs, items]) => {
    const prompts = items ?? []
    if (!props.open || !specs.length || !prompts.length) {
      previewRows.value = []
      return
    }
    const contentByType = new Map(specs.map((s) => [s.type, s.content]))
    const seq = ++previewSeq
    try {
      const outcomes = await batchReplaceSegments(
        prompts.map((p) => ({ id: p.id, text: p.prompt })),
        specs,
      )
      if (seq !== previewSeq) return
      previewRows.value = prompts.flatMap((p) => {
        const hit = outcomes.get(p.id)
        if (!hit || hit.replaced === null) return []
        const changed = hit.outcomes.filter((o) => o.action !== 'skipped')
        if (!changed.length) return []
        return [{
          id: p.id,
          name: p.name || `#${p.id}`,
          seed: p.seed ?? null,
          replaced: hit.replaced,
          outcomes: changed.map((o) => ({
            ...o,
            content: contentByType.get(o.type) ?? '',
          })),
          skipped: hit.outcomes.filter((o) => o.action === 'skipped').map((o) => o.type),
          replacedCount: changed.filter((o) => o.action === 'replaced').length,
          appendedCount: changed.filter((o) => o.action === 'appended').length,
        }]
      })
    } catch {
      if (seq === previewSeq) previewRows.value = []
    }
  },
  { immediate: true },
)

const matchedAll = computed<MatchedRow[]>(() => previewRows.value)

/** 列表内的检索只影响"看/批量勾选"，不影响已经选中的其他条目。 */
const visibleRows = computed<MatchedRow[]>(() => {
  const q = promptQuery.value.trim().toLowerCase()
  if (!q) return matchedAll.value
  return matchedAll.value.filter((r) => {
    const haystack = [
      r.name,
      r.replaced,
      ...r.outcomes.map((o) => `${o.type} ${o.oldContent} ${o.content}`),
    ].join(' ')
    return haystack.toLowerCase().includes(q)
  })
})

const totalCount = computed(() => fullData.value?.items.length ?? 0)
const unmatchedCount = computed(() => Math.max(0, totalCount.value - matchedAll.value.length))
const replacedCells = computed(() => matchedAll.value.reduce((n, r) => n + r.replacedCount, 0))
const appendedCells = computed(() => matchedAll.value.reduce((n, r) => n + r.appendedCount, 0))
const skippedCells = computed(() => matchedAll.value.reduce((n, r) => n + r.skipped.length, 0))

/** 类型/范围/内容变化后默认全选匹配项；检索不改变已选集合。 */
watch(
  () => matchedAll.value.map((r) => r.id).join(','),
  () => {
    selected.value = new Set(matchedAll.value.map((r) => r.id))
  },
)

const selectedRows = computed(() =>
  matchedAll.value.filter((r) => selected.value.has(r.id)),
)
const selectedCount = computed(() => selectedRows.value.length)

/** 检索把已选项藏起来时给出提示，避免反选后漏提交。 */
const hiddenSelectedCount = computed(() => {
  const visible = new Set(visibleRows.value.map((r) => r.id))
  return matchedAll.value.filter((r) => selected.value.has(r.id) && !visible.has(r.id)).length
})

const replacedSelectedCells = computed(() =>
  selectedRows.value.reduce((n, r) => n + r.replacedCount, 0),
)
const appendedSelectedCells = computed(() =>
  selectedRows.value.reduce((n, r) => n + r.appendedCount, 0),
)

/** 主按钮直接说清这次会发生什么，而不是笼统的「替换/追加」。 */
const submitLabel = computed(() => {
  const r = replacedSelectedCells.value
  const a = appendedSelectedCells.value
  if (!r && !a) return '开始出图'
  if (r && a) return `替换 ${r} · 追加 ${a} 处并出图`
  if (a) return `追加 ${a} 处并出图`
  return `替换 ${r} 处并出图`
})

/**
 * 单条模式只有一条结果，默认把完整提示词也展开，正好填满右侧核对区。
 * 把 `open` 也放进依赖：重新打开时 previewRows 可能没变，靠 ids 单独触发会漏掉。
 */
watch(
  () => [props.open, previewRows.value.map((r) => r.id).join(',')] as const,
  ([open]) => {
    if (open && lockedId.value !== null && previewRows.value.length === 1) {
      fullOpen.value = new Set([previewRows.value[0].id])
    }
  },
  { immediate: true },
)

function toggle(id: number) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function toggleFull(id: number) {
  const next = new Set(fullOpen.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  fullOpen.value = next
}

function selectVisible() {
  const next = new Set(selected.value)
  for (const row of visibleRows.value) next.add(row.id)
  selected.value = next
}

function clearVisible() {
  const next = new Set(selected.value)
  for (const row of visibleRows.value) next.delete(row.id)
  selected.value = next
}

function invertVisible() {
  const next = new Set(selected.value)
  for (const row of visibleRows.value) {
    if (next.has(row.id)) next.delete(row.id)
    else next.add(row.id)
  }
  selected.value = next
}

function submit() {
  if (!validReplacements.value.length || !selectedCount.value) return
  const items = selectedRows.value.map((r) => ({
    promptId: r.id,
    seed: r.seed,
    promptOverride: r.replaced,
  }))
  emit('submit', {
    types: validReplacements.value.map((r) => r.type),
    workflowPath: wfPath.value,
    quality: caps.value.quality ? quality.value : '4K',
    aspectRatio: caps.value.orientation ? (aspectRatio.value || defaultRatio.value) : '',
    items,
  })
}
</script>

<template>
  <Modal
    :open="open"
    :title="lockedId ? '替换碎片出图' : '批量替换碎片'"
    width="min(1180px, 96vw)"
    height="min(720px, 88vh)"
    @close="emit('close')"
  >
    <template #head>
      <div class="tabs">
        <button class="btn btn-sm" :class="{ active: tab === 'config' }" @click="tab = 'config'">
          配置
        </button>
        <button class="btn btn-sm" :class="{ active: tab === 'job' }" @click="tab = 'job'">
          任务与结果
          <template v-if="job"> · {{ job.done_count ?? 0 }}/{{ job.total ?? 0 }}</template>
        </button>
      </div>
    </template>

    <div v-if="tab === 'config'" class="pane">
      <div class="context">
        <div class="context-row">
          <span class="step-no">1</span>
          <span class="step-title">范围与工作流</span>

          <div v-if="!lockedId" class="seg">
            <button
              class="btn btn-sm"
              :class="{ on: scope === 'selected' }"
              :disabled="!selectedIds.length"
              :title="selectedIds.length ? '只处理左侧已勾选的提示词' : '左侧还没有勾选'"
              @click="scope = 'selected'"
            >
              已勾选 {{ selectedIds.length }} 条
            </button>
            <button
              class="btn btn-sm"
              :class="{ on: scope === 'filtered' }"
              title="处理当前筛选下的全部提示词"
              @click="scope = 'filtered'"
            >
              当前筛选全部
            </button>
          </div>

          <span class="wf-label">出图工作流</span>
          <WorkflowPicker v-model="wfPath" :workflows="workflows" />
        </div>

        <div class="context-row settings-row">
          <span class="wf-label">出图设置</span>
          <WorkflowParams
            v-model:quality="quality"
            v-model:orientation="orientation"
            v-model:aspect-ratio="aspectRatio"
            :aspect-ratios="aspectRatios"
            :default-ratio="defaultRatio"
            :workflow-path="wfPath"
            :caps="caps"
            :quality-options="qualityOptions"
          />
          <span class="hint">原生 = 工作流基准；推荐 = 工作流原生比例</span>
        </div>

        <div class="context-row policy-row">
          <span class="hint">清单里每个类型单独设置「缺少时」策略；只改清单里的类型，其他块原样保留</span>
          <button
            class="btn btn-sm ghost"
            title="清除已记住的替换清单与工作流"
            @click="resetOptions"
          >
            重置选项
          </button>
          <span class="spacer" />
          <span v-if="!caps.prompt" class="warn">当前工作流不注入提示词，无法替换出图</span>
        </div>
      </div>

      <div class="main">
        <section class="left">
          <div class="panel-head">
            <span class="step-no">2</span>
            <span class="step-title">替换清单</span>
            <span class="spacer" />
            <span class="count">
              已添加 {{ rows.length }} 类
              <template v-if="validReplacements.length !== rows.length">
                · {{ validReplacements.length }} 类就绪
              </template>
            </span>
          </div>

          <select
            class="add-type"
            :value="''"
            :disabled="!addableTypes.length"
            @change="onAddType"
          >
            <option value="">
              {{ addableTypes.length ? '＋ 添加碎片类型…' : '8 类都已添加' }}
            </option>
            <option v-for="t in addableTypes" :key="t" :value="t">【{{ t }}】</option>
          </select>

          <div v-if="rows.length" class="chips">
            <button
              v-for="row in rows"
              :key="row.key"
              class="chip"
              :class="{ active: row.key === activeKey, empty: !row.content.trim() }"
              :title="row.content.trim() || '还没有替换内容'"
              @click="activate(row.key)"
            >
              <span class="chip-type">【{{ row.type || '未选类型' }}】</span>
              <span v-if="row.missing === 'append'" class="chip-badge">追加</span>
              <span class="chip-x" title="移除这一项" @click.stop="removeRow(row.key)">×</span>
            </button>
          </div>

          <template v-if="activeRow">
            <div class="editor-head">
              <select v-model="activeRow.type" class="type-select">
                <option value="">选择碎片类型…</option>
                <option v-for="t in selectableTypes(activeRow)" :key="t" :value="t">
                  【{{ t }}】
                </option>
              </select>

              <div class="seg missing-seg">
                <span class="muted">缺少该类型时</span>
                <button
                  class="btn btn-sm"
                  :class="{ on: activeRow.missing === 'skip' }"
                  title="没有目标【类型】的提示词直接跳过"
                  @click="activeRow.missing = 'skip'"
                >
                  跳过
                </button>
                <button
                  class="btn btn-sm"
                  :class="{ on: activeRow.missing === 'append' }"
                  title="没有目标【类型】时，在提示词末尾追加一段"
                  @click="activeRow.missing = 'append'"
                >
                  在末尾追加
                </button>
              </div>

              <span class="spacer" />
              <span class="count">{{ activeContent.length }} 字</span>
              <button
                v-if="activeRow.content"
                class="btn btn-sm"
                title="清空替换内容"
                @click="activeRow.content = ''"
              >
                清空
              </button>
            </div>

            <textarea
              v-model="activeRow.content"
              class="content-input"
              spellcheck="false"
              :placeholder="`只替换目标【${activeRow.type || '类型'}】块，其他块原样保留；也可以直接手写`"
            />

            <div class="panel-head">
              <span>候选碎片</span>
              <span class="count">
                {{ candidates.length }} 条 · 来自提示词与碎片库
              </span>
            </div>
            <input
              v-model="fragQuery"
              class="cand-search"
              type="search"
              placeholder="搜索候选内容，例如：纤细、短发、夜景…"
            />

            <div v-if="filteredCandidates.length" class="cand-list">
              <button
                v-for="c in filteredCandidates"
                :key="`${c.source}-${c.fragment_id ?? c.prompt_id}-${c.content}`"
                class="cand-row"
                :class="{ on: c.content === activeContent }"
                :title="c.content"
                @click="useCandidate(c)"
              >
                <span class="cand-content">{{ c.content }}</span>
                <span class="cand-meta">
                  {{ c.source === 'library' ? '碎片库' : c.prompt_name || '提示词' }}
                  <i v-if="c.dup_count > 1">×{{ c.dup_count }}</i>
                </span>
              </button>
            </div>
            <div v-else class="empty-line">
              <template v-if="!activeRow.type">先选择碎片类型</template>
              <template v-else-if="candidatesLoading">正在读取候选碎片…</template>
              <template v-else-if="fragQuery.trim()">没有匹配的候选，可直接手写</template>
              <template v-else>这类碎片在提示词库和碎片库里都还没有，可直接手写</template>
            </div>
          </template>
          <div v-else class="empty-line">
            还没有替换项。先从上方添加一个碎片类型，再填替换内容。
          </div>
        </section>

        <section class="right">
          <div class="panel-head right-head">
            <span class="step-no">3</span>
            <span class="step-title">将发生什么</span>
            <span
              v-if="lockedId"
              class="scope-chip"
              :title="`仅当前提示词：${lockPromptName || `#${lockedId}`}`"
            >
              仅当前提示词 · {{ lockPromptName || `#${lockedId}` }}
            </span>
            <span class="spacer" />
            <span class="count">
              已选 {{ selectedCount }} / {{ matchedAll.length }}
              <template v-if="promptQuery.trim()"> · 可见 {{ visibleRows.length }}</template>
              <template v-if="hiddenSelectedCount"> · 隐藏 {{ hiddenSelectedCount }}</template>
            </span>
          </div>

          <div class="op-summary" aria-live="polite">
            <template v-if="!rows.length">
              <span class="muted">先添加碎片类型</span>
            </template>
            <template v-else-if="!validReplacements.length">
              <span class="muted">填好至少一项替换内容后显示匹配数量</span>
            </template>
            <template v-else>
              <span>替换 <b>{{ replacedCells }}</b> 处</span>
              <span class="sep">·</span>
              <span>追加 <b>{{ appendedCells }}</b> 处</span>
              <template v-if="skippedCells">
                <span class="sep">·</span>
                <span>跳过 <b>{{ skippedCells }}</b> 处</span>
              </template>
              <span class="spacer" />
              <span class="muted">
                范围 {{ totalCount }} 条
                <template v-if="unmatchedCount"> · 未命中 {{ unmatchedCount }}</template>
              </span>
            </template>
          </div>

          <div class="list-toolbar">
            <input
              v-model="promptQuery"
              class="prompt-search"
              type="search"
              placeholder="按名称或原碎片过滤"
            />
            <button class="btn btn-sm" :disabled="!visibleRows.length" @click="selectVisible">
              全选
            </button>
            <button class="btn btn-sm" :disabled="!visibleRows.length" @click="clearVisible">
              取消全选
            </button>
            <button class="btn btn-sm" :disabled="!visibleRows.length" @click="invertVisible">
              反选
            </button>
          </div>

          <div v-if="visibleRows.length" class="prompt-list">
            <article
              v-for="row in visibleRows"
              :key="row.id"
              class="row diff-card"
              :class="{ picked: selected.has(row.id) }"
              :title="row.replaced"
            >
              <header class="diff-head">
                <label class="pick">
                  <input
                    type="checkbox"
                    :checked="selected.has(row.id)"
                    @change="toggle(row.id)"
                  />
                  <span class="name">{{ row.name }}</span>
                </label>
                <span v-if="row.appendedCount" class="tag append-tag">
                  追加 {{ row.appendedCount }}
                </span>
                <span v-if="row.replacedCount" class="tag replace-tag">
                  替换 {{ row.replacedCount }}
                </span>
                <span class="spacer" />
                <button class="btn btn-sm" @click="toggleFull(row.id)">
                  {{ fullOpen.has(row.id) ? '收起完整提示词' : '完整提示词' }}
                </button>
              </header>

              <div class="diff-body">
                <template v-for="o in row.outcomes" :key="o.type">
                  <div v-if="o.action === 'appended'" class="diff-note">
                    原提示词没有【{{ o.type }}】，将在末尾新增该块。
                  </div>
                  <div v-else class="diff-block old-block">
                    <span class="diff-label">原【{{ o.type }}】</span>
                    <span class="old" :title="o.oldContent">
                      {{ o.oldContent || '（该块为空）' }}
                    </span>
                  </div>
                  <div class="diff-block new-block">
                    <span class="diff-label">{{ o.action === 'appended' ? '将新增' : '替换为' }}</span>
                    <span class="new">{{ o.content }}</span>
                  </div>
                </template>
                <div v-if="row.skipped.length" class="diff-note muted">
                  未改：{{ row.skipped.map((t) => `【${t}】`).join('、') }}（原提示词没有这些类型）
                </div>
                <div v-if="fullOpen.has(row.id)" class="full-prompt">
                  <span class="diff-label">完整提示词（替换后）</span>
                  <pre>{{ row.replaced }}</pre>
                </div>
              </div>
            </article>
          </div>
          <div v-else class="empty-line">
            <template v-if="!rows.length">先添加碎片类型</template>
            <template v-else-if="!validReplacements.length">填好替换内容后，这里会逐条展示旧 → 新差异</template>
            <template v-else-if="promptQuery.trim()">没有匹配的提示词</template>
            <template v-else>
              这个范围里没有命中清单中任何类型的提示词；可调整类型，或把缺失策略改为「在末尾追加」。
            </template>
          </div>
        </section>
      </div>
    </div>

    <div v-else class="job-pane">
      <div v-if="jobLoading" class="job-empty">正在读取任务…</div>
      <div v-else-if="!job" class="job-empty">
        还没有替换出图任务。提交后会切到这里，实时显示进度与出图结果。
      </div>
      <template v-else>
        <div class="job-summary">
          <span class="job-status" :class="job.status">{{ statusLabel(job.status) }}</span>
          <span class="job-count">{{ job.done_count ?? 0 }}/{{ job.total ?? 0 }}</span>
          <span class="job-meta">耗时 {{ elapsedText(job) || '—' }}</span>
          <span class="job-meta">{{ finishText(job) }}</span>
          <span class="spacer" />
          <span v-if="job.workflow_path" class="job-meta" :title="job.workflow_path">
            {{ workflowName(job.workflow_path) }}
            <template v-if="job.quality"> · {{ job.quality }}</template>
          </span>
        </div>

        <div class="job-progress">
          <div class="job-bar" :class="job.status" :style="{ width: `${jobPercent(job)}%` }" />
        </div>

        <p class="job-hint">
          关闭弹窗不会中断任务；进度与结果也可以在「任务」页继续查看。
        </p>

        <div class="res-list">
          <article v-for="(row, idx) in job.items ?? []" :key="idx" class="res-item">
            <button
              v-if="row.images?.[0]"
              class="res-thumb"
              type="button"
              :title="`查看原图：${row.images[0].filename}`"
              @click="previewImage(row.images[0])"
            >
              <img :src="thumbUrl(row.images[0])" :alt="row.images[0].filename" loading="lazy" />
            </button>
            <span v-else class="res-thumb placeholder">…</span>

            <div class="res-body">
              <div class="res-prompt" :title="row.prompt_preview ?? ''">
                {{ row.prompt_preview || '（无预览）' }}
              </div>
              <div class="res-meta">
                <span :class="['res-status', row.status]">
                  {{ row.submit_state === 'queued' ? '排队中' : statusLabel(row.status) }}
                </span>
                <span v-if="row.seed" class="job-meta">seed {{ row.seed }}</span>
                <span v-if="row.error" class="res-error">{{ row.error }}</span>
              </div>
            </div>

            <button
              v-if="row.images?.[0]"
              class="btn btn-sm"
              type="button"
              title="在资源管理器中定位原图"
              @click="revealImage(row.images[0])"
            >
              定位
            </button>
          </article>
          <div v-if="!job.items?.length" class="job-empty">无明细</div>
        </div>
      </template>
    </div>

    <template #footer>
      <template v-if="tab === 'config'">
        <span class="note">只影响本次出图，不修改提示词库</span>
        <span class="spacer" />
        <button class="btn btn-sm" @click="emit('close')">取消</button>
        <button
          class="btn btn-sm primary"
          :disabled="!selectedCount || !caps.prompt || !wfPath"
          @click="submit"
        >
          {{ submitLabel }}
        </button>
      </template>
      <template v-else>
        <span class="note">关闭弹窗后任务继续执行</span>
        <span class="spacer" />
        <button class="btn btn-sm" @click="tab = 'config'">继续替换</button>
        <button class="btn btn-sm" @click="emit('go-jobs')">打开任务页</button>
        <button class="btn btn-sm primary" @click="emit('close')">关闭</button>
      </template>
    </template>

    <Lightbox
      v-if="previewOpen"
      :items="previewItems"
      :index="0"
      :readonly="previewReadonly"
      :workflows="workflows"
      @close="closePreviewImage"
      @jump-to-prompt="(id) => emit('jump-to-prompt', id)"
    />
  </Modal>
</template>

<style scoped>
.tabs {
  display: flex;
  gap: var(--gap-xs);
}

.pane {
  box-sizing: border-box;
  height: 100%;
  padding: var(--gap) var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

/* ---------- 任务与结果页签 ---------- */

.job-pane {
  box-sizing: border-box;
  height: 100%;
  padding: var(--gap) var(--gap-lg);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.job-empty {
  flex: 1;
  display: grid;
  place-items: center;
  padding: var(--gap-2xl);
  color: var(--muted);
  font-size: var(--fs-sm);
  text-align: center;
}

.job-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--gap);
  font-size: var(--fs-sm);
}

.job-status {
  font-weight: 600;
}

.job-status.running,
.job-status.pending {
  color: var(--primary);
}

.job-status.done {
  color: var(--success);
}

.job-status.error,
.job-status.cancelled,
.job-status.stopped {
  color: var(--danger);
}

.job-count {
  font-variant-numeric: tabular-nums;
  color: var(--text);
}

.job-meta {
  color: var(--muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.job-progress {
  flex: none;
  height: 4px;
  border-radius: var(--radius-pill);
  background: var(--panel-3);
  overflow: hidden;
}

.job-bar {
  height: 100%;
  background: var(--primary);
  transition: width 0.3s;
}

.job-bar.done {
  background: var(--success);
}

.job-bar.error {
  background: var(--danger);
}

.job-hint {
  margin: 0;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.res-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.res-item {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.res-thumb {
  flex: none;
  width: 96px;
  height: 96px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--panel-3);
  overflow: hidden;
  display: grid;
  place-items: center;
  cursor: zoom-in;
}

.res-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.res-thumb.placeholder {
  color: var(--muted);
  cursor: default;
}

.res-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.res-prompt {
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.res-meta {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: var(--fs-xs);
}

.res-status.done {
  color: var(--success);
}

.res-status.error {
  color: var(--danger);
}

.res-status.running,
.res-status.pending {
  color: var(--primary);
}

.res-error {
  color: var(--danger);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.res-item > .btn {
  flex: none;
}

.context {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.context-row {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex-wrap: wrap;
  min-width: 0;
}

/* 工作流吃满这一行剩下的宽度：完整名称不再被压到 242px */
.context-row .wf-picker {
  flex: 1 1 260px;
  max-width: none;
}

.policy-row {
  gap: var(--gap-sm);
}

.muted {
  color: var(--muted);
}

.hint {
  color: var(--muted);
  font-size: var(--fs-xs);
  white-space: nowrap;
}

.missing-seg {
  align-items: center;
}

.missing-seg .muted {
  color: var(--muted);
  font-size: var(--fs-xs);
  white-space: nowrap;
}

.step-no,
.panel-head .step-no {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: var(--fs-xs);
  font-weight: 600;
  flex: none;
}

.step-title {
  font-weight: 600;
  font-size: var(--fs-sm);
  color: var(--text);
}

.type-select {
  min-width: 150px;
}

.add-type {
  width: 100%;
  box-sizing: border-box;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-xs);
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-xs);
  padding: 2px 6px 2px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--panel);
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: 1.6;
  cursor: pointer;
}

.chip:hover {
  border-color: var(--border-strong);
}

.chip.active {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}

.chip.empty .chip-type {
  color: var(--warn);
}

.chip-badge {
  padding: 0 4px;
  border-radius: var(--radius-pill);
  background: var(--primary-soft);
  color: var(--primary);
  font-size: var(--fs-xs);
}

.chip-x {
  padding: 0 2px;
  color: var(--muted);
  font-size: var(--fs-sm);
}

.chip-x:hover {
  color: var(--danger);
}

.editor-head {
  display: flex;
  align-items: center;
  gap: var(--gap-xs);
  flex-wrap: wrap;
  min-width: 0;
}

.wf-label {
  flex: none;
  color: var(--muted);
  font-size: var(--fs-xs);
  white-space: nowrap;
}

.seg {
  display: flex;
  gap: var(--gap-xs);
}

.seg .btn.on {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}

.main {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: var(--gap);
  align-items: stretch;
}

.left,
.right {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  padding: var(--gap-sm);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
}

.panel-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
  font-size: var(--fs-sm);
  color: var(--muted);
}

.right-head {
  flex-wrap: wrap;
  row-gap: var(--gap-xs);
}

/* 锁定提示词是上下文，不是按钮：描边弱化，避免和可点控件抢注意力 */
.scope-chip {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  color: var(--muted);
  font-size: var(--fs-xs);
}

.op-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-sm);
  min-height: 30px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--muted);
  font-size: var(--fs-sm);
}

.op-summary b {
  color: var(--text);
  font-weight: 600;
}

.op-summary .sep {
  color: var(--border-strong);
}

.content-input {
  width: 100%;
  box-sizing: border-box;
  flex: 0 0 104px;
  height: 104px;
  min-height: 104px;
  max-height: none;
  resize: none;
  font: inherit;
  font-size: var(--fs-sm);
  line-height: 1.5;
  color: var(--text);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 6px 8px;
}

.cand-search,
.prompt-search {
  width: 100%;
  box-sizing: border-box;
}

.prompt-search {
  flex: 1 1 200px;
  min-width: 140px;
  width: auto;
}

.cand-list {
  flex: 1 1 auto;
  min-height: 160px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px;
  background: var(--panel);
}

.cand-row {
  display: flex;
  flex-direction: column;
  gap: 1px;
  text-align: left;
  padding: 4px 6px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text);
}

.cand-row:hover {
  background: var(--panel-3);
}

.cand-row.on {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.cand-content {
  font-size: var(--fs-sm);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.cand-meta {
  font-size: var(--fs-xs);
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.list-toolbar {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex-wrap: wrap;
}

.prompt-list {
  flex: 1;
  min-height: 160px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--gap-xs);
  background: var(--panel);
}

.empty-line {
  flex: 1;
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 14px;
  color: var(--muted);
  font-size: var(--fs-sm);
  line-height: 1.55;
}

/* 每条提示词一张差异卡：旧块/新块完整换行，不再单行省略 */
.row.diff-card {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  padding: var(--gap-sm);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  font-size: var(--fs-sm);
}

.row.diff-card:hover {
  border-color: var(--border-strong);
}

.row.diff-card.picked {
  border-color: var(--primary);
  box-shadow: inset 2px 0 0 var(--primary);
}

.diff-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
}

.pick {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  min-width: 0;
  cursor: pointer;
}

.name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-sm);
  font-weight: 600;
}

.tag {
  flex: none;
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  font-size: var(--fs-xs);
  line-height: 1.6;
}

.append-tag {
  background: var(--primary-soft);
  color: var(--primary);
}

.replace-tag {
  background: color-mix(in srgb, var(--success) 14%, transparent);
  color: var(--success);
}

.diff-body {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.diff-note {
  color: var(--muted);
  font-size: var(--fs-sm);
}

.diff-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 5px 8px;
  border-left: 2px solid var(--border-strong);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  background: var(--panel);
}

.new-block {
  border-left-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 8%, transparent);
}

.diff-label {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.new-block .diff-label {
  color: var(--primary);
}

.old,
.new {
  display: block;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: var(--fs-sm);
  line-height: 1.55;
}

.old {
  color: var(--muted);
}

.new {
  color: var(--text);
}

.full-prompt {
  padding-top: 6px;
  border-top: 1px dashed var(--border);
}

.full-prompt pre {
  margin: 2px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font: inherit;
  font-size: var(--fs-sm);
  line-height: 1.55;
  color: var(--text);
}

.count {
  color: var(--muted);
  font-size: var(--fs-sm);
  white-space: nowrap;
}

.warn {
  color: var(--warn);
  font-size: var(--fs-sm);
}

.note {
  color: var(--muted);
  font-size: var(--fs-sm);
}

.spacer {
  flex: 1;
}

@media (max-width: 900px) {
  .main {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .left,
  .right {
    min-height: 420px;
  }

  /* 窄屏时工作流独占一行，避免和类型/范围抢位置 */
  .context-row .wf-picker {
    flex-basis: 100%;
  }
}
</style>
