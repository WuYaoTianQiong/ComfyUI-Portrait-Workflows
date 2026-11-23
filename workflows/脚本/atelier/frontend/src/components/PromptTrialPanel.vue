<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'

import Modal from './Modal.vue'
import Icon from './Icon.vue'
import WorkflowPicker from './WorkflowPicker.vue'
import FlowParamsRow from './FlowParamsRow.vue'
import PromptMatrixStack from './PromptMatrixStack.vue'
import PromptCreateModal from './PromptCreateModal.vue'
import CompareModal from './CompareModal.vue'
import Lightbox from './Lightbox.vue'
import { useSettings } from '../composables/useSettings'
import { useMatrixFlowParams } from '../composables/useMatrixFlowParams'
import { useWorkflows, customWorkflowContent } from '../composables/useWorkflows'
import { useGenerate } from '../composables/useGenerate'
import { usePromptMatrix } from '../composables/usePromptMatrix'
import { buildRunTextRequest } from '../composables/useRunParams'
import { useImagePreview, resolveHistoryItems } from '../composables/useImagePreview'
import { useToast } from '../composables/useToast'
import { availableTiers } from '../composables/useWorkflowMatrix'
import { CANONICAL_RATIOS, QUALITY_SCALES } from '../composables/useWorkflowCaps'
import { normalizeQualityKey } from '../composables/useWorkflowQuality'
import { workflowDisplayName } from '../composables/recipeModel'
import { linkImagesToPrompt } from '../api/images'
import { apiGet } from '../api/client'
import type { HistoryItem, JobSnapshot } from '../api/types'
import type { WorkflowRow } from '../composables/useWorkflows'
import type { MatrixAlign, MatrixImage } from '../composables/useWorkflowMatrix'
import type { MatrixBatch } from '../composables/usePromptMatrix'
import type { RerunInitial } from '../composables/useRerunDraft'

/**
 * 临时试跑工作台。
 *
 * 与详情页横评的分工：详情页跑**库内提示词**，这里跑**外来文本**（不写回库，
 * 空库也能用）。两者共用 `usePromptMatrix` 一套引擎，多选、逐流档位回退、
 * 同种子、一格一 job、矩阵结果的口径完全一致，不用学两套。
 *
 * 左右双栏：左边文本吃满弹窗高度（长提示词不用反复滚动），
 * 右边参数常驻 + 结果堆叠。结果矩阵按列=工作流转置，
 * 竖图并排吃满右栏宽度，不再是旧版 300px 窄条留白。
 * 文本与结果同屏，改一句话就能再跑一轮对比。
 *
 * 闭环：跑 → 满意 → 「存为提示词」新建一条并把**整批图**认领过去，
 * 否则新提示词的出图历史是空的。
 */
const props = withDefaults(
  defineProps<{
    open: boolean
    /** 当前选中的提示词：只用于「归档到」选项，不当载体预填文本。 */
    promptId: number | null
    promptName: string
    /** 入口：试跑写自有草稿；rerun 从画廊「以这张图为模板重跑」打开，状态单独隔离。 */
    scope?: 'trial' | 'rerun'
    /** rerun 入口带入的图片参数；trial 为 null，仍读 localStorage 草稿。 */
    initial?: RerunInitial | null
    /** 开在灯箱里面时必须抬一层，否则被查看器盖住。 */
    raised?: boolean
  }>(),
  { scope: 'trial', initial: null, raised: false },
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', id: number): void
}>()

const isRerun = computed(() => props.scope === 'rerun')

/** 两个入口各存一份：trial 沿用旧键（旧数据不失效），rerun 独立，互不串台。 */
const textKey = computed(() => (isRerun.value ? 'pb.rerunDraft' : 'pb.trialDraft'))
/** 除文本外的面板设置：关掉弹窗再打开要能接着用，不能每次都回默认。 */
const settingsKey = computed(() => (isRerun.value ? 'pb.rerunSettings' : 'pb.trialSettings'))
/** storeKey 在组合式函数创建时一次性读取；入口在实例生命周期内不变，按当前 scope 算即可。 */
const matrixStoreKey = isRerun.value ? 'pb.rerunMatrix' : 'pb.trialMatrix'
const settings = useSettings()
const toast = useToast()
const queryClient = useQueryClient()

interface TrialSettings {
  workflowPath?: string
  orientation?: string
  seed?: string
  count?: number
  lock?: boolean
  linkArchive?: boolean
}

function readSettings(): TrialSettings {
  try {
    const raw = localStorage.getItem(settingsKey.value)
    return raw ? (JSON.parse(raw) as TrialSettings) : {}
  } catch {
    return {}
  }
}

const savedSettings = readSettings()

/** 本面板自己的工作流/方向：改这里不该顺带改掉详情页的单跑默认。 */
const workflowPath = ref(savedSettings.workflowPath || settings.workflowPath.value)
const orientation = ref(savedSettings.orientation || settings.orientation.value)
const { workflows, allWorkflows } = useWorkflows()

/**
 * 逐流参数的读写句柄：比例/画质都沿用「按工作流记忆」的同一份存储，
 * 计划层与逐流行读到的是同一组 ref，改一行只影响那一个工作流。
 */
const flowParams = useMatrixFlowParams()
const { overrides: flowOverrides } = flowParams

const { queue, error: runError, submitAndTrack, trackQueued } = useGenerate('prompt-trial', { queue: true })

function readDraft(): { prompt: string; negative: string } {
  try {
    const raw = localStorage.getItem(textKey.value)
    if (!raw) return { prompt: '', negative: '' }
    const parsed = JSON.parse(raw) as { prompt?: string; negative?: string }
    return { prompt: parsed.prompt ?? '', negative: parsed.negative ?? '' }
  } catch {
    return { prompt: '', negative: '' }
  }
}

const initialDraft = readDraft()
const promptText = ref(initialDraft.prompt)
const negative = ref(initialDraft.negative)
const negativeExpanded = ref(Boolean(initialDraft.negative))
const seedInput = ref(savedSettings.seed ?? '')
/** rerun 入口没有归档下拉，linkArchive 从一开始就不参与任何判断。 */
const linkArchive = ref(!isRerun.value && Boolean(savedSettings.linkArchive) && Boolean(props.promptId))

/** 文本落盘：关掉弹窗再打开还能接着改，不用重新粘一遍。 */
watch([promptText, negative], () => {
  try {
    localStorage.setItem(textKey.value, JSON.stringify({ prompt: promptText.value, negative: negative.value }))
  } catch {
    /* 隐私模式下忽略 */
  }
})

/** 选中的提示词被切走/删掉时，归档选项必须跟着失效。 */
watch(
  () => props.promptId,
  (id) => {
    if (!id) linkArchive.value = false
  },
)

const matrix = usePromptMatrix({
  scope: () => (isRerun.value ? 'rerun' : 'trial'),
  storeKey: matrixStoreKey,
  promptText: () => promptText.value,
  negativeText: () => negative.value,
  savedSeed: () => null,
  workflows: () => workflows.value,
  currentWorkflow: () => workflowPath.value,
  // 试跑没有「全局一套参数」：每行用自己的比例/档位，这里只做兜底。
  ratio: () => '',
  tier: () => '1.0x',
  overrides: (paths) => flowOverrides(paths),
  orientation: () => orientation.value,
  submit: (req) =>
    submitAndTrack<{ success: boolean; job_id?: number | null }>(
      '/api/runs/text',
      buildRunTextRequest({
        prompt: req.prompt,
        negativePrompt: req.negative,
        workflowPath: req.path,
        workflowContent: customWorkflowContent(req.path),
        quality: req.tier,
        orientation: req.orientation,
        aspectRatio: req.ratio,
        seed: req.seed,
        sourcePromptId: isRerun.value
          ? (props.initial?.sourcePromptId ?? 0)
          : linkArchive.value && props.promptId ? props.promptId : 0,
      }),
    ),
  track: trackQueued,
  fetchJob: (id) => apiGet<JobSnapshot>(`/api/jobs/${id}`).catch(() => null),
  jobs: () => queue.value,
  refreshShots: () => {
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

// 张数 / 同种子锁定在组合式函数里，创建后套用上次的值（张数 1~4，由 setCount 夹紧）
if (typeof savedSettings.count === 'number') matrix.setCount(savedSettings.count)
if (typeof savedSettings.lock === 'boolean') matrix.lockSeed = savedSettings.lock

/** rerun 入口：整套参数取自那张图，覆盖掉本入口上次的记忆。 */
function applyInitial(initial: RerunInitial) {
  promptText.value = initial.prompt
  negative.value = initial.negative
  negativeExpanded.value = Boolean(initial.negative)
  workflowPath.value = initial.workflowPath || settings.workflowPath.value
  seedInput.value = initial.seed === null ? '' : String(initial.seed)
  matrix.lockSeed = true
  matrix.setCount(initial.count || 1)

  if (!initial.workflowPath) return
  matrix.setPaths([initial.workflowPath])
  if (initial.ratio) flowParams.setRatio([initial.workflowPath], initial.ratio)
  if (initial.tier) flowParams.setTier([initial.workflowPath], initial.tier)
}

/**
 * 每次打开按入口就位：带 initial（画廊「以这张图为模板重跑」）就整套预填，
 * 否则维持试跑读草稿的老行为。
 */
watch(
  () => props.open,
  (open) => {
    if (!open) return
    if (props.initial) {
      applyInitial(props.initial)
      return
    }
    if (!workflowPath.value) workflowPath.value = settings.workflowPath.value
  },
  { immediate: true },
)

/** 面板设置落盘：文本之外的每一项都记，重开弹窗不该回默认。 */
watch(
  [workflowPath, orientation, seedInput, () => matrix.count, () => matrix.lockSeed, linkArchive],
  () => {
    try {
      const payload: TrialSettings = {
        workflowPath: workflowPath.value,
        orientation: orientation.value,
        seed: seedInput.value,
        count: matrix.count,
        lock: matrix.lockSeed,
        linkArchive: linkArchive.value,
      }
      localStorage.setItem(settingsKey.value, JSON.stringify(payload))
    } catch {
      /* 隐私模式下忽略 */
    }
  },
)

/**
 * 选择器里看不到的流（文件改名 / 被隐藏 / 已删除）不该继续占一行：
 * 持久化的 paths 可能比现有工作流旧，芯片按可见列表反查会自然消失，
 * 逐流参数行却是按原始 paths 铺的，不清理就会多出几行点不动的空行。
 */
const knownPaths = computed(() => new Set(workflows.value.map((wf) => wf.path)))
const pickedPaths = computed(() => matrix.paths.filter((path) => knownPaths.value.has(path)))

watch(
  [() => workflows.value.map((wf) => wf.path).join('\n'), () => matrix.paths],
  () => {
    if (!workflows.value.length || !matrix.paths.length) return
    if (pickedPaths.value.length !== matrix.paths.length) matrix.setPaths(pickedPaths.value)
  },
  { immediate: true },
)

const pickedWorkflows = computed(() =>
  pickedPaths.value
    .map((path) => allWorkflows.value.find((wf) => wf.path === path))
    .filter((wf): wf is WorkflowRow => Boolean(wf)),
)

/** 统一比例：列各流支持比例的并集；不支持的流保持原值并单独提示。 */
const unionRatios = computed(() => {
  const set = new Set<string>()
  for (const wf of pickedWorkflows.value) {
    if (wf.caps && !wf.caps.orientation) continue
    for (const ratio of wf.params?.aspect_ratios ?? []) set.add(ratio)
  }
  if (!set.size) {
    // 探测没给 aspect_ratios 时，退回尺寸预演里出现过的比例
    for (const wf of pickedWorkflows.value) {
      for (const byRatio of Object.values(wf.size_preview ?? {})) {
        for (const ratio of Object.keys(byRatio)) if (ratio !== '*') set.add(ratio)
      }
    }
  }
  return [
    ...CANONICAL_RATIOS.filter((ratio) => set.has(ratio)),
    ...[...set].filter((ratio) => !(CANONICAL_RATIOS as readonly string[]).includes(ratio)),
  ]
})

/** 统一分辨率：档位统一是相对倍率，各流实际像素仍按自己的 size_preview 求解。 */
const unionTiers = computed(() => {
  const set = new Set<string>()
  for (const wf of pickedWorkflows.value) {
    const tiers = availableTiers(wf).map(normalizeQualityKey)
    // 探测没给档位时按「全档可用」处理，与 resolveTier 的兜底一致
    if (!tiers.length) return QUALITY_SCALES.map((tier) => tier.value)
    for (const tier of tiers) set.add(tier)
  }
  return QUALITY_SCALES.map((tier) => tier.value).filter((value) => set.has(value))
})

const bulkRatio = ref('')
const bulkTier = ref('')
const ratioSkips = ref<string[]>([])
const tierSkips = ref<string[]>([])

function shortName(wf: WorkflowRow): string {
  return workflowDisplayName(wf.name).replace(/_/g, ' ')
}

function storedRatio(wf: WorkflowRow): string {
  return flowParams.flowParamsFor(wf.path).ratio.value || wf.params?.default_ratio || '原生'
}

function applyBulkRatio(ratio: string) {
  bulkRatio.value = ratio
  ratioSkips.value = []
  if (!ratio) return
  const ok: string[] = []
  for (const wf of pickedWorkflows.value) {
    const ratios = wf.params?.aspect_ratios ?? []
    if ((wf.caps && !wf.caps.orientation) || !ratios.length) {
      ratioSkips.value.push(`${shortName(wf)} 不支持可调比例，保持 ${storedRatio(wf)}`)
    } else if (!ratios.includes(ratio)) {
      ratioSkips.value.push(`${shortName(wf)} 不支持 ${ratio}，保持 ${storedRatio(wf)}`)
    } else {
      ok.push(wf.path)
    }
  }
  flowParams.setRatio(ok, ratio)
}

function applyBulkTier(tier: string) {
  bulkTier.value = tier
  tierSkips.value = []
  if (!tier) return
  const ok: string[] = []
  for (const wf of pickedWorkflows.value) {
    const tiers = availableTiers(wf).map(normalizeQualityKey)
    const current = flowParams.flowParamsFor(wf.path).tier.value
    if (wf.caps && !wf.caps.quality) {
      tierSkips.value.push(`${shortName(wf)} 不支持画质档，保持 ${current}`)
    } else if (tiers.length && !tiers.includes(tier)) {
      tierSkips.value.push(`${shortName(wf)} 不支持 ${tier}，保持 ${current}`)
    } else {
      ok.push(wf.path)
    }
  }
  flowParams.setTier(ok, tier)
}

/** 与统一值不一致的流数：逐流微调入口直接把差异量报出来，改完不一目了然。 */
const diffCount = computed(() => {
  if (!bulkRatio.value && !bulkTier.value) return 0
  return pickedWorkflows.value.filter((wf) => {
    const refs = flowParams.flowParamsFor(wf.path)
    return (
      (Boolean(bulkRatio.value) && refs.ratio.value !== bulkRatio.value) ||
      (Boolean(bulkTier.value) && refs.tier.value !== bulkTier.value)
    )
  }).length
})

/** 负向提示词至少有一个勾选流真正生效：逐流能力不同，不能只看单个工作流。 */
const negativeEffective = computed(() => {
  if (!pickedPaths.value.length) return true
  return pickedPaths.value.some(
    (path) => allWorkflows.value.find((w) => w.path === path)?.caps?.negative_effective === true,
  )
})

/** 各流比例不同时尺寸对齐没有统一口径：计划层已自动按原生档，控件也要如实显示。 */
const mixedRatio = computed(
  () => new Set(matrix.plan.usable.map((row) => row.ratio)).size > 1,
)

const alignOptions: Array<{ value: MatrixAlign; label: string }> = [
  { value: 'native', label: '各自原生档' },
  { value: 'first', label: '对齐到首个' },
  { value: 'ref', label: '对齐到 1024×1536' },
]

const charCount = computed(() => promptText.value.length)
const canRun = computed(
  () => promptText.value.trim().length > 0 && matrix.plan.usable.length > 0 && !matrix.submitting,
)
const planSummary = computed(() => {
  const p = matrix.plan
  if (!p.usable.length) return '勾选工作流后开始试跑'
  return `${p.usable.length} 个工作流 × ${p.count} 张 = ${p.total} 张`
})

function runTrial() {
  const raw = String(seedInput.value ?? '').trim()
  matrix.submit(raw === '' ? null : Number(raw))
}

function randomSeed() {
  seedInput.value = String(Math.floor(Math.random() * 2 ** 31))
}

function clearText() {
  promptText.value = ''
  negative.value = ''
  negativeExpanded.value = false
}

// ---------------- 看图 / 对比 ----------------

const { items: previewItems, readonly: previewReadonly, open: previewOpen, preview, close: closePreview } =
  useImagePreview()
const compareItems = ref<HistoryItem[]>([])
const compareOpen = ref(false)

function toRef(image: MatrixImage) {
  return { filename: image.filename, subfolder: image.subfolder, type: image.img_type }
}

function openImage(payload: { items: MatrixImage[]; index: number; prompt?: string; negative?: string }) {
  const target = payload.items[payload.index]
  if (target) {
    preview(toRef(target), {
      prompt: payload.prompt ?? promptText.value,
      negative: payload.negative ?? negative.value,
    })
  }
}

async function openCompare(images: MatrixImage[]) {
  if (images.length < 2) {
    toast.info('并排对比至少选 2 张')
    return
  }
  compareItems.value = await resolveHistoryItems(images.slice(0, 4).map(toRef))
  compareOpen.value = true
}

// ---------------- 存为提示词（按批认领整批图） ----------------

const saveOpen = ref(false)
const linking = ref(false)
const savingBatch = ref<MatrixBatch | null>(null)

const saveInitial = computed(() => ({
  prompt: savingBatch.value?.prompt || promptText.value,
  negative_prompt: savingBatch.value?.negative ?? negative.value,
  seed: savingBatch.value?.baseSeed || matrix.baseSeed || null,
}))

function startSave(batch: MatrixBatch) {
  if (!batch.cells.some((c) => c.status === 'done' && c.image)) {
    toast.error('这一批还没有出好的图')
    return
  }
  savingBatch.value = batch
  saveOpen.value = true
}

async function onCreated(id: number) {
  saveOpen.value = false
  const refs = (savingBatch.value?.cells ?? [])
    .filter((c) => c.status === 'done' && c.image)
    .map((c) => c.image as MatrixImage)
  linking.value = true
  try {
    // 任务快照只给文件名，认领需要图库 id：按名取回完整记录，取不到的跳过。
    const resolved = await resolveHistoryItems(refs.map(toRef))
    const ids = resolved.map((r) => r.id).filter((n) => n > 0)
    if (ids.length) {
      const result = await linkImagesToPrompt(ids, id)
      toast.success(`已存为提示词，并认领 ${result.linked} 张图`)
    } else {
      toast.info('已存为提示词；图还没入库，稍后可在画廊同步后认领')
    }
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({ queryKey: ['history'] })
    queryClient.invalidateQueries({ queryKey: ['prompt-history', id] })
  } catch (error) {
    toast.error(`认领图片失败：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    linking.value = false
    emit('created', id)
  }
}
</script>

<template>
  <Modal
    :open="open"
    :title="isRerun ? '以这张图为模板重跑' : '临时试跑'"
    :raised="raised"
    width="min(1760px, 96vw)"
    height="88vh"
    @close="emit('close')"
  >
    <template #head>
      <span class="head-sub">{{
        isRerun
          ? '参数取自这张图 · 改完只跑本次 · 不写回提示词库'
          : '外来文本 · 多工作流横评 · 不写回提示词库'
      }}</span>
    </template>

    <template #actions>
      <span v-if="linking" class="head-sub">正在认领图片…</span>
      <details v-if="!isRerun" class="more">
        <summary class="btn btn-sm">归档 ▾</summary>
        <div class="more-pop">
          <label class="radio">
            <input v-model="linkArchive" type="radio" :value="false" />
            不关联（档案标「临时提示词」）
          </label>
          <label v-if="promptId" class="radio">
            <input v-model="linkArchive" type="radio" :value="true" />
            关联到《{{ promptName || `#${promptId}` }}》
          </label>
          <p class="more-note">关联只影响图片归属，不会把文本写回那条提示词。</p>
        </div>
      </details>
    </template>

    <div class="trial-grid">
      <section class="pane pane-text">
        <div class="pane-head">
          <span class="pane-title">提示词</span>
          <span class="counter">{{ charCount }} 字</span>
          <span class="grow" />
          <button class="btn btn-sm" type="button" :disabled="!charCount" @click="clearText">清空</button>
        </div>
        <textarea
          v-model="promptText"
          class="big-text scroll"
          spellcheck="false"
          placeholder="把从别处复制的提示词粘进来。这里不依赖任何已存提示词，空库也能跑。"
        />
        <div class="neg">
          <div class="neg-head">
            <span class="pane-title">负面提示词</span>
            <span v-if="negative.trim() && !negativeEffective" class="warn-text">
              当前勾选的工作流负向不生效
            </span>
            <span class="grow" />
            <button class="btn btn-sm" type="button" @click="negativeExpanded = !negativeExpanded">
              {{ negativeExpanded ? '收起' : negative ? '展开' : '＋ 添加' }}
            </button>
          </div>
          <textarea
            v-if="negativeExpanded"
            v-model="negative"
            class="neg-input scroll"
            rows="3"
            spellcheck="false"
            placeholder="可留空"
          />
        </div>
      </section>

      <section class="controls">
          <div class="control-row">
            <WorkflowPicker
              :model-value="workflowPath"
              :workflows="workflows"
              multiple
              :selected="matrix.paths"
              :unavailable="matrix.unavailable"
              @update:model-value="workflowPath = $event"
              @update:selected="matrix.setPaths($event)"
            />
          </div>
          <div class="bulk">
            <label class="mini-field">
              <span>统一比例</span>
              <select
                :value="bulkRatio"
                :disabled="!unionRatios.length"
                :title="unionRatios.length
                  ? '一次设全部；不支持的流保持原值并在下面单独提示'
                  : '所选工作流都没有可调比例'"
                @change="applyBulkRatio(($event.target as HTMLSelectElement).value)"
              >
                <option value="">{{ unionRatios.length ? '未统一（各流各自记忆）' : '不可调比例' }}</option>
                <option v-for="ratio in unionRatios" :key="ratio" :value="ratio">{{ ratio }}</option>
              </select>
            </label>
            <label class="mini-field">
              <span>统一分辨率</span>
              <select
                :value="bulkTier"
                :disabled="!unionTiers.length"
                :title="unionTiers.length
                  ? '相对倍率；各流实际像素仍不同，不支持的流保持原值并单独提示'
                  : '所选工作流都没有可调分辨率'"
                @change="applyBulkTier(($event.target as HTMLSelectElement).value)"
              >
                <option value="">{{ unionTiers.length ? '未统一（各流各自记忆）' : '不可调分辨率' }}</option>
                <option v-for="tier in unionTiers" :key="tier" :value="tier">{{ tier }}</option>
              </select>
            </label>
            <span class="bulk-note">统一入口；个别流不支持时保持原值，并在下方单独提示。</span>
          </div>
          <p v-for="(line, i) in ratioSkips" :key="`r${i}`" class="skip-line">{{ line }}</p>
          <p v-for="(line, i) in tierSkips" :key="`t${i}`" class="skip-line">{{ line }}</p>
          <details v-if="pickedPaths.length" class="flow-tune">
            <summary>
              逐流微调 · {{ pickedPaths.length }} 个流<template v-if="diffCount">（{{ diffCount }} 个与统一值不同）</template>
            </summary>
            <div class="flow-params">
              <FlowParamsRow
                v-for="path in pickedPaths"
                :key="path"
                :path="path"
                :workflows="allWorkflows"
              />
            </div>
          </details>
          <p v-if="!pickedPaths.length" class="flow-empty">
            勾选工作流后，这里统一设置比例与分辨率。
          </p>
          <div class="control-row">
            <label class="mini-field">
              <span>尺寸对齐</span>
              <select
                :value="mixedRatio ? 'native' : matrix.align"
                :disabled="mixedRatio"
                :title="mixedRatio
                  ? '各流比例不同，已自动按各自原生档对齐；比例统一后可再选对齐方式'
                  : '各工作流档位机制不同，同一档出的尺寸并不一样'"
                @change="matrix.setAlign(($event.target as HTMLSelectElement).value as MatrixAlign)"
              >
                <option v-for="opt in alignOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </label>
            <div class="mini-field">
              <span>每个工作流张数</span>
              <span class="counts">
                <button
                  v-for="n in [1, 2, 3, 4]"
                  :key="n"
                  class="btn btn-sm count-btn"
                  :class="{ on: matrix.count === n }"
                  type="button"
                  @click="matrix.setCount(n)"
                >
                  {{ n }}
                </button>
              </span>
            </div>
            <label class="mini-field seed">
              <span>基准种子</span>
              <input v-model="seedInput" type="number" min="0" step="1" placeholder="空 = 随机" />
            </label>
            <button class="btn btn-sm" type="button" @click="randomSeed"><Icon name="dices" /> 随机</button>
            <label class="lock" title="锁定后各工作流同列用同一个种子，差异才归因于模型">
              <input v-model="matrix.lockSeed" type="checkbox" />
              同种子
            </label>
            <span class="grow" />
            <button
              class="btn btn-sm primary run"
              type="button"
              :class="{ loading: matrix.submitting }"
              :disabled="!canRun"
              @click="runTrial"
            >
              {{ matrix.submitting ? '提交中…' : `▶ 跑 ${matrix.plan.total} 张` }}
            </button>
          </div>
          <div class="plan">
            <span class="plan-count">{{ planSummary }}</span>
            <span v-for="(warn, i) in matrix.plan.warnings" :key="i" class="plan-warn" :class="warn.kind">
              {{ warn.text }}
            </span>
            <span v-if="runError" class="plan-warn warn">{{ runError }}</span>
          </div>
      </section>

      <div class="results scroll">
        <PromptMatrixStack
          :matrix="matrix"
          saveable
          @compare="openCompare($event)"
          @open-image="openImage($event)"
          @save="startSave($event)"
        />
      </div>
    </div>
  </Modal>

  <CompareModal :open="compareOpen" :items="compareItems" @close="compareOpen = false" />

  <Lightbox
    v-if="previewOpen"
    :items="previewItems"
    :index="0"
    :readonly="previewReadonly"
    :workflows="workflows"
    can-open-gallery
    @close="closePreview"
    @changed="queryClient.invalidateQueries({ queryKey: ['history'] })"
  />

  <PromptCreateModal
    :open="saveOpen"
    :initial="saveInitial"
    @close="saveOpen = false"
    @created="onCreated"
  />
</template>

<style scoped>
.head-sub {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: rgb(255 255 255);
}

.btn.primary:disabled {
  opacity: 0.45;
  cursor: default;
}

.more {
  position: relative;
}

.more > summary {
  display: flex;
  align-items: center;
  list-style: none;
  cursor: pointer;
}

.more > summary::-webkit-details-marker {
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
  width: max-content;
  max-width: min(320px, 80vw);
  padding: var(--gap-sm);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--panel);
  box-shadow: var(--shadow-2);
}

.more-note {
  margin: 0;
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-lg);
}

.radio {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  cursor: pointer;
}

.radio input {
  accent-color: var(--primary);
}

/* ---------- 双栏骨架 ---------- */

.trial-grid {
  display: grid;
  grid-template-columns: minmax(320px, 40%) minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr);
  grid-template-areas:
    "text controls"
    "text results";
  height: 100%;
  min-height: 0;
}

.pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.pane-text {
  grid-area: text;
  gap: var(--gap-sm);
  padding: var(--gap) var(--gap-lg);
  border-right: 1px solid var(--border);
  background: var(--panel-2);
}

.pane-head,
.neg-head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  flex: none;
}

.pane-title {
  font-size: var(--fs-sm);
  font-weight: 500;
}

.counter {
  color: var(--muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.grow {
  flex: 1 1 auto;
}

.big-text {
  flex: 1 1 auto;
  min-height: 200px;
  width: 100%;
  resize: none;
  padding: var(--gap-sm) var(--gap);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
  line-height: 1.7;
}

.big-text:focus {
  border-color: var(--primary);
  outline: none;
}

.neg {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.neg-input {
  width: 100%;
  resize: vertical;
  padding: 6px var(--gap-sm);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
}

.warn-text {
  color: var(--warn);
  font-size: var(--fs-xs);
}

/* ---------- 右侧常驻控制区 ---------- */

.controls {
  grid-area: controls;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  padding: var(--gap) var(--gap-lg);
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}

.control-row {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

/* 统一条件：一行批量设比例/分辨率，逐流微调收进折叠区 */
.bulk {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.bulk-note {
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-lg);
}

.skip-line {
  margin: 0;
  color: var(--warn);
  font-size: var(--fs-xs);
  line-height: var(--lh-lg);
}

.flow-tune > summary {
  width: fit-content;
  color: var(--muted);
  font-size: var(--fs-xs);
  cursor: pointer;
}

.flow-tune > summary:hover {
  color: var(--text);
}

.flow-tune[open] > summary {
  margin-bottom: var(--gap-xs);
}

/* 逐流参数：一行一个工作流，选择器宽度不够时自然折行 */
.flow-params {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  min-width: 0;
}

.flow-empty {
  margin: 0;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.mini-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.mini-field select,
.mini-field input {
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--panel-2);
  color: var(--text);
  font: inherit;
  font-size: var(--fs-sm);
}

.mini-field.seed input {
  width: 130px;
}

.counts {
  display: flex;
  gap: 3px;
}

.count-btn.on {
  border-color: var(--primary);
  color: var(--accent-link);
  background: var(--primary-soft);
}

.lock {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-xs);
  color: var(--muted);
  cursor: pointer;
}

.lock input {
  width: 14px;
  height: 14px;
  accent-color: var(--primary);
}

.run {
  min-width: 116px;
}

.plan {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--gap-xs) var(--gap-sm);
}

.plan-count {
  font-size: var(--fs-sm);
  font-weight: 500;
}

.plan-warn {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: var(--lh-lg);
}

.plan-warn.warn {
  border-color: var(--warn);
  color: var(--warn);
}

.plan-warn.ok {
  border-color: var(--success-border);
  color: var(--success-text);
}

.results {
  grid-area: results;
  min-height: 0;
  overflow-y: auto;
  background: var(--bg);
}

/* ---------- 滚动条跟随面板配色 ---------- */

.scroll {
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) var(--panel-2);
}

.scroll::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

.scroll::-webkit-scrollbar-track {
  background: var(--panel-2);
}

.scroll::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border: 2px solid var(--panel-2);
  border-radius: 999px;
}

.scroll::-webkit-scrollbar-thumb:hover {
  background: var(--muted);
}

@media (max-width: 900px) {
  .head-sub {
    display: none;
  }

  .trial-grid {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto auto;
    grid-template-areas:
      "text"
      "controls"
      "results";
    height: auto;
  }

  .pane-text {
    border-right: none;
    border-bottom: 1px solid var(--border);
  }

  .big-text {
    min-height: 180px;
  }

  .results {
    overflow: visible;
  }
}
</style>
