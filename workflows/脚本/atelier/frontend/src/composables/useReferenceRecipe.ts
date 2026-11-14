/**
 * 合成台批量提交与轮询（契约 C-REF-RECIPES@2 / C-JOB-PROGRESS@1）。
 *
 * 与阶段 3 最薄版的差异（本次升级）：
 * - 三槽改为**多选**：每槽 N 张，前端按
 *   「槽位组合 × 选中工作流 × 画质档 × 比例」做四维笛卡尔积，
 *   **每组独立 POST**（后端 `RecipeRequest` 的槽位仍是单值）；
 * - 工作流也改为**受控多选**（契约 C-REF-WF-SLOTS@1 / C-REF-TOTAL@2）：
 *   `slots` 声明工作流支持的业务角色，缺少当前已选槽位角色的项标为不可用并禁止勾选；
 * - 全组合上限 {@link MAX_BATCH_RECIPES}（100），超限时页面禁用提交；
 * - 提交并发上限 {@link MAX_SUBMIT_CONCURRENCY}（2），不一次打满后端；
 * - 种子按组派生：第 i 组 `seed = base_seed + i`、`seed_mode='fixed'`；
 * - 提交体透传 `workflow` / `quality` / `aspect_ratio` / `orientation` / `body_mode`，
 *   但 `caps.quality` / `caps.orientation` 为 false 时**绝不发送**对应字段；
 * - `body_mode='bare'`（素体展示）时绝不发送 `costume_id`（契约 C-REF-BODY-MODE@1）；
 * - 非空槽数 M < 所选工作流 input_count N 时，提交前弹出降级确认框
 *   （列出 `input_count <= M` 的候选），不做静默自动切换。
 *
 * 明确不迁（施工手册 §7 冻结）：配方草稿持久化、未决任务恢复追踪、
 * 通用参数面板、提示词只读预览。
 *
 * 持久化边界（2026-11-06 用户拍板）：**工作流多选只做会话级记忆** ——
 * 仅写 `sessionStorage['pb.reference_studio_workflows_session_v1']`
 * （值为 `{ workflows: string[] }`），同一会话内切页签 / 刷新 / 从库页返回
 * 都保留多选，关闭标签页后由浏览器自然清空。本文件**不**读写 localStorage /
 * IndexedDB，也不把多选塞进 `pb.reference_studio_v1`（那里 `workflow` 仍是
 * 首条单选语义）。
 */

import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'


import type { CostumeItem, PoseItem, PortraitItem } from '../api/reference'
import {
  NO_IMAGE_SLOT_HINT,
  RECIPE_SLOT_KEYS,
  compileActiveSlotTexts,
  compilePersonBTextFragments,
  describeAlternateModeConflicts,
} from './recipeTextFragments'
import type { RecipeSlotKey } from './recipeTextFragments'
import { uploadPathOf, useReferenceRecipeDraft } from './useReferenceRecipeDraft'
import { useReferenceSafeMode } from './useReferenceSafeMode'
import { awaitRecipeJobs } from './recipeJobStream'
import { useWorkflowCaps } from './useWorkflowCaps'
import type { WorkflowRow } from './useWorkflows'
import { parseStudioCaps, parseStudioParams } from './recipeApi'
import type {
  RecipeBatchGroup,
  RecipeBodyMode,
  RecipeJobSnapshot,
  RecipeProgress,
  RecipeSlotCounts,
  RecipeStyle,
  RecipeSubmitRequest,
  RecipeSubmitResponse,
  StudioFigureNumbers,
  StudioWorkflowOption,
  StudioWorkflowSlot,
  WorkflowDowngradePrompt,
} from './recipeModel'

import {
  STUDIO_WORKFLOWS_ENDPOINT,
  RECIPE_POLL_TIMEOUT_MS,
  DEFAULT_RECIPE_SEED,
  MAX_SUBMIT_CONCURRENCY,
  RECIPE_PREVIEW_DEBOUNCE_MS,
  RecipeSubmitError,
  buildRecipeRequest,
  costumeDimensionForBodyMode,
  countBatchTotal,
  exceedsBatchLimit,
  describeBatchLimit,
  buildBatchGroups,
  parseStudioExtraKind,
  parseFigureNumbers,
  resolveExtraKindConflict,
  parseWorkflowSlots,
  evaluateWorkflowApplicability,
  workflowInapplicableRole,
  describeWorkflowUnavailable,
  describePreviewWorkflowSkip,
  pruneInapplicableWorkflowSelection,
  readWorkflowSelectionSession,
  hasWorkflowSelectionSession,
  writeWorkflowSelectionSession,
  describeWorkflowSelectionRestoreNotice,
  reconcileQualitySelection,
  reconcileRatioSelection,
  describeWorkflowDowngrade,
  buildWorkflowDowngradeCandidates,
  runWithConcurrency,
  isJobSucceeded,
  recipeJobResultUrls,
  resolveInitialWorkflowPath,
  describeJobFailure,
  describeSubmitFailure,
  describePreviewFailure,
  describePollFailure,
  describeMissingResult,
} from './recipeModel'
import {
  submitRecipe,
  previewRecipePrompt,
  checkRecipeTrim,
  pollRecipeJob,
} from './recipeApi'
export * from './recipeModel'
export * from './recipeApi'

// Composable
// ---------------------------------------------------------------------------

/** 提交状态机（“最近一批”兼容视图用）。 */
export type RecipeRunStatus = 'idle' | 'submitting' | 'polling' | 'success' | 'failed'

/** 单个批次的独立状态；每次 `submit()` 产生一批，各批互不覆盖。 */
export type RecipeBatchStatus = 'submitting' | 'polling' | 'success' | 'failed'

/**
 * 一次提交对应的独立批次。
 *
 * - `groups` 是本批全部组合（含后来提交失败的组）；
 * - `jobIds` / `results` 只属于本批，绝不与其他批合并；
 * - `total` / `done` 是**本批**任务快照的汇总（轮询进度）；
 * - `submitted` / `failed` 是组数口径（提交进度 / 失败组数）。
 */
/**
 * 单组结果：结果图与配方组的对应关系（P2 M5）。
 *
 * `groups` 是提交时的完整组合清单，这一层只补「哪张图来自哪一组」；
 * 失败组同样保留一行，`urls` 为空、`error` 写明原因，网格里可以显示灰块。
 */
export interface RecipeGroupResult {
  group: RecipeBatchGroup
  /** 提交成功时的 job id；提交失败为 0。 */
  jobId: number
  /** 该组产出的结果图（可能多张）；失败组为空。 */
  urls: string[]
  /** 失败原因；成功为空串。 */
  error: string
}

export interface RecipeBatch {
  id: string
  createdAt: number
  groups: RecipeBatchGroup[]
  jobIds: number[]
  status: RecipeBatchStatus
  /** 轮询口径的图片总数（后端各 job total 之和；提交阶段为组数）。 */
  total: number
  /** 轮询口径的已完成数。 */
  done: number
  /** 已成功提交的组数（提交阶段进度用）。 */
  submitted: number
  /** 失败组数（提交失败 + 任务失败 + 轮询失败）。 */
  failed: number
  results: string[]
  /**
   * 逐组结果（P2 M5）：组 → job → urls。
   * `results` 仍是扁平数组，保持既有 UI 与测试兼容。
   */
  groupResults: RecipeGroupResult[]
  errorMessage: string
  /** 提交阶段结束（全部组已 POST）的时间；未结束为 null。 */
  submittedAt: number | null
  /** 批次进入终态的时间；未结束为 null。 */
  finishedAt: number | null
  /**
   * 新 B 组（UX 壳阶段）在提交瞬间的预览摘要。
   *
   * 只在 `personBEnabled` 时写入；明确标注「待接入」，避免被误认为已真实提交。
   */
  personBPreview?: string
}

/** 单组提交结果（内部聚合用）。 */
interface SubmitOutcome {
  group: RecipeBatchGroup
  response: RecipeSubmitResponse | null
  error: unknown
}

/** 单组轮询结果（内部聚合用）。 */
interface PollOutcome {
  outcome: SubmitOutcome & { response: RecipeSubmitResponse }
  snapshot: RecipeJobSnapshot | null
  error: unknown
}

/**
 * `groupResults` 的稳定键（P2 M5）。
 *
 * 不能用 group 对象本身：批次是 reactive，`batch.groups` 里的元素会被 Proxy 包装，
 * 与轮询回传的原始 group 引用不相等，对象键会全部查不到。
 */
export function groupResultKeyOf(group: RecipeBatchGroup): number {
  return group.index
}

/** 批次是否仍在运行（提交中或轮询中）。 */
export function isRecipeBatchRunning(batch: RecipeBatch): boolean {
  return batch.status === 'submitting' || batch.status === 'polling'
}

/** 批次进度百分比：提交阶段按组数、轮询阶段按图片数；无法计算时返回 null。 */
export function recipeBatchPercent(batch: RecipeBatch): number | null {
  if (batch.status === 'submitting') {
    if (batch.groups.length <= 0) return 0
    return Math.min(
      100,
      Math.max(0, Math.round((batch.submitted / batch.groups.length) * 100)),
    )
  }
  if (batch.total <= 0) return batch.status === 'success' ? 100 : null
  return Math.min(100, Math.max(0, Math.round((batch.done / batch.total) * 100)))
}

/**
 * 批次状态文案（页面头部展示）。
 *
 * 语义顺序：提交中 → 排队中 → 出图中 N/M → 已完成 / 部分失败 / 失败。
 */
export function describeRecipeBatchStatus(batch: RecipeBatch): string {
  switch (batch.status) {
    case 'submitting':
      return `提交中（${batch.submitted}/${batch.groups.length} 组）`
    case 'polling':
      if (batch.total <= 0) return '排队中'
      return batch.done <= 0 ? '排队中' : `出图中 ${batch.done}/${batch.total}`
    case 'success':
      return `已完成（${batch.results.length} 张）`
    case 'failed':
      return batch.results.length
        ? `部分失败（成功 ${batch.results.length} 张）`
        : '失败'
  }
}

/** 批次进度 → 兼容视图用的 {@link RecipeProgress}。 */
function describeBatchProgressView(batch: RecipeBatch): RecipeProgress {
  if (batch.status === 'submitting') {
    return {
      stage: 'submit',
      message: `正在提交 ${batch.submitted}/${batch.groups.length} 组…`,
      percent: recipeBatchPercent(batch),
    }
  }
  if (batch.status === 'polling') {
    const percent = recipeBatchPercent(batch)
    if (batch.done <= 0) {
      return {
        stage: 'queued',
        message: `已提交 ${batch.jobIds.length} 个任务，正在排队…`,
        percent,
      }
    }
    return {
      stage: 'running',
      message: `正在出图…（已完成 ${batch.done}/${batch.total}）`,
      percent,
    }
  }
  if (batch.status === 'success') {
    return { stage: 'done', message: `已完成 ${batch.results.length} 张`, percent: 100 }
  }
  return {
    stage: 'done',
    message: batch.results.length
      ? `部分任务失败（成功 ${batch.results.length} 张）`
      : '生成失败',
    percent: percentOfCompleted(batch),
  }
}

/** 失败批次在兼容视图里的百分比：有 total 就用 done/total，否则沿用已有值。 */
function percentOfCompleted(batch: RecipeBatch): number | null {
  if (batch.total <= 0) return null
  return Math.min(100, Math.max(0, Math.round((batch.done / batch.total) * 100)))
}

/**
 * 合成台批量提交与进度状态。
 *
 * 所有状态都是组件级内存态：切页签会重置（草稿与未决任务恢复按 §7 不迁），
 * 三槽选择本身来自 `useReferenceRecipeDraft` 单例，不受影响。
 */
export function useReferenceRecipe() {
  const draft = useReferenceRecipeDraft()
  /**
   * 18+ 安全模式（模块级单例，与参考库各页签共用同一份）。
   *
   * 2026-11-08：安全模式关闭 = 18+ 已解锁 → 预览与提交都下发 `adult_mode: true`，
   * 后端据此去掉素体/双人条款里的非性化抑制句；安全模式下保持后端默认口径。
   * 预览与提交必须同口径，否则用户看到的提示词与实际提交的不一致。
   */
  const { safeMode } = useReferenceSafeMode()

  const workflows = ref<StudioWorkflowOption[]>([])
  const workflowDefault = ref('')
  /**
   * 已选工作流（有序、去重；契约 C-REF-WF-SLOTS@1 的 `workflows: string[]`）。
   *
   * 空数组表示「使用后端默认工作流」：计数按 1 条默认项，UI 另有明示。
   *
   * 初始化从 **sessionStorage** 恢复：同一会话内切页签（SPA）、刷新、从库页
   * 返回合成台都保留多选；关闭标签页后浏览器自然清空。恢复出来的路径随后
   * 必须再走目录存在性 + `slots` 三态校验（见 `loadStudioWorkflows` 与
   * `filledSlotRoles` 的 watch）。
   */
  const restoredSessionWorkflows = readWorkflowSelectionSession()
  /** 会话里是否有有效记忆（含 `{ workflows: [] }` 的主动清空）。 */
  const hasSessionWorkflowRestore = hasWorkflowSelectionSession()
  const workflowSelection = ref<string[]>(
    hasSessionWorkflowRestore ? restoredSessionWorkflows : [],
  )
  const workflowsLoading = ref(false)
  const workflowsError = ref('')
  /**
   * 会话恢复尚未完成：期间忽略 `pb.reference_studio_v1.workflow` 的单选回填，
   * 否则页面用「上次的代表工作流」会把刚恢复的多选（含空选择）压成单条。
   */
  let pendingSessionWorkflowRestore = hasSessionWorkflowRestore
  /** 恢复校验尚未给出提示：用于把「恢复」文案与用户操作导致的取消文案区分开。 */
  let sessionRestoreNoticePending = restoredSessionWorkflows.length > 0

  /** 工作流多选变化即写会话记忆（去重、保序）；只碰 sessionStorage。 */
  watch(
    workflowSelection,
    (selection) => writeWorkflowSelectionSession(selection),
    { deep: true, flush: 'sync' },
  )

  /**
   * 第 4 槽语义互斥（v2-A 收尾）。
   *
   * `person_b` 与 `hair` 共用第 4 槽但按各自语义编译提示词，混选会让其中一条
   * 错配。选择层只保留**最新勾选**的一条并沿用既有提示通道（页面转 toast），
   * 不改后端、不按工作流分组提交。
   *
   * `sync` 保证页面直接 `workflowSelection = $event` 时也立即收敛；
   * 目录未加载 / 只有一种语义时函数返回 null，不做任何改动。
   */
  watch(
    [workflowSelection, workflows],
    () => {
      const resolution = resolveExtraKindConflict(workflowSelection.value, workflows.value)
      if (!resolution.kind) return
      workflowSelection.value = resolution.kept
      const label = resolution.kind === 'person_b' ? '人物B身份参考' : '发型'
      workflowSelectionNotice.value =
        `已自动取消 ${resolution.removed.length} 个工作流。` +
        '原因：第 4 槽不能同时用作「人物B身份参考」与「发型参考」，' +
        `只保留最新选择的「${label}」。` +
        '下一步：若要改用另一种语义，请先取消当前工作流再重新勾选。'
    },
    { flush: 'sync' },
  )

  /** 默认工作流路径：后端 `default` 在列表内时用它，否则回落首条；空列表为 ''。 */
  const workflowDefaultPath = computed(() =>
    resolveInitialWorkflowPath(workflows.value, workflowDefault.value),
  )

  /**
   * 代表工作流（首条；空选择时为默认项）。
   *
   * caps / 尺寸档位 / 持久化仍按首条工作流计算；写入时视为单选替换，
   * 这样 `pb.reference_studio_v1.workflow` 的既有语义不变。
   */
  const workflowPath = computed<string>({
    get: () => workflowSelection.value[0] ?? workflowDefaultPath.value,
    set: (value: string) => {
      // 会话多选恢复期间忽略单选回填：页面会在 setup 阶段用 localStorage 的
      // `pb.reference_studio_v1.workflow`（首条）做恢复，不能让它覆盖会话多选。
      if (pendingSessionWorkflowRestore) return
      workflowSelection.value = value ? [value] : []
    },
  })

  /** 已选工作流对应的目录项（保序、过滤目录中已消失的路径）。 */
  const selectedWorkflows = computed<StudioWorkflowOption[]>(() =>
    workflowSelection.value
      .map((path) => workflows.value.find((item) => item.path === path))
      .filter((item): item is StudioWorkflowOption => Boolean(item)),
  )

  /**
   * 实际参与笛卡尔积的工作流。
   *
   * 未勾选时回落后端默认项（1 条），保证「空选择 = 1 条默认工作流」的计数口径。
   */
  const effectiveWorkflows = computed<StudioWorkflowOption[]>(() => {
    if (selectedWorkflows.value.length) return selectedWorkflows.value
    const fallback = workflows.value.find((item) => item.path === workflowDefaultPath.value)
    return fallback ? [fallback] : []
  })

  /** 是否正在使用后端默认工作流（UI 需要明示）。 */
  const usesDefaultWorkflow = computed(
    () => selectedWorkflows.value.length === 0 && effectiveWorkflows.value.length > 0,
  )

  /** 工作流维度：至少按 1 计，不能把 total 乘成 0。 */
  const workflowDimension = computed(() => Math.max(1, effectiveWorkflows.value.length))

  const style = ref<RecipeStyle>('realistic')
  const promptSuffix = ref('')

  /**
   * 第 4 槽（2026-11-07）：真源已上提到 `useReferenceRecipeDraft`，
   * 这里只做只读投影，保证「库页签 → 合成台 → 刷新」共用同一份草稿。
   */
  const extra = draft.extra
  const extraPath = computed(() => extra.value.path)
  const extraId = computed(() => extra.value.id)
  const extraLibrary = computed(() => extra.value.library)
  const extraName = computed(() => extra.value.name)
  const extraText = computed(() => extra.value.text)
  /** 第 4 槽是否已填（上传路径或发型库条目二选一）。 */
  const extraFilled = draft.extraFilled

  /** V2-C 第 5 槽（人物B服装）：只读投影，与草稿单例共用同一份来源。 */
  const extraCostume = draft.extraCostume
  const extraCostumeFilled = draft.extraCostumeFilled
  const extraCostumePath = computed(() => extraCostume.value.path)
  const extraCostumeId = computed(() => extraCostume.value.id)
  const extraCostumeLibrary = computed(() => extraCostume.value.library)

  /**
   * P1：新 B 组是否进入本轮提交。
   *
   * 同时要求「已新增 B」「当前是双人姿势」「至少选了一个五图人物B工作流」。
   * 单人姿势下 B 图像参考会污染人物A，所以即使 B 组有素材也绝不提交。
   */
  const personBGroupActive = computed(
    () =>
      draft.personBEnabled.value &&
      draft.hasPairPose.value &&
      effectiveWorkflows.value.some((item) => item.extraKind === 'person_b'),
  )

  /** 新 B 组逐组配对素材：只有 image 模式的槽才带图。 */
  const personBGroupInput = computed(() => {
    if (!personBGroupActive.value) return undefined
    return {
      portraits:
        draft.personBSlotModes.value.portrait === 'image'
          ? draft.personBPortrait.value
          : [],
      costumes:
        draft.personBSlotModes.value.costume === 'image'
          ? draft.personBCostume.value
          : [],
    }
  })

  /** P1：B 组人像数（计数用）；未生效时为 0，回落到旧变体口径。 */
  const personBGroupPortraitCount = computed(() =>
    personBGroupActive.value ? (personBGroupInput.value?.portraits.length ?? 0) : 0,
  )

  /**
   * P1：A/B 人像数量不齐时的配对提示。
   *
   * 不阻断提交：按较少侧收敛，多出的素材本轮不参与；两侧都按 image 模式计。
   */
  const personBPairNotice = computed(() => {
    if (!personBGroupActive.value) return ''
    const a = draft.slotModes.value.portrait === 'image' ? slotCounts.value.portrait : 0
    const b = personBGroupPortraitCount.value
    if (!a || !b || a === b) return ''
    return `A 人像 ${a} 张 / B 人像 ${b} 张，按较少侧 ${Math.min(a, b)} 组配对，多出的素材本轮不参与。`
  })

  /**
   * P1：B 的文本字段（只在双人姿势下发送）。
   *
   * - 人像/服饰：text 模式恒发送；image 模式只在补充开关打开时发送（图为主）；
   * - 姿态：P1 没有 B 独立姿势图位，非空即发送；
   * - 修饰层：非空即发送，后端包成独立的人物B条款。
   */
  function personBTextFields(): {
    personBPortraitText: string
    personBCostumeText: string
    personBPoseText: string
    personBModifierFragments: string
  } {
    const empty = {
      personBPortraitText: '',
      personBCostumeText: '',
      personBPoseText: '',
      personBModifierFragments: '',
    }
    if (!draft.hasPairPose.value) return empty
    const compiled = compilePersonBTextFragments(draft.personBTextFragments.value)
    const modes = draft.personBSlotModes.value
    const supplements = draft.personBSupplementFlags.value
    const active = (slot: RecipeSlotKey): boolean =>
      modes[slot] === 'text' || (modes[slot] === 'image' && supplements[slot])
    return {
      personBPortraitText: active('portrait') ? compiled.portraitText : '',
      personBCostumeText: active('costume') ? compiled.costumeText : '',
      personBPoseText: compiled.poseText,
      personBModifierFragments: compiled.modifierFragments,
    }
  }

  /** 尺寸档位 / 比例均为多选；空数组表示本轮不发对应参数。 */
  const qualitySelection = ref<string[]>([])
  const ratioSelection = ref<string[]>([])
  /** 基础种子；第 i 组 = baseSeed + i。 */
  const baseSeed = ref<number>(DEFAULT_RECIPE_SEED)

  /** 非空时页面渲染降级确认框；用户确认切换后才继续提交。 */
  const workflowDowngrade = ref<WorkflowDowngradePrompt | null>(null)
  /** 工作流因槽位变化被自动取消时的提示文案（页面转成 toast，绝不静默移除）。 */
  const workflowSelectionNotice = ref('')
  /** 空槽被自动裁剪后提交时的提示文案（页面转成 toast；已提交，不需要用户确认）。 */
  const workflowTrimNotice = ref('')

  // 工作流能力：复用主站唯一实现，避免合成台再写一份档位规则。
  const studioRows = computed<WorkflowRow[]>(() =>
    workflows.value.map((item) => ({
      path: item.path,
      name: item.name,
      caps: item.caps,
      params: item.params,
    })),
  )
  const { caps, qualityOptions, aspectRatios, defaultRatio } = useWorkflowCaps(
    workflowPath,
    studioRows,
    /**
     * 档位文案（2.0× · 6.3MP · 1648×3824）只按第一个比例算，**只影响标注**。
     *
     * 合成台的比例是多选，每个「比例 × 档位」各展开一组任务；多选时页面不显示
     * 像素（见 StudioParamsCard），所以这里给第一个比例就够，提交体仍按全部比例展开。
     */
    computed(() => ratioSelection.value[0] ?? ''),
  )

  /** 当前代表工作流（首条）：caps / 预览 / 降级判定都用它。 */
  const currentWorkflow = computed<StudioWorkflowOption | null>(
    () => effectiveWorkflows.value[0] ?? null,
  )
  /**
   * 提交前输入数预判：取所有生效工作流里的最大 input_count。
   *
   * 多选时逐组提交，任何一组输入数不足都会 400；用最大值判定能提前拦住。
   */
  const workflowInputCount = computed(() =>
    effectiveWorkflows.value.reduce(
      (max, item) => Math.max(max, item.inputCount || 0),
      0,
    ),
  )

  /** 体态模式（素体开关）；不写 localStorage（本轮契约不要求记忆）。 */
  const bodyMode = ref<RecipeBodyMode>('costume')
  /**
   * 当前生效工作流里是否有能接第 4 张（`extra`）的。
   *
   * 没有时页面直接隐藏上传入口（`extra` 槽一并清空）：合成台现有工作流都只有 3 个
   * LoadImage，上传第 4 张只会让所有工作流因 `slots` 不含 extra 被判「不适用」，
   * 用户看到的是一排置灰项。`slots` 缺失（旧后端）按「支持」处理，避免误伤。
   */
  const supportsExtraSlot = computed(() =>
    effectiveWorkflows.value.some((item) =>
      item.slots === undefined ? true : item.slots.includes('extra'),
    ),
  )
  /**
   * 当前生效工作流里是否有能接第 5 槽（`extra_costume`）的。
   *
   * 旧后端 `slots` 缺失时返回 false：第 5 槽是 V2-C 新契约，不猜测支持，
   * 避免页面显示一个提交后必 400 的入口。
   */
  const supportsExtraCostumeSlot = computed(() =>
    effectiveWorkflows.value.some((item) =>
      item.slots === undefined ? false : item.slots.includes('extra_costume'),
    ),
  )
  /** 缺服装自动切换素体展示时的提示文案（页面转成 toast，不拦提交）。 */
  const bodyModeNotice = ref('')
  /**
   * 实际生效的体态模式：`costume` 但服装槽为空 → 按 `bare`（中性素体展示）。
   *
   * 后端 `create_reference_recipe` 用同一条规则兜底（2026-11-06 实测：缺服装且不声明
   * 素体时，Qwen 系会自由发挥出裸体）。组合裁剪、预览与提交体都用这个生效值，
   * 保证「预览给出的提示词 = 真正提交的提示词」。
   *
   * P2：服装槽用文本替代时**不能**判素体（否则后端写「不穿任何服装」），
   * 所以 text 模式直接返回 costume（方案 C3-1 的前端对齐）。
   */
  const effectiveBodyMode = computed<RecipeBodyMode>(() => {
    if (draft.slotModes.value.costume === 'text') return 'costume'
    return bodyMode.value === 'bare' || draft.costumeCount.value === 0 ? 'bare' : 'costume'
  })

  /**
   * 素体展示时服装一律不计入提交（2026-11-08）。
   *
   * 素体开关不再销毁服装选择（关闭素体后可直接恢复），所以「有选择」≠「要提交」：
   * 批量组合数、非空槽数、适用性判定都必须按 0 计，否则会虚高并让后端判定冲突。
   */
  const costumeSubmittable = computed(() => effectiveBodyMode.value !== 'bare')

  const slotCounts = computed<RecipeSlotCounts>(() => ({
    portrait: draft.portraitCount.value,
    costume: costumeSubmittable.value ? draft.costumeCount.value : 0,
    pose: draft.poseCount.value,
  }))

  /** 某槽本次提交是否真的带图（text / empty 模式即使有残留条目也不算）。 */
  function slotHasImage(slot: RecipeSlotKey): boolean {
    if (draft.slotModes.value[slot] !== 'image') return false
    // 素体展示的服装槽：选择会保留，但本次不提交（对应 slotCounts 已归零）。
    if (slot === 'costume' && !costumeSubmittable.value) return false
    return slotCounts.value[slot] > 0
  }

  /** 非空槽位名（含第 4 张）：后端按「非空槽数 M」校验工作流输入数。 */
  const filledSlotNames = computed<string[]>(() => {
    const names: string[] = []
    if (slotHasImage('portrait')) names.push('人像')
    if (slotHasImage('costume')) names.push('服装')
    if (slotHasImage('pose')) names.push('姿势')
    // P1：新 B 组生效时，B 人像/服装按逐组输入计入；否则沿用第 4/5 槽。
    const bPortrait = personBGroupPortraitCount.value > 0
    // 素体展示不提交服装：B 服装选择保留但本次不算槽位。
    const bCostume =
      costumeSubmittable.value &&
      (personBGroupInput.value?.costumes.length ?? 0) > 0
    if (personBGroupActive.value ? bPortrait : extraFilled.value) names.push('第 4 张')
    if (
      personBGroupActive.value
        ? bCostume
        : costumeSubmittable.value && extraCostumeFilled.value
    ) {
      names.push('人物B服装')
    }
    return names
  })
  const activeSlotCount = computed(() => filledSlotNames.value.length)

  /** 非空槽位的**业务角色**（工作流 `slots` 适用性判定用；空槽不参与）。 */
  const filledSlotRoles = computed<StudioWorkflowSlot[]>(() => {
    const roles: StudioWorkflowSlot[] = []
    if (slotHasImage('portrait')) roles.push('portrait')
    if (slotHasImage('costume')) roles.push('costume')
    if (slotHasImage('pose')) roles.push('pose')
    // P1：新 B 组走逐组输入，角色判定与第 4/5 槽同构；未生效时保持旧口径。
    const bPortrait = personBGroupPortraitCount.value > 0
    // 素体展示不提交服装：B 服装选择保留但本次不算槽位（2026-11-08）。
    const bCostume =
      costumeSubmittable.value &&
      (personBGroupInput.value?.costumes.length ?? 0) > 0
    if (personBGroupActive.value ? bPortrait : extraFilled.value) roles.push('extra')
    if (
      personBGroupActive.value
        ? bCostume
        : costumeSubmittable.value && extraCostumeFilled.value
    ) {
      roles.push('extra_costume')
    }
    return roles
  })

  /** 尺寸维度：caps 不支持时折叠为 1（页面也会隐藏控件）。 */
  const qualityDimension = computed(() =>
    caps.value.quality ? qualitySelection.value.length : 0,
  )
  const ratioDimension = computed(() =>
    caps.value.orientation ? ratioSelection.value.length : 0,
  )

  /**
   * 组合计数用的槽位数：双人配对模式下每槽最多按 1 张计。
   *
   * 选择层已收敛；这里再兜底一次，保证完全展开前（例如旧草稿恢复）
   * 「当前 N / 上限 100」不会按多选虚高。
   */
  const batchSlotCounts = computed<RecipeSlotCounts>(() =>
    draft.pairModeActive.value
      ? {
          portrait: Math.min(1, slotCounts.value.portrait),
          costume: Math.min(1, slotCounts.value.costume),
          pose: Math.min(1, slotCounts.value.pose),
        }
      : slotCounts.value,
  )

  /** 组合计数用的 B 变体数：配对模式下只算 1 组；新 B 组生效时不走旧变体。 */
  const batchPersonBVariantCount = computed(() => {
    if (!draft.hasPairPose.value) return 0
    if (personBGroupActive.value) return 0
    return draft.pairModeActive.value ? 1 : draft.personBVariants.value.length
  })

  /**
   * 全组合数（契约 C-REF-TOTAL@2）：
   * `槽位组合数 × 选中工作流数 × 画质档数 × 比例数`。
   *
   * 常驻展示「当前 N / 上限 100」，提交前也用它做上限判断。
   */
  const batchTotal = computed(() =>
    countBatchTotal(
      batchSlotCounts.value,
      qualityDimension.value,
      ratioDimension.value,
      workflowDimension.value,
      draft.slotModes.value,
      batchPersonBVariantCount.value,
      // P1：新 B 组按较短侧配对，计数与清单同口径。
      personBGroupPortraitCount.value,
    ),
  )
  const batchOverLimit = computed(() => exceedsBatchLimit(batchTotal.value))
  const batchLimitMessage = computed(() =>
    batchOverLimit.value ? describeBatchLimit(batchTotal.value) : '',
  )

  /** 尺寸和比例都不可选（编辑类模型全程跟随参考图）。Qwen21 现在有像素档，只剩比例跟随。 */
  const followsReferenceSize = computed(
    () => !caps.value.quality && !caps.value.orientation,
  )

  const status = ref<RecipeRunStatus>('idle')
  const progress = ref<RecipeProgress>({
    stage: 'submit',
    message: '',
    percent: null,
  })
  const jobId = ref<number | null>(null)
  const jobIds = ref<number[]>([])
  const resultUrls = ref<string[]>([])
  const previousResultUrl = ref('')
  const errorMessage = ref('')

  // -------------------------------------------------------------------------
  // 多批次真源（每次 submit 一批，各批独立轮询、互不覆盖）
  // -------------------------------------------------------------------------

  /** 批次列表（创建顺序）；页面按批分组展示结果。 */
  const batches = ref<RecipeBatch[]>([])
  /** 批次 id 序号（仅内存，不持久化）。 */
  let batchSequence = 0
  /** 提交前校验错误（尚未创建批次）；与批次内错误分开，避免误挂到上一批。 */
  const formError = ref('')

  /** 是否**有任意批次处于提交阶段**（submit 只拦这类重复点击）。 */
  const submitting = computed(() =>
    batches.value.some((batch) => batch.status === 'submitting'),
  )
  /** 是否**有任意批次处于轮询阶段**（不阻止再次提交）。 */
  const polling = computed(() =>
    batches.value.some((batch) => batch.status === 'polling'),
  )
  /** 整体忙碌语义（仅用于“停止 / 生成中”类提示，不参与 canSubmit）。 */
  const busy = computed(() => submitting.value || polling.value)

  /** 最近创建的批次（兼容视图 / 状态文案都看它）。 */
  function latestBatch(): RecipeBatch | null {
    return batches.value[batches.value.length - 1] ?? null
  }

  /**
   * 把批次状态同步到“最近一批”兼容视图。
   *
   * 只有**最新批次**可以写单值视图：旧批次完成时绝不能覆盖用户刚提交的新批次，
   * 否则进度 / 结果 / 错误会串批。
   */
  function syncLatestView(batch: RecipeBatch): void {
    if (latestBatch()?.id !== batch.id) return
    status.value = batch.status
    progress.value = describeBatchProgressView(batch)
    jobIds.value = [...batch.jobIds]
    jobId.value = batch.jobIds[0] ?? null
    resultUrls.value = [...batch.results]
    errorMessage.value = batch.errorMessage
  }

  const progressPercent = computed<number | null>(() => {
    const value = progress.value.percent
    if (typeof value !== 'number' || !Number.isFinite(value)) return null
    return Math.min(100, Math.max(0, Math.round(value)))
  })
  const primaryResultUrl = computed(() => resultUrls.value[0] ?? '')
  const selectedCount = computed(() => draft.totalSelected.value)
  /**
   * 可否提交：只拦「正在提交中」的重复点击。
   *
   * 轮询期间 `polling === true` **不再**禁用按钮——ComfyUI 支持随时入队，
   * 新任务会进入 `queue_pending` 并 GPU 串行执行。
   */
  const canSubmit = computed(
    () =>
      !submitting.value &&
      !workflowsLoading.value &&
      effectiveWorkflows.value.length > 0 &&
      // P2：text 模式槽也会产生组合（batchTotal > 0），不要求必须有图片槽；
      // 「至少 1 张图 / 文本碎片为空」由 submit() 统一拦截并给出文案。
      batchTotal.value > 0 &&
      !batchOverLimit.value,
  )

  // -------------------------------------------------------------------------
  // 提示词 dry-run 预览（只读，不产生任务）
  // -------------------------------------------------------------------------

  /** 后端组合出的提示词；空串表示尚未拿到有效预览。 */
  const previewPrompt = ref('')
  /**
   * P3 手动改写（方案 §14）。
   *
   * - `null`：自动模式，提示词由碎片 + 后端编译生成；
   * - 字符串：用户手动改写后的最终原文，提交时作为 `prompt_override` 发送，
   *   后端据此跳过二次编译（`skip_compile` 由后端推断，前端不传）。
   */
  const promptOverride = ref<string | null>(null)

  /** 设置手动改写原文；空白字符串按「未改写」处理（回到自动模式）。 */
  function setPromptOverride(value: string | null): void {
    const text = typeof value === 'string' ? value : ''
    promptOverride.value = text.trim() ? value : null
  }
  /**
   * 编译后的最终负向（dry-run 返回）。
   *
   * §11.3：预览必须显示「最终正向 + 最终负向」，否则用户看到的不是实际提交内容。
   * 空串表示后端明确返回空负向，或尚未拿到有效预览。
   */
  const previewNegativePrompt = ref('')
  /**
   * 当前工作流负向是否生效。
   *
   * `false`（后端明确判定不生效）时实际提交为空，页面要如实说明；
   * `null` 表示后端未给出该字段（旧后端），前端不臆测生效与否。
   */
  const previewNegativeEffective = ref<boolean | null>(null)
  const previewError = ref('')
  const previewLoading = ref(false)

  /** 清空「最终负向」两条状态；必须与正向预览同时清，避免旧值留在界面上。 */
  function clearPreviewNegative(): void {
    previewNegativePrompt.value = ''
    previewNegativeEffective.value = null
  }

  /** 防抖定时器与请求序号：新请求会丢弃旧响应，避免快速切换槽位时串轮。 */
  let previewTimer: ReturnType<typeof setTimeout> | null = null
  let previewRequestSeq = 0

  /**
   * 预览用请求：三槽各取**第一张**作为代表组合。
   *
   * 批量提交时每组提示词只在槽位条目名上不同，取首张即可反映组合结构与画风；
   * 第 4 张按需求不参与预览。工作流取**第一条**（多选时预览卡会注明），
   * 素体模式随 `body_mode` 一起下发，保证预览与提交口径一致。
   */
  function buildPreviewRequest(): RecipeSubmitRequest {
    // P1：新 B 组生效时，预览用 B 组首张素材与八类文本；否则沿用旧第 4/5 槽与变体。
    const bGroup = personBGroupActive.value ? personBGroupInput.value : undefined
    const firstBPortrait = bGroup?.portraits[0] ?? null
    const firstBCostume = bGroup?.costumes[0] ?? null
    const firstBPortraitUpload = uploadPathOf(firstBPortrait)
    const firstBCostumeUpload = uploadPathOf(firstBCostume)
    const bText = personBTextFields()
    return buildRecipeRequest(
      {
        portrait: draft.portrait.value[0] ?? null,
        costume:
          effectiveBodyMode.value === 'bare' ? null : (draft.costume.value[0] ?? null),
        pose: draft.pose.value[0]?.item ?? null,
      },
      {
        style: style.value,
        promptSuffix: promptSuffix.value,
        // 预览与提交共用同一份第 4 槽（图片 + 文字），避免「预览看不到、提交却生效」。
        extraPath: bGroup ? (firstBPortraitUpload ?? '') : extraPath.value,
        extraId:
          bGroup && !firstBPortraitUpload ? (firstBPortrait?.id ?? '') : bGroup ? '' : extraId.value,
        extraLibrary: bGroup
          ? firstBPortrait ? 'portrait' : ''
          : extraLibrary.value,
        extraText: bGroup ? '' : extraText.value,
        // V2-C：第 5 槽（人物B服装）同样整批共享，预览与提交共用。
        extraCostumePath: bGroup
          ? (firstBCostumeUpload ?? '')
          : extraCostumePath.value,
        extraCostumeId:
          bGroup && !firstBCostumeUpload ? (firstBCostume?.id ?? '') : bGroup ? '' : extraCostumeId.value,
        extraCostumeLibrary: bGroup
          ? (firstBCostume?.library ?? '')
          : extraCostumeLibrary.value,
        // v1.5：旧路径用当前激活的 B 变体；P1 新 B 组改走下方独立字段。
        personBVariant:
          !personBGroupActive.value && draft.hasPairPose.value
            ? draft.activePersonBVariant.value
            : null,
        personBText:
          !personBGroupActive.value && draft.hasPairPose.value ? draft.personBText.value : '',
        personBPortraitText: bGroup ? bText.personBPortraitText : '',
        personBCostumeText: bGroup ? bText.personBCostumeText : '',
        personBPoseText: bGroup ? bText.personBPoseText : '',
        personBModifierFragments: bGroup ? bText.personBModifierFragments : '',
        workflow: previewWorkflow.value?.path ?? '',
        bodyMode: effectiveBodyMode.value,
        // 成人向（2026-11-08）：与提交同口径——18+ 解锁才下发，预览据此去掉抑制句。
        adultMode: !safeMode.value,
        seed: baseSeed.value,
        seedMode: 'fixed',
        textFragments: draft.textFragments.value,
        // P2：预览与提交使用同一份槽位模式（text 槽不带图，只带文本）。
        slotModes: draft.slotModes.value,
        // P4：image 模式 + 文本只有显式开关才作为补充发送。
        supplementFlags: draft.supplementFlags.value,
        negativePrompt: draft.negativePrompt.value,
        // P3：手动模式下 dry-run 也按原文请求（与正式提交同一构造器）。
        promptOverride: promptOverride.value ?? '',
      },
    )
  }

  /** 预览代表工作流：永远取第一条生效工作流。 */
  const previewWorkflow = computed<StudioWorkflowOption | null>(
    () => effectiveWorkflows.value[0] ?? null,
  )

  /**
   * 角色 → 图号（提示词里的「图N」），用于槽位卡与预览段落的图号徽标。
   *
   * 取预览工作流（= 实际会提交的那份）的 `figure_numbers`：空槽也保留图号，
   * 因此「图3 空着」这件事本身是可见的，而不是让用户猜为什么跳到图4。
   */
  const figureNumbers = computed<StudioFigureNumbers>(
    () => previewWorkflow.value?.figureNumbers ?? {},
  )

  /**
   * 预览前置校验：第一条工作流对当前已选槽位不适用时返回三句式文案。
   *
   * 命中后**不发送** dry-run 请求，避免用户再看到后端 400。
   */
  const previewWorkflowSkipReason = computed(() => {
    const workflow = previewWorkflow.value
    if (!workflow) return ''
    const { kind, role } = evaluateWorkflowApplicability(workflow, filledSlotRoles.value)
    if (!kind || !role) return ''
    return describePreviewWorkflowSkip(role, workflow.name, kind)
  })

  /** 立即刷新预览（按请求序号丢弃过期响应）；失败只写 `previewError`，不影响提交状态机。 */
  async function refreshPreviewPrompt(): Promise<void> {
    // P3 手动改写：预览文本就是用户原文，发 dry-run 只会拿回同一份内容，
    // 但仍可能覆盖正在编辑的 `previewPrompt`；直接 return 由 clear 时再刷新。
    if (promptOverride.value !== null) {
      previewLoading.value = false
      return
    }

    const blocked = previewWorkflowSkipReason.value
    if (blocked) {
      // 前置校验命中：不发请求，直接展示现象 / 原因 / 下一步。
      previewRequestSeq += 1
      previewTimer = null
      previewPrompt.value = ''
      clearPreviewNegative()
      previewError.value = blocked
      previewLoading.value = false
      return
    }

    const seq = ++previewRequestSeq
    previewLoading.value = true
    previewError.value = ''

    try {
      const response = await previewRecipePrompt(buildPreviewRequest())
      if (seq !== previewRequestSeq) return
      previewPrompt.value = typeof response.prompt === 'string' ? response.prompt : ''
      // 最终负向与正向同批返回：缺字段按空（旧后端不返回时不显示错误的旧值）。
      previewNegativePrompt.value =
        typeof response.negative_prompt === 'string' ? response.negative_prompt : ''
      previewNegativeEffective.value =
        typeof response.negative_effective === 'boolean' ? response.negative_effective : null
      if (!previewPrompt.value) {
        previewError.value =
          '提示词预览为空。原因：后端未返回 prompt 字段。下一步：点击「重试」再次请求，仍为空请检查工作流是否支持提示词。'
      }
    } catch (cause) {
      if (seq !== previewRequestSeq) return
      previewPrompt.value = ''
      clearPreviewNegative()
      previewError.value = describePreviewFailure(cause)
    } finally {
      if (seq === previewRequestSeq) previewLoading.value = false
    }
  }

  /**
   * 清空手动改写，回到碎片驱动的自动模式。
   *
   * 清空后必须主动刷新一次预览：手动期间 `refreshPreviewPrompt` 是空转的，
   * 不刷新会一直显示进入手动模式前的旧文本。
   */
  function clearPromptOverride(): void {
    if (promptOverride.value === null) return
    promptOverride.value = null
    previewError.value = ''
    void refreshPreviewPrompt()
  }

  /**
   * 400ms 防抖刷新。
   *
   * 三槽全空时不发请求：后端对 `total == 0` 明确返回 400「请至少选择一个参考图」，
   * 预览区改为中性占位，避免一进页面就出现红色错误。
   */
  function schedulePreviewRefresh(): void {
    if (previewTimer !== null) clearTimeout(previewTimer)

    if (draft.totalSelected.value === 0) {
      previewTimer = null
      previewRequestSeq += 1
      previewPrompt.value = ''
      clearPreviewNegative()
      previewError.value = ''
      previewLoading.value = false
      return
    }

    previewTimer = setTimeout(() => {
      previewTimer = null
      void refreshPreviewPrompt()
    }, RECIPE_PREVIEW_DEBOUNCE_MS)
  }

  watch(
    [
      () => draft.portrait.value,
      () => draft.costume.value,
      () => draft.pose.value,
      style,
      promptSuffix,
      workflowSelection,
      // 工作流目录加载完成后 previewWorkflow 从 null 变为默认项，需要重新预览。
      previewWorkflow,
      bodyMode,
      baseSeed,
      // 文本补充与负向也进提交体，预览必须跟着刷新（否则预览 ≠ 真实提交）。
      () => draft.textFragments.value,
      () => draft.negativePrompt.value,
      // P2/P4：模式与补充开关决定文本是否发送，切换后必须刷新预览。
      () => draft.slotModes.value,
      () => draft.supplementFlags.value,
    ],
    () => schedulePreviewRefresh(),
    { immediate: true },
  )

  onBeforeUnmount(() => {
    if (previewTimer !== null) clearTimeout(previewTimer)
    previewTimer = null
    previewRequestSeq += 1
  })

  /**
   * 切换工作流后重建尺寸选项：
   * 清掉新工作流不支持但已选中的档位 / 比例，绝不把用不上的参数发出去。
   */
  function reconcileSizeSelections(): void {
    qualitySelection.value = reconcileQualitySelection(
      qualitySelection.value,
      qualityOptions.value,
    )
    ratioSelection.value = reconcileRatioSelection(
      ratioSelection.value,
      aspectRatios.value,
      defaultRatio.value,
    )
  }

  watch(
    [workflowPath, qualityOptions, aspectRatios, defaultRatio],
    () => reconcileSizeSelections(),
    { immediate: true, flush: 'sync' },
  )

  /**
   * 读取本机工作流目录（scope=studio）。
   *
   * 自动选中后端 `default`（当前为 Qwen21+VNCCS）；它缺失或不在列表时回落
   * 第一条。用户已手动选择且该路径仍可用时保留用户选择（重试刷新不覆盖）。
   */
  async function loadStudioWorkflows(): Promise<void> {
    workflowsLoading.value = true
    workflowsError.value = ''
    try {
      const response = await fetch(STUDIO_WORKFLOWS_ENDPOINT)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const body = (await response.json()) as {
        workflows?: unknown
        default?: unknown
      }
      if (!body || !Array.isArray(body.workflows)) throw new Error('响应结构异常')

      const options: StudioWorkflowOption[] = []
      for (const raw of body.workflows) {
        if (!raw || typeof raw !== 'object') continue
        const item = raw as Record<string, unknown>
        if (typeof item.path !== 'string' || !item.path) continue
        options.push({
          path: item.path,
          name: typeof item.name === 'string' ? item.name : item.path,
          source: typeof item.source === 'string' ? item.source : '',
          relPath: typeof item.rel_path === 'string' ? item.rel_path : '',
          imageSlots: Number(item.image_slots) || 0,
          inputCount: Number(item.input_count) || 0,
          recommended: item.recommended === true,
          // 三态解析：缺失=undefined（旧后端宽松）/ 空数组或脏数据=[]（不可识别，禁用）/
          // 非空=按角色匹配。
          slots: parseWorkflowSlots(item.slots),
          extraKind: parseStudioExtraKind(item.extra_kind),
          // 图号表：缺字段（旧后端）时为空对象 → 前端不显示「图N」徽标。
          figureNumbers: parseFigureNumbers(item.figure_numbers),
          caps: parseStudioCaps(item.caps),
          params: parseStudioParams(item.params),
        })
      }

      workflows.value = options
      workflowDefault.value = typeof body.default === 'string' ? body.default : ''
      // 保留仍存在于目录中的已选工作流（保序、去重）；全部失效时清空回落默认项。
      const available = new Set(options.map((item) => item.path))
      workflowSelection.value = workflowSelection.value.filter((path) => available.has(path))
      reconcileSizeSelections()
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      workflowsError.value = `读取工作流列表失败。原因：${message}。下一步：点击「重试」重新读取，或确认后端服务在线。`
    } finally {
      workflowsLoading.value = false
      // 目录已给出结论：此后 `workflowPath` 的单选写入都来自用户操作 / 降级确认。
      pendingSessionWorkflowRestore = false
    }
  }

  /** 工作流多选：点已选取消，否则追加（保持有序，天然去重）。 */
  function toggleWorkflow(path: string): void {
    workflowSelection.value = workflowSelection.value.includes(path)
      ? workflowSelection.value.filter((item) => item !== path)
      : [...workflowSelection.value, path]
  }

  /** 设置工作流多选（v-model 入口）：去空白、保序去重。 */
  function setWorkflowSelection(paths: readonly string[]): void {
    const seen = new Set<string>()
    const next: string[] = []
    for (const path of paths) {
      const trimmed = typeof path === 'string' ? path.trim() : ''
      if (!trimmed || seen.has(trimmed)) continue
      seen.add(trimmed)
      next.push(trimmed)
    }
    workflowSelection.value = next
  }

  /**
   * 素体开关（契约 C-REF-BODY-MODE@1）。
   *
   * 2026-11-08 改为**非破坏**：不再清空服装槽（`removeCostume` /
   * `removePersonBCostume` / `clearExtraCostume` 已移除）。
   *
   * 为什么安全：后端拒绝的是「`body_mode=bare` + 提交服装」，而不是「UI 有服装选择」。
   * 提交层已按生效体态裁掉服装——`slotCounts.costume` 归零、`costumeDimensionForBodyMode`
   * 组合裁剪、`buildRecipeRequest` 跳过 `costume_*` / `extra_costume_*`。
   * 这样用户切回服装模式时原选择还在，不必重新挑一遍。
   */
  function setBodyMode(mode: RecipeBodyMode): void {
    bodyMode.value = mode
  }

  /** 消费后清空自动取消提示，避免同一条消息重复弹出。 */
  function clearWorkflowSelectionNotice(): void {
    workflowSelectionNotice.value = ''
  }

  /** 消费后清空自动裁剪提示，避免同一条消息重复弹出。 */
  function clearWorkflowTrimNotice(): void {
    workflowTrimNotice.value = ''
  }

  /** 消费后清空「缺服装 → 素体展示」提示，避免重复弹出。 */
  function clearBodyModeNotice(): void {
    bodyModeNotice.value = ''
  }

  /**
   * 槽位变化后，已勾选但不再适用的工作流**自动取消并提示**（绝不静默）。
   *
   * 该 watch 同时承担**会话恢复后的两级校验**：目录里已不存在的路径静默剔除；
   * 对当前已选槽位不适用（三态）的项丢弃并 toast。刷新场景下 draft 三槽要等库
   * 加载完成后才 hydrate，所以首次校验可能在这里（槽位角色可见时）才真正生效。
   *
   * 使用默认 flush（组件更新前）而非 sync：`loadStudioWorkflows` 会在赋值
   * `workflows` 后同步过滤失效路径，这时不应再对「目录里已不存在的路径」告警；
   * 回调只针对「目录中存在但 slots 不满足」的项。
   */
  watch(
    [filledSlotRoles, workflows],
    () => {
      if (!workflowSelection.value.length) {
        // 恢复出的选择已被目录过滤清空：恢复流程结束，避免下次误用恢复文案。
        sessionRestoreNoticePending = false
        return
      }
      if (workflows.value.length === 0) return

      // 只取消「对新槽位集合已不适用」的项；仍适用的工作流保持选中。
      // 同一槽位换另一张图时角色集合不变，本 watch 不会触发，也不会取消任何工作流。
      const { kept, removed } = pruneInapplicableWorkflowSelection(
        workflowSelection.value,
        workflows.value,
        filledSlotRoles.value,
      )
      const reasons = removed.map((item) => item.reason).filter(Boolean)
      const restoring = sessionRestoreNoticePending
      if (removed.length) workflowSelection.value = kept

      if (!reasons.length) {
        // 目录中已消失的路径静默剔除（由 loadStudioWorkflows 负责），不产生误导性 toast。
        // draft 已就绪（当前确实有槽位）时，可认为本次恢复校验已经完成。
        if (draft.totalSelected.value > 0) sessionRestoreNoticePending = false
        return
      }

      sessionRestoreNoticePending = false
      // 恢复阶段被丢弃的项用「已跳过」文案，避免被误读成用户刚取消。
      workflowSelectionNotice.value = restoring
        ? describeWorkflowSelectionRestoreNotice(reasons)
        : `已自动取消 ${reasons.length} 个工作流。原因：${reasons.join('；')}。` +
          '下一步：改选支持这些槽位的工作流，或清空对应槽位后重新勾选。'
    },
  )

  /** 画质档多选：点已选取消，否则追加。 */
  function toggleQuality(value: string): void {
    qualitySelection.value = qualitySelection.value.includes(value)
      ? qualitySelection.value.filter((item) => item !== value)
      : [...qualitySelection.value, value]
  }

  /** 比例多选：点已选取消，否则追加。 */
  function toggleRatio(value: string): void {
    ratioSelection.value = ratioSelection.value.includes(value)
      ? ratioSelection.value.filter((item) => item !== value)
      : [...ratioSelection.value, value]
  }

  /** 基础种子输入归一：非负整数，非法值回落默认种子。 */
  function setBaseSeed(value: number | string): void {
    const parsed = Number(value)
    baseSeed.value =
      Number.isFinite(parsed) && parsed >= 0 ? Math.trunc(parsed) : DEFAULT_RECIPE_SEED
  }

  /** 第 4 张：只保存 1 张（后传覆盖前传，与「只提交 extraImages[0]」一致）。 */
  function setExtra(path: string, name: string): void {
    draft.setExtraUpload(path, name)
  }

  /** 第 4 张改为库条目（发型库 / v2-A 人像库）：提交 `extra_id` + `extra_library`。 */
  function setExtraLibrary(library: string, id: string, name: string): void {
    if (library !== 'hair' && library !== 'portrait') return
    draft.setExtraLibrary(library, id, name)
  }

  function clearExtra(): void {
    draft.clearExtra()
  }

  /** V2-C 第 5 槽：上传人物B服装。 */
  function setExtraCostume(path: string, name: string): void {
    draft.setExtraCostumeUpload(path, name)
  }

  /** V2-C 第 5 槽：从服装库选择人物B服装。 */
  function setExtraCostumeLibrary(library: string, id: string, name: string): void {
    if (library !== 'costume' && library !== 'costume-anime') return
    draft.setExtraCostumeLibrary(library, id, name)
  }

  function clearExtraCostume(): void {
    draft.clearExtraCostume()
  }

  /** 清空上一次的运行结果（重试前调用）。 */
  /**
   * 清空「最近一批」兼容视图（重试前调用）。
   *
   * **不**清空 `batches`：批次是真源，其他仍在跑的批次不能被重试抹掉。
   */
  function clearRunState(): void {
    formError.value = ''
    status.value = 'idle'
    progress.value = { stage: 'submit', message: '', percent: null }
    errorMessage.value = ''
    workflowDowngrade.value = null
  }

  /** 提交前校验失败：不创建批次，只记录表单错误（页面单独展示）。 */
  function rejectBeforeSubmit(message: string): null {
    formError.value = message
    errorMessage.value = message
    status.value = 'failed'
    return null
  }

  /**
   * 新 B 组（UX 壳阶段）的预览摘要，供结果区按提交时快照展示。
   *
   * 不参与请求体，也不伪造已提交数据；只把「提交那一刻 B 组选了什么」记在批次上，
   * 避免历史批次被当前设置误标。
   */
  function describePersonBPreview(): string {
    if (!draft.personBEnabled.value) return ''
    const parts: string[] = []
    const summarize = (label: string, names: readonly string[]): void => {
      const unique = [...new Set(names.filter(Boolean))]
      if (!unique.length) return
      const head = unique.slice(0, 2).join('、')
      parts.push(`${label}「${head}${unique.length > 2 ? ` 等 ${unique.length} 张` : ''}」`)
    }
    summarize('B 人像', draft.personBPortrait.value.map((item) => item.发型名称 || item.标题))
    summarize('B 服装', draft.personBCostume.value.map((item) => item.服装名称))
    summarize('B 姿势图', draft.personBPose.value.map((entry) => entry.item.姿势名称))
    const state = personBGroupActive.value
      ? 'B 组（已接入）'
      : 'B 组（本轮未接入：需双人姿势 + 五图人物B工作流）'
    if (!parts.length) return `${state}：未选择素材`
    const note = draft.hasPairPose.value ? '；B 独立姿势图待 P2，当前只提交姿势文字' : ''
    return `${state}：${parts.join(' · ')}${note}`
  }

  /**
   * 执行**一个独立批次**：逐组提交 + 聚合轮询。
   *
   * - 提交并发上限 2；同一时刻只会有一个批次处于提交阶段（`submit()` 拦截），
   *   因此全局 POST 并发同样不会超过 2；
   * - 每个批次有自己的 `jobIds` / `results` / 进度聚合，**绝不与其他批合并**；
   * - 轮询阶段的 GET 由模块级 `pollRequestGate` 做全局并发上限（最多 2 个请求）；
   * - 返回批次对象（含终态），页面据此给本批 toast，不依赖“最近一批”视图。
   */
  async function runBatch(groups: RecipeBatchGroup[]): Promise<RecipeBatch> {
    const batch = reactive<RecipeBatch>({
      id: `batch-${++batchSequence}`,
      createdAt: Date.now(),
      groups: [...groups],
      jobIds: [],
      status: 'submitting',
      total: groups.length,
      done: 0,
      submitted: 0,
      failed: 0,
      results: [],
      groupResults: [],
      errorMessage: '',
      submittedAt: null,
      finishedAt: null,
      personBPreview: describePersonBPreview(),
    })
    batches.value.push(batch)
    syncLatestView(batch)

    // P1：B 八类文本整批共享（不参与组合维度），在并发提交前只编译一次。
    const bText = personBTextFields()

    const outcomes = await runWithConcurrency(
      groups,
      MAX_SUBMIT_CONCURRENCY,
      async (group): Promise<SubmitOutcome> => {
        // 2026-11-08：人物B工作流下，每个 B 变体绑定自己的身份图/服装图；
        // 非人物B工作流（发型/三槽）仍用页面全局的第 4 槽。
        // P1：新 B 组优先，逐组用 group 自己的 B 人像/服装。
        const groupWorkflow =
          effectiveWorkflows.value.find((item) => item.path === group.workflow) ??
          (group.workflow ? undefined : previewWorkflow.value)
        const useBGroup =
          personBGroupActive.value &&
          draft.hasPairPose.value &&
          groupWorkflow?.extraKind === 'person_b'
        const bPortrait = useBGroup ? (group.personBPortrait ?? null) : null
        const bPortraitUpload = uploadPathOf(bPortrait)
        const bCostumeSupported =
          groupWorkflow?.slots?.includes('extra_costume') ?? false
        const bCostume = useBGroup && bCostumeSupported
          ? (group.personBCostume ?? null)
          : null
        const bCostumeUpload = uploadPathOf(bCostume)
        const useVariantImages =
          !personBGroupActive.value &&
          previewWorkflow.value?.extraKind === 'person_b' &&
          draft.hasPairPose.value
        const variantForGroup = useVariantImages
          ? (group.personBVariant ?? draft.activePersonBVariant.value)
          : null
        const variantIdentity = variantForGroup?.identity
        const variantCostume = variantForGroup?.costume
        const request = buildRecipeRequest(group.slots, {
          style: style.value,
          promptSuffix: promptSuffix.value,
          extraPath: useBGroup
            ? (bPortraitUpload ?? '')
            : variantForGroup ? (variantIdentity?.path ?? '') : extraPath.value,
          extraId: useBGroup
            ? (bPortraitUpload ? '' : (bPortrait?.id ?? ''))
            : variantForGroup ? (variantIdentity?.id ?? '') : extraId.value,
          extraLibrary: useBGroup
            ? (bPortrait ? 'portrait' : '')
            : variantForGroup
              ? (variantIdentity?.library ?? '')
              : extraLibrary.value,
          // 第 4 槽文字补充仍按页面全局发送（B 文字走变体自己的碎片）。
          extraText: useBGroup ? '' : extraText.value,
          // V2-C 第 5 槽（人物B服装）：有变体绑图时逐组发送，否则整批共享。
          extraCostumePath: useBGroup
            ? (bCostumeUpload ?? '')
            : variantForGroup ? (variantCostume?.path ?? '') : extraCostumePath.value,
          extraCostumeId: useBGroup
            ? (bCostumeUpload ? '' : (bCostume?.id ?? ''))
            : variantForGroup ? (variantCostume?.id ?? '') : extraCostumeId.value,
          extraCostumeLibrary: useBGroup
            ? (bCostume?.library ?? '')
            : variantForGroup
              ? (variantCostume?.library ?? '')
              : extraCostumeLibrary.value,
          // v1.5：每组提交自己的 B 变体；无变体时回退到当前变体 / 旧自由文字。
          personBVariant: useBGroup
            ? null
            : draft.hasPairPose.value
              ? (group.personBVariant ?? draft.activePersonBVariant.value)
              : null,
          personBText:
            useBGroup || !draft.hasPairPose.value ? '' : draft.personBText.value,
          // P1：B 八类文本独立下发；只有实际走五图人物B工作流的组才带。
          personBPortraitText: useBGroup ? bText.personBPortraitText : '',
          personBCostumeText: useBGroup ? bText.personBCostumeText : '',
          personBPoseText: useBGroup ? bText.personBPoseText : '',
          personBModifierFragments: useBGroup ? bText.personBModifierFragments : '',
          // 每组提交自己的工作流（契约 C-REF-TOTAL@2）；空串由后端用默认工作流。
          workflow: group.workflow,
          quality: group.quality,
          aspectRatio: group.aspectRatio,
          orientation: group.orientation,
          // 缺服装时按素体展示提交（与后端兜底同一规则），否则会出裸体
          bodyMode: effectiveBodyMode.value,
          // 成人向（2026-11-08）：与预览同口径，整批共用 18+ 安全模式判定。
          adultMode: !safeMode.value,
          seed: group.seed,
          seedMode: 'fixed',
          // 八类补充文本 / 负向：每组提示词都带同一份（不参与笛卡尔积）。
          textFragments: draft.textFragments.value,
          // 每组带自己的模式（与预览清单一致）：text 槽不发图片字段。
          slotModes: group.slotModes ?? draft.slotModes.value,
          // P4：补充开关是全局选择，不参与笛卡尔积。
          supplementFlags: draft.supplementFlags.value,
          negativePrompt: draft.negativePrompt.value,
          // P3 手动改写：非空时只发原文，三槽文本 / 修饰 / 后缀由构造器统一跳过。
          promptOverride: promptOverride.value ?? '',
        })
        try {
          const response = await submitRecipe(request)
          if (!response?.success || !response.job_id) {
            const detail =
              response?.errors?.filter(Boolean).join('；') || '后端未返回任务编号'
            throw new RecipeSubmitError('提交出图任务失败', 0, detail)
          }
          batch.submitted += 1
          syncLatestView(batch)
          return { group, response, error: null }
        } catch (error) {
          return { group, response: null, error }
        }
      },
    )

    const submitted = outcomes.filter(
      (outcome): outcome is SubmitOutcome & { response: RecipeSubmitResponse } =>
        outcome.response !== null,
    )
    const submitFailures = outcomes.filter((outcome) => outcome.response === null)

    batch.jobIds = submitted.map((outcome) => outcome.response.job_id)
    batch.failed = submitFailures.length

    // P2 M5：先按批次原始组顺序建槽，保证清单 #组号与提交前一致；
    // 提交失败组也保留一行并写 error，网格里显示灰块 + 原因。
    //
    // 键必须用稳定的数值 `index`：`batch` 是 reactive，`batch.groups` 里的 group
    // 已被 Proxy 包装，与 `result.outcome.group`（原始对象）引用不相等；
    // 用对象做键会导致轮询结果全部查不到，网格退化成 3 个「该组未返回图片」灰块。
    const groupResults = new Map<number, RecipeGroupResult>()
    for (const group of batch.groups) {
      groupResults.set(groupResultKeyOf(group), { group, jobId: 0, urls: [], error: '' })
    }
    for (const outcome of submitFailures) {
      const entry = groupResults.get(groupResultKeyOf(outcome.group))
      if (!entry) continue
      entry.error = describeSubmitFailure(
        outcome.error ?? new RecipeSubmitError('提交出图任务失败', 0, '提交分组为空'),
      )
    }
    batch.groupResults = [...groupResults.values()]

    if (!submitted.length) {
      const first = submitFailures[0]
      batch.status = 'failed'
      batch.errorMessage = describeSubmitFailure(
        first?.error ?? new RecipeSubmitError('提交出图任务失败', 0, '提交分组为空'),
      )
      batch.finishedAt = Date.now()
      syncLatestView(batch)
      return batch
    }

    batch.status = 'polling'
    batch.total = submitted.length
    batch.done = 0
    batch.submittedAt = Date.now()
    syncLatestView(batch)

    // 本批 job 的进度聚合（独立 map，旧批次不会写进这里）。
    const aggregates = new Map<number, { total: number; done: number }>()
    for (const id of batch.jobIds) aggregates.set(id, { total: 1, done: 0 })

    /** 只汇总**本批** job 的 total / done。 */
    function updateBatchAggregates(): void {
      let total = 0
      let done = 0
      for (const value of aggregates.values()) {
        total += Math.max(0, value.total)
        done += Math.max(0, value.done)
      }
      batch.total = Math.max(0, total)
      batch.done = Math.max(0, done)
    }

    // 一批任务共用一条 SSE 连接推送进度；浏览器不支持或连接断开时，
    // awaitRecipeJobs 会退回逐任务轮询（保留原有的单任务失败隔离）。
    const wait = await awaitRecipeJobs(batch.jobIds, {
      onUpdate: (next) => {
        aggregates.set(next.id, {
          total: Number(next.total) || 1,
          done: Number(next.done_count) || 0,
        })
        updateBatchAggregates()
        syncLatestView(batch)
      },
      pollJob: (id, onUpdate) => pollRecipeJob(id, { onUpdate }),
      timeoutMs: RECIPE_POLL_TIMEOUT_MS,
    })
    const pollOutcomes: PollOutcome[] = submitted.map((outcome) => {
      const snapshot = wait.snapshots.get(outcome.response.job_id) ?? null
      return {
        outcome,
        snapshot,
        error: snapshot ? null : (wait.error ?? new Error('任务状态获取失败')),
      }
    })

    const urls: string[] = []
    const failureMessages: string[] = []
    let lastSnapshot: RecipeJobSnapshot | null = null

    for (const result of pollOutcomes) {
      lastSnapshot = result.snapshot ?? lastSnapshot
      const entry = groupResults.get(groupResultKeyOf(result.outcome.group))
      if (result.snapshot && isJobSucceeded(result.snapshot)) {
        const groupUrls = recipeJobResultUrls(result.snapshot)
        urls.push(...groupUrls)
        if (entry) {
          entry.jobId = result.outcome.response.job_id
          entry.urls = groupUrls
        }
      } else if (result.snapshot) {
        batch.failed += 1
        const message = describeJobFailure(result.snapshot)
        failureMessages.push(message)
        if (entry) {
          entry.jobId = result.outcome.response.job_id
          entry.error = message
        }
      } else {
        batch.failed += 1
        const message = describePollFailure(result.error, result.outcome.response.job_id)
        failureMessages.push(message)
        if (entry) {
          entry.jobId = result.outcome.response.job_id
          entry.error = message
        }
      }
    }
    if (submitFailures.length) {
      failureMessages.unshift(
        describeSubmitFailure(
          submitFailures[0]?.error ??
            new RecipeSubmitError('提交出图任务失败', 0, '部分分组提交失败'),
        ),
      )
    }

    batch.results = [...new Set(urls)]
    // 逐组结果同步落盘：网格按 groupResults 渲染「#组号 · 工作流 · 尺寸」。
    batch.groupResults = [...groupResults.values()]
    if (failureMessages.length) {
      batch.status = 'failed'
      batch.errorMessage = failureMessages.slice(0, 3).join('\n')
      batch.finishedAt = Date.now()
      syncLatestView(batch)
      return batch
    }

    if (!batch.results.length) {
      batch.status = 'failed'
      batch.errorMessage = describeMissingResult(
        lastSnapshot ?? {
          id: batch.jobIds[0] ?? 0,
          status: 'done',
          total: 0,
          done_count: 0,
          error_count: 0,
          items: [],
        },
      )
      batch.finishedAt = Date.now()
      syncLatestView(batch)
      return batch
    }

    batch.done = batch.total
    batch.status = 'success'
    batch.finishedAt = Date.now()
    previousResultUrl.value = batch.results[0]
    syncLatestView(batch)
    return batch
  }

  /** 用当前工作流与当前选择构造分组（提交前 / 强制提交共用）。 */
  function buildCurrentBatchGroups(): RecipeBatchGroup[] {
    // V2-C：双人配对模式只取每槽首张 / 首组变体，避免任何跨槽笛卡尔积。
    const singlePair = draft.pairModeActive.value
    const portraitSource = singlePair ? draft.portrait.value.slice(0, 1) : draft.portrait.value
    const costumeSource = singlePair ? draft.costume.value.slice(0, 1) : draft.costume.value
    const poseSource = singlePair ? draft.pose.value.slice(0, 1) : draft.pose.value
    const variantSource = singlePair
      ? draft.personBVariants.value.slice(0, 1)
      : draft.personBVariants.value
    return buildBatchGroups({
      portrait: portraitSource,
      // 素体模式：即使槽位有残留服装也绝不进入组合（后端 bare + 服装 = 400）。
      costume: costumeDimensionForBodyMode(costumeSource, effectiveBodyMode.value),
      pose: poseSource.map((entry) => entry.item),
      workflows: effectiveWorkflows.value.map((item) => item.path),
      qualities: qualitySelection.value,
      ratios: ratioSelection.value,
      qualityEnabled: caps.value.quality,
      orientationEnabled: caps.value.orientation,
      baseSeed: baseSeed.value,
      // P2：模式与文本一起进入组合，提交体按模式只发图片或文本。
      slotModes: draft.slotModes.value,
      // P4：矩阵组键只统计真正生效的文本（image + 开关关闭的文本不参与）。
      slotTexts: compileActiveSlotTexts(
        draft.textFragments.value,
        draft.slotModes.value,
        draft.supplementFlags.value,
      ),
      // v1.5：双人姿势下 A 人像与 B 变体 1:1 配对；单人姿势不启用。
      personBVariants:
        !personBGroupActive.value && draft.hasPairPose.value ? variantSource : [],
      // P1：新 B 组优先；按较短侧配对，B 人像/服装逐组下发。
      personBGroup: personBGroupActive.value ? personBGroupInput.value : undefined,
    })
  }

  /**
   * 提交前可裁剪探测（M < N 时才调用）。
   *
   * - `{ allTrimmable: true }`：后端确认空槽能被安全裁掉 → 直接提交；
   * - `{ allTrimmable: false, blockedReason }`：至少一个工作流裁不掉 → 弹确认框；
   * - `null`：探测本身失败（网络 / 旧后端）→ 退回原确认框，绝不因探测失败放行。
   */
  async function probeWorkflowTrim(): Promise<{
    allTrimmable: boolean
    blockedReason: string
  } | null> {
    try {
      const response = await checkRecipeTrim({
        workflows: effectiveWorkflows.value.map((item) => item.path),
        roles: filledSlotRoles.value,
      })
      const blocked = response.workflows.find((item) => !item.trimmable)
      if (response.all_trimmable === true && !blocked) {
        return { allTrimmable: true, blockedReason: '' }
      }
      const reason = response.workflows.find((item) => !item.trimmable && item.reason)?.reason
      return { allTrimmable: false, blockedReason: reason ?? '' }
    } catch {
      // 探测失败不阻断提交：退回「确认后再提交」，旧后端 / 瞬时网络问题不会卡死。
      return null
    }
  }

  /**
   * 提交入口。
   *
   * **只拦截“正在提交中”的重复点击**（防抖 / 防连点）；轮询期间允许再次提交，
   * 新批次会立刻入队（ComfyUI 串行执行，无需等上一批出图）。
   *
   * 返回 `null` 表示没有创建批次：校验失败（`formError` 已写好三句式文案）或
   * 需要先过降级确认框（`workflowDowngrade` 非空）。成功创建批次时返回该批次对象。
   */
  async function submit(): Promise<RecipeBatch | null> {
    if (submitting.value) return null
    workflowDowngrade.value = null
    workflowTrimNotice.value = ''
    bodyModeNotice.value = ''
    formError.value = ''
    errorMessage.value = ''

    // 先记住上一次展示过的结果，再开始新批：失败区「查看上一张结果」依赖它。
    const lastResultUrl =
      [...batches.value].reverse().flatMap((batch) => batch.results)[0] ??
      resultUrls.value[0]
    if (lastResultUrl) previousResultUrl.value = lastResultUrl

    if (effectiveWorkflows.value.length === 0) {
      return rejectBeforeSubmit(
        '无法提交。原因：尚未选择出图工作流。下一步：在工作流下拉中选择一个可用工作流后重试。',
      )
    }

    // 工作流角色能力缺口的最后一道拦截（watch 已自动取消，这里防竞态）。
    // 收紧点：slots === []（角色不可识别）也必须拦截，不再放行。
    for (const workflow of effectiveWorkflows.value) {
      const { kind, role } = evaluateWorkflowApplicability(workflow, filledSlotRoles.value)
      if (!kind || !role) continue
      return rejectBeforeSubmit(
        `无法提交。原因：${describeWorkflowUnavailable(kind, role, workflow.name)}。` +
          '下一步：取消勾选该工作流，或清空对应槽位后重试。',
      )
    }

    // P3 手动改写（方案 §14.2）：原文提交时后端不再二次编译，
    // P2 的槽位文本校验（text 模式碎片 / 素体+服装 / 双人姿势）没有意义，全部跳过；
    // 但仍必须至少 1 张参考图 —— 手动模式只替换「提示词」，不替换图片输入。
    if (promptOverride.value !== null) {
      // 空白的「手动改写」不能静默回落到自动生成：后端会把空 override 当自动模式，
      // 用户看到的是手动徽标、实际跑的却是碎片提示词。
      if (!promptOverride.value.trim()) {
        return rejectBeforeSubmit(
          '无法提交。原因：手动改写内容为空。下一步：填写提示词后重试，或点「恢复自动生成」。',
        )
      }
      const imageCounts: Record<RecipeSlotKey, number> = {
        portrait: draft.portraitCount.value,
        costume: draft.costumeCount.value,
        pose: draft.poseCount.value,
      }
      const hasImageSlot = RECIPE_SLOT_KEYS.some(
        (slot) => draft.slotModes.value[slot] === 'image' && imageCounts[slot] > 0,
      )
      if (!hasImageSlot && !extraFilled.value && !extraCostumeFilled.value) {
        return rejectBeforeSubmit(
          `无法提交。原因：${NO_IMAGE_SLOT_HINT}。下一步：选择至少 1 张参考图后重试。`,
        )
      }
    } else {
      // P2 替代态校验（方案 §4.4）：
      // - 至少 1 个 image 模式槽有图（文本不计入参考图）；
      // - text 模式必须有对应类碎片；
      // - 素体展示 + 服装文本；
      // - 姿势文本 + 双人姿势（当前 / 上次选择）。
      // P1 的「文本非空但槽无图」不再阻止：无图 + 文本正是替代态的合法用法。
      const modeConflict = describeAlternateModeConflicts({
        modes: draft.slotModes.value,
        fragments: draft.textFragments.value,
        imageCounts: {
          portrait: draft.portraitCount.value,
          costume: draft.costumeCount.value,
          pose: draft.poseCount.value,
        },
        extraFilled: extraFilled.value,
        bodyMode: bodyMode.value,
        // 批量多选时只要任一姿势是 pair* 就阻止：文本替代无法表达双人语义。
        poseId:
          draft.pose.value.find((entry) => entry.item.id.startsWith('pair'))?.item.id ??
          draft.pose.value[0]?.item.id ??
          draft.lastPoseId.value,
      })
      if (modeConflict) {
        return rejectBeforeSubmit(
          `无法提交。原因：${modeConflict}。下一步：调整槽位模式或文本补充后重试。`,
        )
      }
    }


    if (batchOverLimit.value) {
      return rejectBeforeSubmit(
        `无法提交。原因：${batchLimitMessage.value}。下一步：减少素材或尺寸档位后重试。`,
      )
    }

    // 缺服装会自动按素体展示提交（后端同规则兜底）：必须明确告知，不静默改变语义。
    // 放在能力预判之前：自动裁剪分支会直接 return，提示不能因此漏掉。
    if (bodyMode.value === 'costume' && effectiveBodyMode.value === 'bare') {
      bodyModeNotice.value =
        '未选择服装参考图，已按素体展示（无服装）提交；要穿衣服请先选择服装再提交'
    }

    // 能力预判：M（非空槽数）< N（工作流输入数）。
    // 先问后端「空槽能不能裁」：能裁就直接提交并用 toast 告知，裁不掉才弹确认框。
    const inputCount = workflowInputCount.value
    if (inputCount > 0 && activeSlotCount.value < inputCount) {
      const plan = await probeWorkflowTrim()
      if (plan?.allTrimmable) {
        workflowTrimNotice.value =
          `当前工作流需要 ${inputCount} 个输入，已按 ${activeSlotCount.value} 图自动裁剪空槽后提交`
        return runBatch(buildCurrentBatchGroups())
      }
      workflowDowngrade.value = {
        message: describeWorkflowDowngrade(inputCount, activeSlotCount.value),
        slotCount: activeSlotCount.value,
        inputCount,
        // 候选再按 slots 过滤：降级切换后也不应把用户带到「缺当前槽位输入」的工作流。
        candidates: buildWorkflowDowngradeCandidates(
          workflows.value,
          workflowPath.value,
          activeSlotCount.value,
        ).filter(
          (candidate) =>
            workflowInapplicableRole(candidate, filledSlotRoles.value) === null,
        ),
        blockedReason: plan?.blockedReason ?? '',
      }
      return null
    }

    const groups = buildCurrentBatchGroups()
    return runBatch(groups)
  }

  /** 降级确认：切到候选工作流（按新 caps 重建尺寸）后继续提交。 */
  async function confirmWorkflowDowngrade(path: string): Promise<RecipeBatch | null> {
    if (!workflowDowngrade.value) return null
    workflowDowngrade.value = null
    workflowPath.value = path
    // watch 是 sync，但显式再对齐一次，保证提交体不会带旧工作流的尺寸参数。
    reconcileSizeSelections()
    return submit()
  }

  /**
   * 降级确认：不切换工作流，仍然提交。
   *
   * 空槽允许提交是硬要求；后端会尝试裁剪工作流副本，成功则照常出图，
   * 无法裁剪时返回 400（原文由 `describeSubmitFailure` 展示给用户）。
   */
  async function confirmCurrentWorkflowDowngrade(): Promise<RecipeBatch | null> {
    if (!workflowDowngrade.value) return null
    workflowDowngrade.value = null
    return runBatch(buildCurrentBatchGroups())
  }

  /** 取消降级：不提交，保持当前工作流与选择。 */
  function cancelWorkflowDowngrade(): void {
    workflowDowngrade.value = null
    formError.value = ''
    errorMessage.value = ''
    status.value = 'idle'
  }

  /**
   * 复用某批参数（P2 M5）。
   *
   * 只回填 `groups[0]` 会丢掉槽位组合维度，导致「复用后清单只剩 1 组」；
   * 因此按该批**全部** group 去重收集槽位条目、工作流、画质档与比例，
   * 使清单组数能还原到提交前。
   */
  function reuseBatchParams(batch: RecipeBatch): boolean {
    if (!batch.groups.length) return false

    const portraits = new Map<string, PortraitItem>()
    const costumes = new Map<string, CostumeItem>()
    const poses = new Map<string, PoseItem>()
    for (const group of batch.groups) {
      if (group.slots.portrait) portraits.set(group.slots.portrait.id, group.slots.portrait)
      if (group.slots.costume) costumes.set(group.slots.costume.id, group.slots.costume)
      if (group.slots.pose) poses.set(group.slots.pose.id, group.slots.pose)
    }

    draft.portrait.value = [...portraits.values()]
    draft.costume.value = [...costumes.values()]
    draft.pose.value = [...poses.values()].map((item) => ({ item, useDepth: false }))

    // P2：槽位回填后再恢复模式（顺序不能反：先设槽位会触发 empty → image）。
    const firstGroup = batch.groups[0]
    if (firstGroup?.slotModes) {
      draft.slotModes.value = { ...firstGroup.slotModes }
    }

    const workflows = [
      ...new Set(batch.groups.map((group) => group.workflow).filter((path) => !!path)),
    ]
    setWorkflowSelection(workflows)
    qualitySelection.value = [
      ...new Set(batch.groups.map((group) => group.quality).filter((quality) => !!quality)),
    ]
    ratioSelection.value = [
      ...new Set(batch.groups.map((group) => group.aspectRatio).filter((ratio) => !!ratio)),
    ]
    return true
  }

  /** 清理已结束批次（只保留运行中批次），返回移除数量。 */
  function clearFinishedBatches(): number {
    const kept = batches.value.filter(isRecipeBatchRunning)
    const removed = batches.value.length - kept.length
    if (!removed) return 0

    batches.value = kept
    const latest = kept[kept.length - 1]
    if (latest) syncLatestView(latest)
    else clearRunState()
    return removed
  }

  /** 重试：清掉表单错误后重新提交（沿用当前槽位与设置，产生一个独立新批次）。 */
  async function retry(): Promise<RecipeBatch | null> {
    clearRunState()
    return submit()
  }

  return {
    // 工作流目录与多选（契约 C-REF-WF-SLOTS@1 / C-REF-TOTAL@2）
    workflows,
    workflowDefault,
    workflowDefaultPath,
    workflowSelection,
    selectedWorkflows,
    effectiveWorkflows,
    usesDefaultWorkflow,
    workflowDimension,
    setWorkflowSelection,
    toggleWorkflow,
    workflowSelectionNotice,
    clearWorkflowSelectionNotice,
    workflowPath,
    workflowsLoading,
    workflowsError,
    loadStudioWorkflows,
    currentWorkflow,
    workflowInputCount,
    // 槽位角色（工作流适用性判定）
    filledSlotRoles,
    // 体态模式（素体开关，契约 C-REF-BODY-MODE@1）
    bodyMode,
    setBodyMode,
    /** 实际生效的体态模式（缺服装 → bare）；预览/提交/组合都按它走。 */
    effectiveBodyMode,
    /** 缺服装自动切素体展示时的提示文案（页面转 toast）。 */
    bodyModeNotice,
    clearBodyModeNotice,
    /** 当前生效工作流是否支持第 4 张（extra）；false 时页面隐藏上传入口。 */
    supportsExtraSlot,
    /** V2-C：当前生效工作流是否支持第 5 槽（人物B服装）。 */
    supportsExtraCostumeSlot,
    // 能力与尺寸
    caps,
    qualityOptions,
    aspectRatios,
    defaultRatio,
    qualitySelection,
    ratioSelection,
    toggleQuality,
    toggleRatio,
    followsReferenceSize,
    baseSeed,
    setBaseSeed,
    // 批量预览
    slotCounts,
    filledSlotNames,
    activeSlotCount,
    batchTotal,
    batchOverLimit,
    batchLimitMessage,
    // 提交设置
    style,
    promptSuffix,
    extraPath,
    extraName,
    extraFilled,
    extraLibrary,
    setExtra,
    setExtraLibrary,
    clearExtra,
    // V2-C 第 5 槽（人物B服装）
    extraCostume,
    extraCostumeFilled,
    setExtraCostume,
    setExtraCostumeLibrary,
    clearExtraCostume,
    // P1：新 B 组接入状态与配对提示
    personBGroupActive,
    personBGroupPortraitCount,
    personBPairNotice,
    // 提示词只读预览（dry_run，与正式提交完全独立）
    previewPrompt,
    /** 编译后的最终负向（§11.3：预览 = 最终正向 + 最终负向）。 */
    previewNegativePrompt,
    /** 负向是否在当前工作流生效；null = 后端未返回该字段。 */
    previewNegativeEffective,
    previewError,
    previewLoading,
    refreshPreviewPrompt,
    previewWorkflow,
    previewWorkflowSkipReason,
    /** 角色 → 图号（「图N」徽标的唯一来源；旧后端为空对象）。 */
    figureNumbers,
    // P3 手动改写：null = 自动模式；字符串 = 用户原文（提交时作为 prompt_override）
    promptOverride,
    setPromptOverride,
    clearPromptOverride,
    // 降级确认
    workflowDowngrade,
    confirmWorkflowDowngrade,
    confirmCurrentWorkflowDowngrade,
    cancelWorkflowDowngrade,
    // 空槽自动裁剪提示（可裁剪时直接提交，用 toast 告知）
    workflowTrimNotice,
    clearWorkflowTrimNotice,
    // 运行状态
    status,
    progress,
    progressPercent,
    jobId,
    jobIds,
    resultUrls,
    primaryResultUrl,
    previousResultUrl,
    errorMessage,
    busy,
    // 多批次真源：页面按批展示结果，各批状态 / 结果互不覆盖。
    batches,
    reuseBatchParams,
    clearFinishedBatches,
    submitting,
    polling,
    formError,
    selectedCount,
    canSubmit,
    submit,
    retry,
    clearRunState,
  }
}