/** 合成台契约模型：常量、类型、纯函数（无 Vue / 无 HTTP）。 */

import type { CostumeItem, PoseItem, PortraitItem } from '../api/reference'
import {
  compilePersonBVariant,
  compileRecipeTextFragments,
  createImageSlotModes,
  hasStyleFragment,
  isSlotTextActive,
  resolveSlotModes,
  resolveSupplementFlags,
} from './recipeTextFragments'
import type {
  RecipePersonBVariant,
  RecipeSlotKey,
  RecipeSlotModes,
  RecipeSlotTexts,
  RecipeSupplementFlags,
  RecipeTextFragments,
  SelectedFragment,
} from './recipeTextFragments'
import { uploadPathOf } from './useReferenceRecipeDraft'
import { viewUrl } from '../api/client'
import type { QualityOption, WorkflowCaps, WorkflowParams } from './useWorkflowCaps'

// 契约常量
// ---------------------------------------------------------------------------

/** 提交端点（后端 `reference_library.create_reference_recipe`）。 */
export const RECIPE_ENDPOINT = '/api/reference/recipes'
/** 提交前可裁剪探测端点（后端 `reference_library.check_reference_trim`）。 */
export const TRIM_CHECK_ENDPOINT = '/api/reference/trim-check'
/** 任务快照端点前缀。 */
export const RECIPE_JOB_ENDPOINT = '/api/jobs'
/** 工作流目录（合成台只看能塞参考图的工作流）。 */
export const STUDIO_WORKFLOWS_ENDPOINT = '/api/workflows?scope=studio'
/**
 * 工作流多选的**会话级**记忆键（sessionStorage）。
 *
 * 只在本会话内有效：切页签（SPA）、刷新、从库页返回合成台都会恢复；
 * 关闭标签页后浏览器自然清空，无需额外清理代码。
 * **绝不**混入 `pb.reference_studio_v1`（那里 `workflow` 仍表示首条单选）。
 */
export const WORKFLOW_SELECTION_SESSION_KEY = 'pb.reference_studio_workflows_session_v1'
/** 轮询间隔与上限，与 React `recipeClient` 一致。 */
export const RECIPE_POLL_INTERVAL_MS = 1500
export const RECIPE_POLL_TIMEOUT_MS = 30 * 60 * 1000
/** 连续查询失败上限：达到 3 次才把错误抛给用户。 */
export const MAX_CONSECUTIVE_POLL_ERRORS = 3
/** 后端 `RecipeRequest.seed` 的固定种子默认值。 */
export const DEFAULT_RECIPE_SEED = 100000
/** 全组合上限：超过后页面禁用提交，避免一次排爆后端队列。 */
export const MAX_BATCH_RECIPES = 100
/** 提交并发上限：逐组 POST 时最多同时 2 个请求。 */
export const MAX_SUBMIT_CONCURRENCY = 2
/** 提示词 dry-run 预览的防抖间隔：槽位 / 画风 / 补充要求变化后 400ms 刷新。 */
export const RECIPE_PREVIEW_DEBOUNCE_MS = 400
/** 任务成功终态（逐字对齐 React）。 */
export const SUCCESS_JOB_STATUSES: ReadonlySet<string> = new Set([
  'success',
  'done',
  'completed',
  'finished',
])
/** 任务失败终态（逐字对齐 React）。 */
export const FAILURE_JOB_STATUSES: ReadonlySet<string> = new Set([
  'failed',
  'error',
  'cancelled',
  'canceled',
  'stopped',
])

/** 提交用画风；旧值一律降级为 realistic（后端只认这两项）。 */
export type RecipeStyle = 'none' | 'realistic'
/** 服装槽可用的两个库。 */
export type RecipeCostumeLibrary = 'costume' | 'costume-anime'

/**
 * 工作流支持的业务角色（后端 `slots` 字段，契约 C-REF-WF-SLOTS@1）。
 *
 * `extra` 对应合成台的第 4 张上传图；槽位为空时不参与适用性判定。
 */
export type StudioWorkflowSlot = 'portrait' | 'costume' | 'pose' | 'extra'

/** 合法角色值（顺序即 UI 提示顺序）。 */
export const STUDIO_WORKFLOW_SLOTS: readonly StudioWorkflowSlot[] = [
  'portrait',
  'costume',
  'pose',
  'extra',
]

/** 角色中文名（用于「缺少 X 输入，不适用于当前已选 X」文案）。 */
const WORKFLOW_SLOT_LABELS: Readonly<Record<StudioWorkflowSlot, string>> = {
  portrait: '人像',
  costume: '服装',
  pose: '姿势',
  extra: '第 4 张',
}

/** 体态模式：`costume` 服装模式；`bare` 素体展示（无服装）。 */
export type RecipeBodyMode = 'costume' | 'bare'

// ---------------------------------------------------------------------------
// 类型
// ---------------------------------------------------------------------------

/** 文本补充碎片的契约类型统一从这里导出（实现见 `recipeTextFragments`）。 */
export type { RecipeTextFragments, SelectedFragment }

/** 提交给后端的配方请求（字段名与后端 `RecipeRequest` 逐字一致）。 */
export interface RecipeSubmitRequest {
  portrait_id?: string
  costume_id?: string
  pose_id?: string
  /** 本地上传图路径（与对应 `*_id` 二选一；后端校验必须在 uploads 内）。 */
  portrait_path?: string
  costume_path?: string
  pose_path?: string
  costume_library?: RecipeCostumeLibrary
  extra_path?: string
  /** 第 4 张库条目：与 `extra_path` 二选一。 */
  extra_id?: string
  /** 第 4 张库标识（当前仅 hair）；与 `extra_id` 配套。 */
  extra_library?: string
  /** 第 4 张文字补充；只在 extra 图片存在时发送（后端对“有文本无图”返回 400）。 */
  extra_text?: string
  /** 合成台工作流文件名 / 库内路径；空 = 后端默认 Qwen21+VNCCS。 */
  workflow?: string
  /** 画质档位；`caps.quality === false` 时不发送。 */
  quality?: string
  /** 输出比例；`caps.orientation === false` 时不发送。 */
  aspect_ratio?: string
  /** 横竖方向（由比例推导）；`caps.orientation === false` 时不发送。 */
  orientation?: 'portrait' | 'landscape'
  /** 体态模式；`bare` 时后端不接受服装（提交体不会带 `costume_id`）。 */
  body_mode?: RecipeBodyMode
  style: RecipeStyle
  /** 追加要求；手动改写（`prompt_override`）模式不发送。 */
  prompt_suffix?: string
  seed: number
  seed_mode: 'fixed' | 'random'
  /** 双人姿势的人物 B 文字设定；空不发送。 */
  person_b_text?: string
  /** v1.5：人物 B 的面部/身材碎片；只在双人姿势下发送。 */
  person_b_portrait_text?: string
  /** v1.5：人物 B 的服饰碎片；只在双人姿势下发送。 */
  person_b_costume_text?: string
  /** 人像补充文本（人物面部 + 人物身材）；空不发送。 */
  portrait_text?: string
  /** 服装补充文本（人物服饰）；空不发送。 */
  costume_text?: string
  /** 姿势补充文本（姿态动作）；空不发送。 */
  pose_text?: string
  /**
   * P4 跨源补充开关：image 模式 + 文本时，后端只有看到对应 true 才追加
   * 「此外需体现」；text 模式不发送该字段（文本是替代）。
   */
  portrait_supplement?: boolean
  costume_supplement?: boolean
  pose_supplement?: boolean
  /** 修饰层渲染结果（视角 / 场景 / 光影 / 画风，多行 `• 类型：内容`）；空不发送。 */
  modifier_fragments?: string
  /**
   * 真负向（后端透传 `FaceswapRequest.negative_prompt`）；空不发送。
   *
   * 手动改写模式（`prompt_override` 非空）下这是**唯一**负向来源：
   * 后端不再自动抽取，前端也不发送任何三槽文本。
   */
  negative_prompt?: string
  /**
   * P3 手动改写：非空 = 按原文提交（方案 §14.3）。
   *
   * 前端只在「手动改写」模式发送；后端据此推断 `skip_compile`（前端不传该字段），
   * 因此手动模式**不发送** `*_text` / `modifier_fragments` / `prompt_suffix`。
   */
  prompt_override?: string
}

/** `POST /api/reference/recipes` 响应（只声明前端用得到的字段）。 */
export interface RecipeSubmitResponse {
  success: boolean
  job_id: number
  total: number
  submitted: number
  queued: number
  errors: string[]
  prompt?: string
  workflow_path?: string
}

/** `POST /api/reference/recipes` 的 dry-run 响应（只声明预览用到的字段）。 */
export interface RecipePreviewResponse {
  success?: boolean
  dry_run?: boolean
  /** 后端按三槽自动组合出的提示词（P1 起为 `compile_prompt` 后的最终正向）。 */
  prompt?: string
  /** 编译后的最终负向（自动抽取 + 用户手填）。 */
  negative_prompt?: string
  /**
   * 当前工作流负向是否生效。
   *
   * `false` 表示后端判定该工作流不消费负向（例如 cfg=1），实际提交为空；
   * `null` / 缺省表示后端未给出判定（旧后端），前端不臆测。
   */
  negative_effective?: boolean | null
  /** 编译前的原始提示词（排障 / 对照用，可缺省）。 */
  prompt_raw?: string
}

/** `POST /api/reference/trim-check` 请求：只报「哪几个槽有图」，不传具体素材。 */
export interface RecipeTrimCheckRequest {
  /** 待探测的工作流路径；空数组 = 后端默认工作流。 */
  workflows: string[]
  /** 已填槽位角色（与后端 `SLOT_ROLES` 同名字符串）。 */
  roles: StudioWorkflowSlot[]
}

/** 单个工作流的探测结果。 */
export interface RecipeTrimCheckItem {
  name: string
  path: string
  input_count: number
  slot_count: number
  trimmable: boolean
  /** 不可提交时的原因（与提交端点 400 文案同源）。 */
  reason: string
}

/** `POST /api/reference/trim-check` 响应。 */
export interface RecipeTrimCheckResponse {
  workflows: RecipeTrimCheckItem[]
  /** 全部工作流都能按当前非空槽提交。 */
  all_trimmable: boolean
}

/** 任务条目里的单张图片（后端 `JobImage`）。 */
export interface RecipeJobImage {
  filename: string
  subfolder?: string
  type?: string
}

/** 任务条目（后端 `JobItem`）。 */
export interface RecipeJobItem {
  prompt_id?: number | null
  status?: string
  error?: string
  images: RecipeJobImage[]
}

/** 任务快照（后端 `JobSnapshot`，只声明合成台用到的字段）。 */
export interface RecipeJobSnapshot {
  id: number
  status: string
  total: number
  done_count: number
  error_count: number
  items: RecipeJobItem[]
  created_at?: string
  updated_at?: string
}

/** 进度文案；`percent` 只在后端 total > 0 时存在。 */
export interface RecipeProgress {
  stage: 'submit' | 'queued' | 'running' | 'done'
  message: string
  percent: number | null
}

/** 工作流下拉选项（`/api/workflows?scope=studio` 的子集）。 */
export interface StudioWorkflowOption {
  path: string
  name: string
  source: string
  relPath: string
  /** LoadImage 槽位数（兼容旧字段）。 */
  imageSlots: number
  /** LoadImage 输入数；提交前能力预判用它和「非空槽数 M」比较。 */
  inputCount: number
  recommended: boolean
  /**
   * 该工作流支持的业务角色（后端 `slots`，契约 C-REF-WF-SLOTS@1）。
   *
   * 三态语义（旧后端 / 异常数据都不能放行"看起来能选、一提交就 400"的项）：
   * - `undefined`：字段缺失（旧后端）→ 能力未知，**不做**适用性判定；
   * - `[]`：字段存在但没有任何可识别角色（UI 格式工作流 / 解析失败）→
   *   **角色不可识别**，对所有非空槽位都不适用，必须置灰禁止勾选；
   * - 非空：按角色匹配，缺少已选槽位角色即不适用。
   */
  slots?: StudioWorkflowSlot[]
  /** 第 4 槽语义（v2-A）：`hair` / `person_b` / 空串；缺省按空串。 */
  extraKind?: StudioExtraKind
  /** 后端探测的注入能力；缺失时由 `useWorkflowCaps` 回落到乐观默认值。 */
  caps?: WorkflowCaps
  /** 画质 / 方向参数描述；用于生成真实档位与比例选项。 */
  params?: WorkflowParams
}

/** 第 4 槽语义：发型参考 / 人物B身份参考 / 空（附加参考）。 */
export type StudioExtraKind = 'hair' | 'person_b' | ''

/**
 * 解析后端 `extra_kind`（v2-A）。
 *
 * 旧后端缺字段 / 脏数据一律回落空串（按普通附加参考处理），不误伤旧目录。
 */
export function parseStudioExtraKind(raw: unknown): StudioExtraKind {
  return raw === 'hair' || raw === 'person_b' ? raw : ''
}

/** 第 4 槽语义互斥的解析结果（v2-A 收尾）。 */
export interface ExtraKindConflictResolution {
  /** 冲突中保留的语义；null = 无需处理（未混选 / 目录未识别出两种语义）。 */
  kind: StudioExtraKind | null
  /** 处理后的选择（保持原顺序）；无需处理时与输入一致。 */
  kept: string[]
  /** 被移除的冲突项路径；无需处理时为空。 */
  removed: string[]
}

/**
 * 第 4 槽语义互斥（v2-A 收尾）。
 *
 * `person_b` 与 `hair` 共用同一个第 4 槽，提示词却按各自语义编译：
 * 同批混选会让其中一条语义错配，因此选择层只保留**最新选中**的一条。
 *
 * 「最新选中」按数组顺序判定：`ReferenceWorkflowSelect` 勾选时总把新项追加到
 * 末尾，因此冲突项中下标最大的一条即用户刚选的那条。目录里无法识别的路径
 * （旧后端 / 尚未加载）不参与判定，避免误伤。
 */
export function resolveExtraKindConflict(
  selection: readonly string[],
  workflows: readonly StudioWorkflowOption[],
): ExtraKindConflictResolution {
  const conflicting: Array<{ path: string; kind: StudioExtraKind }> = []
  for (const path of selection) {
    const workflow = workflows.find((item) => item.path === path)
    const kind = workflow?.extraKind ?? ''
    if (kind === 'person_b' || kind === 'hair') conflicting.push({ path, kind })
  }

  const hasPersonB = conflicting.some((item) => item.kind === 'person_b')
  const hasHair = conflicting.some((item) => item.kind === 'hair')
  if (!hasPersonB || !hasHair) {
    return { kind: null, kept: [...selection], removed: [] }
  }

  // 数组末尾 = 最近勾选；同语义的多条不算冲突，只移除另一种语义。
  const latest = conflicting[conflicting.length - 1]
  const removed = conflicting
    .filter((item) => item.kind !== latest.kind)
    .map((item) => item.path)
  const removedSet = new Set(removed)
  return {
    kind: latest.kind,
    kept: selection.filter((path) => !removedSet.has(path)),
    removed,
  }
}

/** 工作流目录响应。 */
export interface StudioWorkflowCatalog {
  workflows: StudioWorkflowOption[]
  default: string
}

/** 三槽当前选择（单组提交时的单值快照）。 */
export interface RecipeSlots {
  portrait: PortraitItem | null
  costume: CostumeItem | null
  pose: PoseItem | null
}

/** 各槽条目数（用于组合数计算）。 */
export interface RecipeSlotCounts {
  portrait: number
  costume: number
  pose: number
}

/** 提交体构造参数。 */
export interface RecipeRequestOptions {
  style: RecipeStyle
  promptSuffix: string
  /** 第 4 张上传图的后端路径；空串表示不带第 4 张 */
  extraPath: string
  /** 第 4 张库条目 id；与 `extraPath` 二选一。 */
  extraId?: string
  /** 第 4 张库标识（当前仅 hair）。 */
  extraLibrary?: string
  /** 第 4 张文字补充；空串不发送，有文本无图也绝不发送。 */
  extraText?: string
  /** 双人姿势的人物 B 文字设定；只在选中 composition=pair 姿势时发送。 */
  personBText?: string
  /**
   * v1.5：当前组的 B 变体（面部/身材、服饰、自由文字）。
   *
   * 批量时每组带自己的变体；单组 / 预览传当前激活变体。非空时优先于
   * `personBText` / `personBPortraitText` / `personBCostumeText`。
   */
  personBVariant?: RecipePersonBVariant | null
  /** 旧调用方直接给 B 面部/身材文本（无变体时使用）。 */
  personBPortraitText?: string
  /** 旧调用方直接给 B 服饰文本（无变体时使用）。 */
  personBCostumeText?: string
  /** 所选工作流路径 / 文件名；空串不发送（后端用默认工作流）。 */
  workflow?: string
  /** 画质档位；空串不发送。 */
  quality?: string
  /** 输出比例；空串不发送。 */
  aspectRatio?: string
  /** 横竖方向；空串不发送。 */
  orientation?: 'portrait' | 'landscape' | ''
  /** 体态模式；缺省 `costume`（与既有行为一致，总是随提交体发送）。 */
  bodyMode?: RecipeBodyMode
  seed?: number
  seedMode?: 'fixed' | 'random'
  /** 八类文本补充碎片（方案 §4.1）；缺省 = 不发送任何 `*_text` 字段。 */
  textFragments?: RecipeTextFragments
  /**
   * 三槽模式（P2 替代态，方案 §4.4）。
   *
   * - `image`：发送该槽 `*_id` / `*_path`（有碎片时文本作为补充一并发送）；
   * - `text`：**不发送**图片字段，只发送该槽 `*_text`；
   * - `empty`：两者都不发送。
   *
   * 缺省时按「该槽是否有条目」回退为 image / empty，保持 P1 调用方行为不变。
   */
  slotModes?: RecipeSlotModes
  /**
   * P4 跨源补充开关；缺省全关。
   *
   * 只有 `mode === 'image'` 且该槽开关为 true 时，文本才随图片发送并带
   * `*_supplement=true`；text 模式仍只走替代，empty 模式两者都不发。
   */
  supplementFlags?: RecipeSupplementFlags
  /** 用户手填负向；空串不发送。 */
  negativePrompt?: string
  /**
   * P3 手动改写：非空 = 按原文提交（方案 §14.3）。
   *
   * 设置后**不再发送**三槽文本 / 修饰层 / 追加要求，只发 `prompt_override`；
   * 图片槽、工作流、种子、`body_mode`、负向仍照常发送。
   */
  promptOverride?: string
}

/** 批量输入：三槽多选 + 工作流多选 + 尺寸档位多选 + 槽位模式 / 文本。 */
export interface RecipeBatchInput {
  portrait: readonly PortraitItem[]
  costume: readonly CostumeItem[]
  pose: readonly PoseItem[]
  /**
   * 已选工作流路径（有序、去重）。
   *
   * 空数组按 **1 条默认工作流**计（不把维度乘成 0）；路径本身为空串时
   * 提交体不发送 `workflow`，由后端使用默认工作流。
   */
  workflows: readonly string[]
  qualities: readonly string[]
  ratios: readonly string[]
  qualityEnabled: boolean
  orientationEnabled: boolean
  baseSeed: number
  /** 三槽模式；缺省 = 全 image（旧调用方行为不变）。 */
  slotModes?: RecipeSlotModes
  /** 三槽编译后的文本（供矩阵组键 / 组标签使用）；缺省 = 全空。 */
  slotTexts?: RecipeSlotTexts
  /**
   * v1.5：人物 B 变体。非空时与 A 人像按序号 1:1 配对（不乘成 A×B 笛卡尔积）；
   * 空数组 = 不启用变体，组合口径与旧版本逐字一致。
   */
  personBVariants?: readonly RecipePersonBVariant[]
}

/** 一个笛卡尔积组合（= 一次 POST / 一个独立 job）。 */
export interface RecipeBatchGroup {
  /** 组下标（从 0 开始），种子 = baseSeed + index。 */
  index: number
  slots: RecipeSlots
  /** 本组要提交的工作流路径；空串表示本轮不发送 `workflow`（后端默认）。 */
  workflow: string
  /** 空串表示本轮不发送 quality。 */
  quality: string
  /** 空串表示本轮不发送 aspect_ratio。 */
  aspectRatio: string
  /** 空串表示本轮不发送 orientation；否则由比例推导。 */
  orientation: 'portrait' | 'landscape' | ''
  seed: number
  /**
   * 本组的槽位模式（P2）。
   *
   * 文本 / 空槽在组合阶段已折叠为 null，但要保留模式供提交体判断「发图还是发文本」。
   * 旧批次对象可能没有该字段，读取方需回退为全 image。
   */
  slotModes?: RecipeSlotModes
  /** 本组的三槽编译文本；用于矩阵组键与组标签。 */
  slotTexts?: RecipeSlotTexts
  /**
   * v1.5：本组使用的人物 B 变体；`null` = 未启用变体（旧组合口径）。
   * 与 `slots.portrait` 按组序号一一对应。
   */
  personBVariant?: RecipePersonBVariant | null
}

/** 提交前降级确认框数据。 */
export interface WorkflowDowngradePrompt {
  message: string
  /** 非空槽数 M（含第 4 张）。 */
  slotCount: number
  /** 当前工作流 input_count N。 */
  inputCount: number
  /** `input_count <= M` 的候选工作流（不含当前项）。 */
  candidates: StudioWorkflowOption[]
  /**
   * 不可提交的具体原因（后端探测给出，例如「该工作流有 3 个输入且无法裁剪到 2 个」）。
   *
   * 空串 = 探测本身没结论（网络失败 / 旧后端），此时框内保留「仍用当前工作流提交」。
   */
  blockedReason: string
}

/** 提交阶段的错误：保留 HTTP 状态码与后端 `detail`。 */
export class RecipeSubmitError extends Error {
  readonly status: number
  readonly detail: string

  constructor(message: string, status: number, detail: string) {
    super(message)
    this.name = 'RecipeSubmitError'
    this.status = status
    this.detail = detail
  }
}

/** 轮询超时（与普通网络错误区分，文案不同）。 */
export class RecipeTimeoutError extends Error {
  readonly jobId: number

  constructor(jobId: number, timeoutMs: number) {
    super(`等待出图结果超时（${Math.round(timeoutMs / 60000)} 分钟）`)
    this.name = 'RecipeTimeoutError'
    this.jobId = jobId
  }
}

// ---------------------------------------------------------------------------
// 纯函数（可直接单测）
// ---------------------------------------------------------------------------

/** 画风归一：只有 `none` 保留，其余（含旧 12 条预设）一律 realistic。 */
export function normalizeRecipeStyle(value: unknown): RecipeStyle {
  return value === 'none' ? 'none' : 'realistic'
}

/** 服装槽库名归一：只允许 `costume` / `costume-anime`，缺省现实库。 */
export function costumeLibraryOf(item: CostumeItem | null): RecipeCostumeLibrary {
  return item?.library === 'costume-anime' ? 'costume-anime' : 'costume'
}

/**
 * 构造单组提交体。
 *
 * 空槽不发送对应字段（后端按「未提供」裁掉该图位）；第 4 张只接受 uploads
 * 路径。`quality` / `aspect_ratio` / `orientation` 只有非空才发送，调用方
 * 负责在 `caps` 不支持时不要传值 —— 这样 Qwen 系永远发不出用不上的参数。
 */
export function buildRecipeRequest(
  slots: RecipeSlots,
  options: RecipeRequestOptions,
): RecipeSubmitRequest {
  // 三槽模式：缺省按「是否有条目」回退，P1 调用方与旧单测行为不变。
  const modes: RecipeSlotModes = options.slotModes
    ? resolveSlotModes(options.slotModes)
    : {
        portrait: slots.portrait ? 'image' : 'empty',
        costume: slots.costume ? 'image' : 'empty',
        pose: slots.pose ? 'image' : 'empty',
      }
  const imageMode = (slot: RecipeSlotKey): boolean => modes[slot] === 'image'
  const supplements = resolveSupplementFlags(options.supplementFlags)

  // 服装槽用文本替代时必须按服装模式提交：body_mode=bare 会让后端写「不穿任何服装」，
  // 与 costume_text 直接冲突（方案 C3-1 的前端对齐）。
  const requestedBare = options.bodyMode === 'bare'
  const bodyMode: RecipeBodyMode =
    requestedBare && modes.costume !== 'text' ? 'bare' : 'costume'
  // 画风技术碎片与画风预设互斥（方案 §5.4）：选了碎片就强制 style='none'，
  // 页面同时禁用下拉；后端也只渲染碎片、不追加固定风格段。
  const style: RecipeStyle = hasStyleFragment(options.textFragments)
    ? 'none'
    : normalizeRecipeStyle(options.style)
  // P3 手动改写（方案 §14.3）：非空 = 原文提交，不再二次编译。
  const promptOverride = options.promptOverride?.trim() ?? ''
  const request: RecipeSubmitRequest = {
    costume_library: costumeLibraryOf(slots.costume),
    body_mode: bodyMode,
    style,
    seed: options.seed ?? DEFAULT_RECIPE_SEED,
    seed_mode: options.seedMode ?? 'fixed',
  }
  if (promptOverride) {
    request.prompt_override = promptOverride
  } else {
    // 追加要求（prompt_suffix）只参与自动编译；手动模式按原文提交，不再发它。
    request.prompt_suffix = options.promptSuffix.trim()
  }

  // 本地上传图（`upload:` 伪条目）发 `*_path`，库条目发 `*_id`：后端二选一。
  // 只有 image 模式才发送图片字段；text 模式即使还有残留图片也不发送。
  const portraitUpload = uploadPathOf(slots.portrait)
  if (slots.portrait && imageMode('portrait')) {
    if (portraitUpload) request.portrait_path = portraitUpload
    else request.portrait_id = slots.portrait.id
  }
  // 素体模式后端明确拒绝「同时带服装」：这里做最后一道防御，防止槽位清空竞态。
  if (slots.costume && bodyMode !== 'bare' && imageMode('costume')) {
    const costumeUpload = uploadPathOf(slots.costume)
    if (costumeUpload) request.costume_path = costumeUpload
    else request.costume_id = slots.costume.id
  }
  const poseUpload = uploadPathOf(slots.pose)
  if (slots.pose && imageMode('pose')) {
    if (poseUpload) request.pose_path = poseUpload
    else request.pose_id = slots.pose.id
  }

  const extra = options.extraPath.trim()
  if (extra) {
    request.extra_path = extra
  } else {
    const extraId = options.extraId?.trim()
    if (extraId) {
      request.extra_id = extraId
      request.extra_library = options.extraLibrary?.trim() || ''
    }
  }

  // 第 4 槽文字补充：只随图片一起发送；手动改写（prompt_override）不参与。
  const extraText = options.extraText?.trim() ?? ''
  if (
    !promptOverride &&
    extraText &&
    (request.extra_path || request.extra_id)
  ) {
    request.extra_text = extraText
  }

  const workflow = options.workflow?.trim()
  if (workflow) request.workflow = workflow

  // v1.5：B 变体优先；没有变体时回退到旧调用方的三个独立字段。
  // 三部分都只在双人姿势下由调用方传入，单人姿势这里自然为空。
  const variantCompiled = compilePersonBVariant(options.personBVariant ?? null)
  const personBPortraitText =
    variantCompiled.portraitText || (options.personBPortraitText?.trim() ?? '')
  const personBCostumeText =
    variantCompiled.costumeText || (options.personBCostumeText?.trim() ?? '')
  const personBText = variantCompiled.freeText || (options.personBText?.trim() ?? '')
  if (personBPortraitText) request.person_b_portrait_text = personBPortraitText
  if (personBCostumeText) request.person_b_costume_text = personBCostumeText
  if (personBText) request.person_b_text = personBText

  const quality = options.quality?.trim()
  if (quality) request.quality = quality

  const ratio = options.aspectRatio?.trim()
  if (ratio) request.aspect_ratio = ratio

  if (options.orientation) request.orientation = options.orientation

  // 三槽文本按「本次真正生效」口径发送（P4）：
  // - text 模式 → 替代（发 *_text，不发 flag）；
  // - image 模式 + supplement=true → 补充（发 *_text + *_supplement=true）；
  // - image 模式 + supplement=false / empty → 一律不发。
  // P3 手动改写：三槽文本 / 修饰层一律不发送 —— 用户改的是编译后的最终原文，
  // 再发碎片会让后端二次改写；负向只保留用户填写内容。
  if (!promptOverride) {
    const compiled = compileRecipeTextFragments(options.textFragments)
    if (
      compiled.portraitText &&
      isSlotTextActive('portrait', modes.portrait, supplements)
    ) {
      request.portrait_text = compiled.portraitText
      if (modes.portrait === 'image') request.portrait_supplement = true
    }
    if (
      compiled.costumeText &&
      isSlotTextActive('costume', modes.costume, supplements)
    ) {
      request.costume_text = compiled.costumeText
      if (modes.costume === 'image') request.costume_supplement = true
    }
    if (compiled.poseText && isSlotTextActive('pose', modes.pose, supplements)) {
      request.pose_text = compiled.poseText
      if (modes.pose === 'image') request.pose_supplement = true
    }
    if (compiled.modifierFragments) request.modifier_fragments = compiled.modifierFragments
  }

  const negativePrompt = options.negativePrompt?.trim()
  if (negativePrompt) request.negative_prompt = negativePrompt

  return request
}

/**
 * 素体模式下的服装组合维度：`bare` 一律为空。
 *
 * 后端规定 `body_mode='bare'` 与服装同时出现会 400；在组合阶段就裁掉服装维度，
 * 不依赖「UI 已清空服装槽」的时序（契约 C-REF-BODY-MODE@1）。
 */
export function costumeDimensionForBodyMode(
  costume: readonly CostumeItem[],
  bodyMode: RecipeBodyMode,
): readonly CostumeItem[] {
  return bodyMode === 'bare' ? [] : costume
}

/**
 * 槽位组合数：三个维度各自「空 / 文本 → 1 种，image 有图 → 条目数种」。
 *
 * 三槽都没有可提交内容（image 无图且非 text）时返回 0 —— 这不是「1 种空组合」，
 * 而是后端会拒绝的 M==0。
 *
 * `slotModes` 缺省 = 全 image（旧口径）；text 模式即使 items 非空也只算 1 维。
 */
export function countSlotCombinations(
  counts: RecipeSlotCounts,
  slotModes: RecipeSlotModes = createImageSlotModes(),
  personBVariantCount = 0,
): number {
  const modes = resolveSlotModes(slotModes)
  const hasContent = (['portrait', 'costume', 'pose'] as const).some((slot) =>
    modes[slot] === 'text' ? true : modes[slot] === 'image' && counts[slot] > 0,
  )
  if (!hasContent) return 0

  const variants = Math.max(0, Math.trunc(personBVariantCount || 0))
  return (['portrait', 'costume', 'pose'] as const).reduce((total, slot) => {
    const imageCount = modes[slot] === 'image' ? counts[slot] : 0
    // v1.5：B 变体与 A 人像 1:1 配对 → 人像维度取较长一侧的长度，
    // 不做 A × B；其余槽位口径不变。
    const dimension =
      slot === 'portrait' && variants > 0
        ? Math.max(1, imageCount, variants)
        : Math.max(1, imageCount)
    return total * dimension
  }, 1)
}

/**
 * 全组合数 = 槽位组合数 × 选中工作流数 × 画质档数 × 比例数。
 *
 * 尺寸维度传 0 表示「该能力不可用 / 未选择」，按 1 计；工作流维度同样
 * 至少按 1 计（未选工作流时回落默认项，不能把 total 乘成 0）。
 */
export function countBatchTotal(
  counts: RecipeSlotCounts,
  qualityCount: number,
  ratioCount: number,
  workflowCount = 1,
  slotModes: RecipeSlotModes = createImageSlotModes(),
  personBVariantCount = 0,
): number {
  const combos = countSlotCombinations(counts, slotModes, personBVariantCount)
  if (combos === 0) return 0
  return (
    combos *
    Math.max(1, workflowCount) *
    Math.max(1, qualityCount) *
    Math.max(1, ratioCount)
  )
}

/** 是否超过全组合上限。 */
export function exceedsBatchLimit(total: number): boolean {
  return total > MAX_BATCH_RECIPES
}

/**
 * 超限文案（页面按钮禁用提示，契约 C-REF-TOTAL@2）。
 *
 * 逐字含「当前 N / 上限 100」与「减少工作流、槽位或尺寸档数」，便于 E2E 断言。
 */
export function describeBatchLimit(total: number): string {
  return `当前 ${total} / 上限 ${MAX_BATCH_RECIPES}，请减少工作流、槽位或尺寸档数`
}

/** 比例 → 横竖；1:1 按竖版（与项目默认 `portrait` 一致）。 */
export function orientationForRatio(ratio: string): 'portrait' | 'landscape' {
  const [width, height] = ratio.split(':').map((part) => Number(part))
  if (!Number.isFinite(width) || !Number.isFinite(height) || height <= 0) return 'portrait'
  return width > height ? 'landscape' : 'portrait'
}

/**
 * 三槽多选 → 单值槽位组合（空槽 / 文本槽维度用 null 占位，计数为 1）。
 *
 * `slotModes` 缺省 = 全 image（旧口径）。text / empty 模式的槽即使还有残留图片
 * 也折叠成 null：text 模式不提交图片（方案 §4.4），残留图片只用于「改回图片」。
 */
export function buildSlotCombinations(
  portrait: readonly PortraitItem[],
  costume: readonly CostumeItem[],
  pose: readonly PoseItem[],
  slotModes: RecipeSlotModes = createImageSlotModes(),
): RecipeSlots[] {
  const modes = resolveSlotModes(slotModes)
  const imageDim = <T>(items: readonly T[], slot: RecipeSlotKey): (T | null)[] =>
    modes[slot] === 'image' && items.length ? [...items] : [null]

  const portraitDim = imageDim(portrait, 'portrait')
  const costumeDim = imageDim(costume, 'costume')
  const poseDim = imageDim(pose, 'pose')

  const combos: RecipeSlots[] = []
  for (const portraitItem of portraitDim) {
    for (const costumeItem of costumeDim) {
      for (const poseItem of poseDim) {
        combos.push({ portrait: portraitItem, costume: costumeItem, pose: poseItem })
      }
    }
  }
  return combos
}

/** 一对「A 人像 + B 变体」组合；`personBVariant=null` 表示未启用变体。 */
export interface RecipePairCombination {
  slots: RecipeSlots
  personBVariant: RecipePersonBVariant | null
}

/**
 * A 人像 × B 变体 **按序号 1:1 配对**（v1.5），不做 A×B 笛卡尔积。
 *
 * 两侧数量不等时，较短一侧复用最后一项：既不丢弃用户已选的人像 / 变体，
 * 也不会把组合数乘成两边长度的乘积。人像槽为 text / empty 时按 `null` 配对。
 */
export function buildPairSlotCombinations(
  portrait: readonly PortraitItem[],
  costume: readonly CostumeItem[],
  pose: readonly PoseItem[],
  slotModes: RecipeSlotModes,
  variants: readonly RecipePersonBVariant[],
): RecipePairCombination[] {
  const modes = resolveSlotModes(slotModes)
  const imageDim = <T>(items: readonly T[], slot: RecipeSlotKey): (T | null)[] =>
    modes[slot] === 'image' && items.length ? [...items] : [null]
  const costumeDim = imageDim(costume, 'costume')
  const poseDim = imageDim(pose, 'pose')
  const portraitDim: (PortraitItem | null)[] =
    modes.portrait === 'image' && portrait.length ? [...portrait] : []
  const variantDim = [...variants]
  const pairCount = Math.max(portraitDim.length, variantDim.length)
  const pick = <T>(list: readonly T[], index: number): T | null =>
    list.length ? list[Math.min(index, list.length - 1)]! : null

  const combos: RecipePairCombination[] = []
  for (let pairIndex = 0; pairIndex < pairCount; pairIndex += 1) {
    const portraitItem = pick(portraitDim, pairIndex)
    const variant = pick(variantDim, pairIndex)
    for (const costumeItem of costumeDim) {
      for (const poseItem of poseDim) {
        combos.push({
          slots: { portrait: portraitItem, costume: costumeItem, pose: poseItem },
          personBVariant: variant,
        })
      }
    }
  }
  return combos
}

/**
 * 生成四维笛卡尔积分组（= 前端要逐组 POST 的请求清单）。
 *
 * 顺序固定：槽位组合 → 工作流 → 画质 → 比例；第 i 组种子 = baseSeed + i。
 * 工作流维度为空时折叠为 1 条空路径（后端默认工作流），绝不乘成 0；
 * caps 不支持时尺寸维度折叠为「不发参数」（空串），计数仍为 1。
 *
 * P2：每组带上槽位模式与三槽文本，供提交体 / 矩阵组键使用（同一批内共享一份）。
 * v1.5：有 B 变体时，人像维度改为「A 人像 × B 变体 1:1 配对」。
 */
export function buildBatchGroups(input: RecipeBatchInput): RecipeBatchGroup[] {
  const slotModes = resolveSlotModes(input.slotModes)
  const slotTexts: RecipeSlotTexts = {
    portrait: input.slotTexts?.portrait ?? '',
    costume: input.slotTexts?.costume ?? '',
    pose: input.slotTexts?.pose ?? '',
  }
  const variants = input.personBVariants ?? []
  const pairCombos: RecipePairCombination[] =
    variants.length > 0
      ? buildPairSlotCombinations(
          input.portrait,
          input.costume,
          input.pose,
          slotModes,
          variants,
        )
      : buildSlotCombinations(
          input.portrait,
          input.costume,
          input.pose,
          slotModes,
        ).map((slots) => ({ slots, personBVariant: null }))
  const workflowDim = input.workflows.length ? [...input.workflows] : ['']
  const qualityDim =
    input.qualityEnabled && input.qualities.length ? [...input.qualities] : ['']
  const ratioDim = input.orientationEnabled && input.ratios.length ? [...input.ratios] : ['']
  const baseSeed = Math.max(0, Math.trunc(Number(input.baseSeed) || DEFAULT_RECIPE_SEED))

  const groups: RecipeBatchGroup[] = []
  let index = 0
  for (const combo of pairCombos) {
    for (const workflow of workflowDim) {
      for (const quality of qualityDim) {
        for (const ratio of ratioDim) {
          groups.push({
            index,
            slots: combo.slots,
            workflow,
            quality,
            aspectRatio: ratio,
            orientation: ratio ? orientationForRatio(ratio) : '',
            seed: baseSeed + index,
            slotModes: { ...slotModes },
            slotTexts: { ...slotTexts },
            // v1.5：本组自己的 B 变体（旧口径恒为 null）
            personBVariant: combo.personBVariant,
          })
          index += 1
        }
      }
    }
  }
  return groups
}

// ---------------------------------------------------------------------------
// 工作流角色适用性（契约 C-REF-WF-SLOTS@1）
// ---------------------------------------------------------------------------

/**
 * 解析后端 `slots` 字段（三态，见 {@link StudioWorkflowOption.slots}）。
 *
 * - `undefined` / 字段缺失：能力未知 → 返回 `undefined`，调用方不判定（旧后端宽松）；
 * - 数组为空 / 全部非法：角色不可识别 → 返回 `[]`，调用方据此置灰禁用；
 * - 非数组脏数据（null / 字符串 / 数字）：同样按不可识别返回 `[]`
 *   —— **只有 `undefined` 才宽松**，异常数据不能放行。
 *
 * 合法角色只保留四个并去重。
 */
export function parseWorkflowSlots(raw: unknown): StudioWorkflowSlot[] | undefined {
  if (raw === undefined) return undefined
  if (!Array.isArray(raw)) return []

  const valid = new Set<string>(STUDIO_WORKFLOW_SLOTS)
  const slots: StudioWorkflowSlot[] = []
  for (const value of raw) {
    if (typeof value !== 'string' || !valid.has(value)) continue
    const slot = value as StudioWorkflowSlot
    if (!slots.includes(slot)) slots.push(slot)
  }
  return slots
}

/** 工作流不适用原因类型：缺具体角色输入 / 角色整体不可识别。 */
export type WorkflowUnavailableKind = 'missing' | 'unrecognized'

/** 适用性评估结果；`kind` / `role` 同时为 null 表示可用。 */
export interface WorkflowApplicability {
  kind: WorkflowUnavailableKind | null
  role: StudioWorkflowSlot | null
}

/**
 * 评估工作流对当前已选槽位集合是否适用。
 *
 * - 空槽位不参与判定（调用方只传非空槽位角色）；
 * - `slots === undefined`：字段缺失（旧后端）→ 适用，不误伤；
 * - `slots === []`：角色不可识别 → 对所有非空槽位都不适用（返回第一个已选角色）；
 * - 非空：缺少任一已选角色即不适用（返回第一个缺的角色）。
 */
export function evaluateWorkflowApplicability(
  workflow: Pick<StudioWorkflowOption, 'slots'>,
  selectedRoles: readonly StudioWorkflowSlot[],
): WorkflowApplicability {
  if (workflow.slots === undefined) return { kind: null, role: null }
  if (!selectedRoles.length) return { kind: null, role: null }

  const slots = workflow.slots
  if (slots.length === 0) {
    return { kind: 'unrecognized', role: selectedRoles[0] }
  }
  for (const role of selectedRoles) {
    if (!slots.includes(role)) return { kind: 'missing', role }
  }
  return { kind: null, role: null }
}

/** 兼容入口：只取「第一个不适用的角色」，适用时返回 null。 */
export function workflowInapplicableRole(
  workflow: Pick<StudioWorkflowOption, 'slots'>,
  selectedRoles: readonly StudioWorkflowSlot[],
): StudioWorkflowSlot | null {
  return evaluateWorkflowApplicability(workflow, selectedRoles).role
}

/** 缺角色文案（`missing` 场景）。 */
export function describeWorkflowInapplicable(
  role: StudioWorkflowSlot,
  workflowName = '',
): string {
  const label = WORKFLOW_SLOT_LABELS[role] ?? role
  const prefix = workflowName ? `工作流「${workflowDisplayName(workflowName)}」` : '当前工作流'
  return `${prefix}缺少${label}输入，不适用于当前已选${label}`
}

/**
 * 不可用原因文案（下拉 / toast / 提交错误共用）。
 *
 * - `missing`：`工作流「X」缺少人像输入，不适用于当前已选人像`
 * - `unrecognized`：`该工作流的参考图节点无法识别角色（可能是 UI 格式工作流），不适用于当前已选人像`
 *   （此时不拼工作流名，按验收给定文案逐字输出）
 */
export function describeWorkflowUnavailable(
  kind: WorkflowUnavailableKind,
  role: StudioWorkflowSlot,
  workflowName = '',
): string {
  if (kind === 'unrecognized') {
    const label = WORKFLOW_SLOT_LABELS[role] ?? role
    return `该工作流的参考图节点无法识别角色（可能是 UI 格式工作流），不适用于当前已选${label}`
  }
  return describeWorkflowInapplicable(role, workflowName)
}

/** 下拉项原因：'' 表示适用（可直接勾选）。 */
export function describeWorkflowUnavailableFor(
  workflow: Pick<StudioWorkflowOption, 'slots' | 'name'>,
  selectedRoles: readonly StudioWorkflowSlot[],
): string {
  const { kind, role } = evaluateWorkflowApplicability(workflow, selectedRoles)
  if (!kind || !role) return ''
  return describeWorkflowUnavailable(kind, role, workflow.name)
}

/**
 * 预览前置校验的三句式文案（现象 / 原因 / 下一步）。
 *
 * 命中后前端**不发** dry-run 请求，直接展示这段文案，避免用户看到后端 400。
 */
export function describePreviewWorkflowSkip(
  role: StudioWorkflowSlot,
  workflowName = '',
  kind: WorkflowUnavailableKind = 'missing',
): string {
  return (
    `提示词预览已跳过。原因：${describeWorkflowUnavailable(kind, role, workflowName)}。` +
    '下一步：改选支持该槽位的工作流，或清空对应槽位后重新预览。'
  )
}

/**
 * 按新的槽位角色集合裁剪已选工作流（收紧点 2）。
 *
 * - 仍然适用的工作流**必须保持选中**；"只换同一槽位的另一张图"时角色集合没变，
 *   调用方根本不会产生取消；
 * - 只移除**当前已不适用**的项，并带回中文原因，供页面 toast 提示（不静默）；
 * - 目录中已不存在的路径直接剔除但不产生原因（目录失效由 `loadStudioWorkflows` 处理）。
 */
export interface WorkflowSelectionPrune {
  kept: string[]
  /** path + 中文原因；目录中已消失的项原因为空串。 */
  removed: Array<{ path: string; reason: string }>
}

export function pruneInapplicableWorkflowSelection(
  selection: readonly string[],
  workflows: readonly StudioWorkflowOption[],
  selectedRoles: readonly StudioWorkflowSlot[],
): WorkflowSelectionPrune {
  const kept: string[] = []
  const removed: Array<{ path: string; reason: string }> = []

  for (const path of selection) {
    const workflow = workflows.find((item) => item.path === path)
    if (!workflow) {
      removed.push({ path, reason: '' })
      continue
    }
    const reason = describeWorkflowUnavailableFor(workflow, selectedRoles)
    if (!reason) {
      kept.push(path)
      continue
    }
    removed.push({ path, reason })
  }

  return { kept, removed }
}

// ---------------------------------------------------------------------------
// 工作流多选的会话级记忆（sessionStorage，契约 C-REF-WF-SLOTS@1 的本地补充）
// ---------------------------------------------------------------------------

/** `sessionStorage[WORKFLOW_SELECTION_SESSION_KEY]` 里的数据结构。 */
export interface WorkflowSelectionSessionSnapshot {
  workflows: string[]
}

/**
 * 工作流路径归一：去首尾空白、丢弃空串、保序去重。
 *
 * 初始化、写入与恢复共用同一口径，避免 sessionStorage 里出现脏数据或重复项。
 */
export function normalizeWorkflowSelectionPaths(paths: readonly unknown[]): string[] {
  const seen = new Set<string>()
  const normalized: string[] = []
  for (const value of paths) {
    if (typeof value !== 'string') continue
    const path = value.trim()
    if (!path || seen.has(path)) continue
    seen.add(path)
    normalized.push(path)
  }
  return normalized
}

/** 安全获取 sessionStorage：隐私模式 / 非浏览器环境下访问本身也可能抛错。 */
function getSessionStorage(): Storage | null {
  try {
    if (typeof globalThis.sessionStorage === 'undefined') return null
    return globalThis.sessionStorage
  } catch {
    return null
  }
}

/**
 * 解析 sessionStorage 原文。
 *
 * 非法 JSON / 非对象 / `workflows` 非数组一律回落空数组（绝不把脏数据带进
 * 工作流多选）；数组内的非字符串项、空白项与重复项按同一口径归一。
 */
export function parseWorkflowSelectionSession(raw: string | null | undefined): string[] {
  if (typeof raw !== 'string' || !raw.trim()) return []

  let parsed: unknown
  try {
    parsed = JSON.parse(raw) as unknown
  } catch {
    return []
  }

  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return []
  const workflows = (parsed as { workflows?: unknown }).workflows
  if (!Array.isArray(workflows)) return []
  return normalizeWorkflowSelectionPaths(workflows)
}

/**
 * 读取会话级已选工作流。
 *
 * 缺失 / 损坏 / 存储不可用一律回落空数组。取回后调用方还会用目录存在性与
 * `slots` 三态再校验一次（见 {@link pruneInapplicableWorkflowSelection}），
 * 这里只负责取回路径原文。
 *
 * `storage` 可注入，便于单测断言读写行为（默认取 `globalThis.sessionStorage`）。
 */
export function readWorkflowSelectionSession(
  storage: Storage | null = getSessionStorage(),
): string[] {
  if (!storage) return []
  try {
    return parseWorkflowSelectionSession(storage.getItem(WORKFLOW_SELECTION_SESSION_KEY))
  } catch {
    return []
  }
}

/**
 * 是否存在**有效**的会话记忆。
 *
 * 与 `readWorkflowSelectionSession` 分开：`{ workflows: [] }`（用户本会话主动
 * 清空多选）也算「存在」，初始化时不能被 `pb.reference_studio_v1.workflow`
 * 的单选回填覆盖成一条。非法 JSON / 结构不符则视为不存在。
 */
export function hasWorkflowSelectionSession(
  storage: Storage | null = getSessionStorage(),
): boolean {
  if (!storage) return false
  try {
    const raw = storage.getItem(WORKFLOW_SELECTION_SESSION_KEY)
    if (typeof raw !== 'string' || !raw.trim()) return false
    const parsed = JSON.parse(raw) as unknown
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return false
    return Array.isArray((parsed as { workflows?: unknown }).workflows)
  } catch {
    return false
  }
}

/**
 * 写入会话级已选工作流（去重、保序）。
 *
 * 空选择也写 `{ workflows: [] }`：让「本会话主动清空多选」也能被记住，
 * 不需要额外的清理代码；关闭标签页后由浏览器自然回收。
 * 写失败（隐私模式 / 配额不足）静默降级，本次会话仍按内存值工作。
 */
export function writeWorkflowSelectionSession(
  paths: readonly string[],
  storage: Storage | null = getSessionStorage(),
): void {
  if (!storage) return

  const snapshot: WorkflowSelectionSessionSnapshot = {
    workflows: normalizeWorkflowSelectionPaths(paths),
  }
  try {
    storage.setItem(WORKFLOW_SELECTION_SESSION_KEY, JSON.stringify(snapshot))
  } catch {
    /* 隐私模式 / 配额不足：静默降级 */
  }
}

/**
 * 会话恢复时「被跳过项」的三句式文案。
 *
 * 用词刻意避免「取消」：这不是用户刚做了取消操作，而是恢复会话记忆时发现
 * 目录已删除 / 与当前槽位不匹配，因此用「已跳过」描述。
 */
export function describeWorkflowSelectionRestoreNotice(reasons: readonly string[]): string {
  return (
    `本次会话恢复的已选工作流中有 ${reasons.length} 个与当前槽位不匹配，已跳过。` +
    `原因：${reasons.join('；')}。` +
    '下一步：改选支持这些槽位的工作流，或清空对应槽位后重新勾选。'
  )
}

/**
 * 切换工作流后重建画质选择：
 * - 新工作流不支持画质（options 为空）→ 清空，绝不把旧参数发出去；
 * - 保留仍然可用的档位；一个都不剩时回落到 4K / 首档。
 */
export function reconcileQualitySelection(
  selected: readonly string[],
  options: readonly QualityOption[],
): string[] {
  if (!options.length) return []
  const available = new Set(options.map((option) => option.value))
  const kept = selected.filter((value) => available.has(value))
  if (kept.length) return [...kept]
  const preferred =
    options.find((option) => option.value === '1.0x') ??
    options.find((option) => option.value === '4K') ??
    options[0]
  return preferred ? [preferred.value] : []
}

/**
 * 切换工作流后重建比例选择：
 * - 新工作流不支持横竖（ratios 为空）→ 清空；
 * - 保留仍然可用的比例；一个都不剩时回落到工作流默认比例 / 首项。
 */
export function reconcileRatioSelection(
  selected: readonly string[],
  ratios: readonly string[],
  defaultRatio: string,
): string[] {
  if (!ratios.length) return []
  const kept = selected.filter((value) => ratios.includes(value))
  if (kept.length) return [...kept]
  const preferred =
    defaultRatio && ratios.includes(defaultRatio) ? defaultRatio : ratios[0]
  return preferred ? [preferred] : []
}

/** 降级确认框文案：必须写明「切换后任务语义可能变为换衣/编辑」。 */
export function describeWorkflowDowngrade(inputCount: number, slotCount: number): string {
  return (
    `当前工作流需要 ${inputCount} 个输入，但只提供了 ${slotCount} 个非空槽位。` +
    '切换后任务语义可能变为换衣/编辑。' +
    '下一步：从下方候选工作流中切换，或取消后补齐参考图再提交。'
  )
}

/** 候选工作流：`input_count <= M` 且不含当前项（0 输入无法参与出图）。 */
export function buildWorkflowDowngradeCandidates(
  workflows: readonly StudioWorkflowOption[],
  currentPath: string,
  slotCount: number,
): StudioWorkflowOption[] {
  return workflows.filter(
    (workflow) =>
      workflow.path !== currentPath &&
      workflow.inputCount > 0 &&
      workflow.inputCount <= slotCount,
  )
}

/**
 * 限并发执行：最多 `limit` 个 worker 同时进行，返回顺序与输入一致。
 *
 * 用于「逐组 POST，并发上限 2」与轮询阶段，避免一次把后端队列打满。
 */
export async function runWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  if (!items.length) return []
  const size = Math.max(1, Math.min(Math.trunc(limit) || 1, items.length))
  const results = new Array<R>(items.length)
  let cursor = 0

  async function drain(): Promise<void> {
    while (cursor < items.length) {
      const index = cursor
      cursor += 1
      results[index] = await worker(items[index], index)
    }
  }

  await Promise.all(Array.from({ length: size }, () => drain()))
  return results
}

/** 任务状态小写归一，避免后端大小写差异导致终态判断失效。 */
function normalizedStatus(snapshot: RecipeJobSnapshot | null | undefined): string {
  return String(snapshot?.status ?? '').toLowerCase()
}

/** 任务是否处于成功终态。 */
export function isJobSucceeded(snapshot: RecipeJobSnapshot): boolean {
  return SUCCESS_JOB_STATUSES.has(normalizedStatus(snapshot))
}

/** 任务是否处于（成功或失败）终态。 */
export function isJobTerminal(snapshot: RecipeJobSnapshot): boolean {
  const status = normalizedStatus(snapshot)
  return SUCCESS_JOB_STATUSES.has(status) || FAILURE_JOB_STATUSES.has(status)
}

/** 汇总任务条目里的错误文案。 */
export function jobErrorMessages(snapshot: RecipeJobSnapshot): string[] {
  const messages: string[] = []
  for (const item of snapshot?.items ?? []) {
    const text = typeof item?.error === 'string' ? item.error.trim() : ''
    if (text) messages.push(text)
  }
  return messages
}

/**
 * 从任务快照提取结果图 URL（`/api/media/image?...`）。
 *
 * 顺序按 items / images 返回顺序，重复 URL 只保留首次；缺省 `type=output`
 * 与后端媒体端点默认值一致。绝不返回直连 ComfyUI 的地址。
 */
export function recipeJobResultUrls(snapshot: RecipeJobSnapshot): string[] {
  const urls: string[] = []
  const seen = new Set<string>()
  for (const item of snapshot?.items ?? []) {
    for (const image of item?.images ?? []) {
      if (!image?.filename) continue
      const url = viewUrl({
        filename: image.filename,
        subfolder: image.subfolder ?? '',
        img_type: image.type || 'output',
      })
      if (seen.has(url)) continue
      seen.add(url)
      urls.push(url)
    }
  }
  return urls
}

/**
 * 快照 → 进度文案。
 *
 * `total > 0` 时才计算百分比（后端批量任务）；不使用节点级百分比。
 */
export function describeJobProgress(snapshot: RecipeJobSnapshot): RecipeProgress {
  const status = normalizedStatus(snapshot)
  const total = Number(snapshot?.total) || 0
  const done = Number(snapshot?.done_count) || 0
  const percent =
    total > 0 ? Math.min(100, Math.max(0, Math.round((done / total) * 100))) : null
  const counts = total > 0 ? `（已完成 ${done}/${total}）` : ''

  if (SUCCESS_JOB_STATUSES.has(status)) {
    return { stage: 'done', message: `任务已完成，正在获取生成结果…${counts}`, percent }
  }
  if (FAILURE_JOB_STATUSES.has(status)) {
    return { stage: 'done', message: `任务已结束（${status}），正在确认结果…${counts}`, percent }
  }
  if (status === 'pending' || status === 'queued' || status === 'waiting') {
    return { stage: 'queued', message: `任务已提交，正在排队…${counts}`, percent }
  }
  return { stage: 'running', message: `正在出图…${counts}`, percent }
}

/**
 * 工作流默认选中项。
 *
 * 优先后端 `default`（且必须在列表里），缺失时回落列表第一条；
 * 列表为空返回空串（页面据此禁用「生成角色图」）。
 */
export function resolveInitialWorkflowPath(
  workflows: readonly StudioWorkflowOption[],
  defaultPath: string,
): string {
  if (!workflows.length) return ''
  if (defaultPath && workflows.some((workflow) => workflow.path === defaultPath)) {
    return defaultPath
  }
  return workflows[0].path
}

/** 工作流展示名：去掉 `.json` / `.api.json` 后缀。 */
export function workflowDisplayName(name: string): string {
  return name.replace(/\.api\.json$/i, '').replace(/\.json$/i, '')
}

/** 后端任务失败终态 → 三句式中文错误。 */
export function describeJobFailure(snapshot: RecipeJobSnapshot): string {
  const messages = jobErrorMessages(snapshot)
  const reason = messages.length
    ? messages.join('；')
    : `后端任务状态为 ${normalizedStatus(snapshot) || '未知'}`
  return `生成失败。原因：${reason}。下一步：点击「重试」重新提交，或前往任务中心查看任务 #${snapshot.id} 的详细日志。`
}

/** 提交失败 → 三句式中文错误（现象 + 原因 + 下一步），始终带后端原文。 */
export function describeSubmitFailure(cause: unknown): string {
  if (cause instanceof RecipeSubmitError) {
    const detail = cause.detail
    if (cause.status === 0) {
      return '提交出图任务失败。原因：无法连接后端（网络中断或服务未启动）。下一步：确认后端服务在线后点击「重试」。'
    }
    if (detail.includes('请至少选择一个参考图')) {
      return `提交被拒绝。原因：${detail}。下一步：从人像 / 服装 / 姿势任一库选择参考图，或上传第 4 张后再提交。`
    }
    if (/只有\s*\d+\s*个输入/.test(detail)) {
      return `提交被拒绝。原因：${detail}。下一步：减少本次提交的参考图数量，或切换到输入数更多的工作流后重试。`
    }
    if (detail.includes('无法裁剪')) {
      return `提交被拒绝。原因：${detail}。下一步：按提示补齐参考图，或切换到输入数更少的工作流后重试。`
    }
    if (detail.includes('不属于合成台可用范围')) {
      return `提交被拒绝。原因：${detail}。下一步：在合成台工作流下拉中重新选择一个可用工作流后重试。`
    }
    if (/uploads|上传目录|上传的/i.test(detail)) {
      return `第 4 张参考图被后端拒绝。原因：${detail}（后端只接受通过上传接口落盘的图片）。下一步：用页面上的「添加附加参考图」重新上传后再提交，不要填本地磁盘路径。`
    }
    if (detail.includes('缺少')) {
      return `提交被拒绝。原因：${detail}。下一步：补齐对应槽位的参考图后再提交。`
    }
    if (detail.includes('服装库')) {
      return `提交被拒绝。原因：${detail}。下一步：重新选择服装槽参考图（服装库只支持 costume 与 costume-anime）。`
    }
    if (detail.includes('画风')) {
      return `提交被拒绝。原因：${detail}。下一步：把画风预设切到「无预设」或「写实人像写真」后重试。`
    }
    if (detail.includes('工作流')) {
      return `提交被拒绝。原因：${detail}。下一步：请检查库目录中的出图工作流文件是否齐全后重试。`
    }
    return `提交被拒绝（HTTP ${cause.status}）。原因：${detail}。下一步：按提示调整后重试；仍失败请前往任务中心查看。`
  }

  const message = cause instanceof Error ? cause.message : String(cause)
  return `提交出图任务失败。原因：${message}。下一步：确认网络与后端服务正常后点击「重试」。`
}

/** 提示词预览失败 → 三句式中文错误（现象 + 原因 + 下一步）。 */
export function describePreviewFailure(cause: unknown): string {
  if (cause instanceof RecipeSubmitError) {
    const detail = cause.detail
    if (cause.status === 0) {
      return '提示词预览失败。原因：无法连接后端（网络中断或服务未启动）。下一步：确认后端服务在线后点击「重试」。'
    }
    if (detail.includes('请至少选择一个参考图')) {
      return `提示词预览失败。原因：${detail}。下一步：从人像 / 服装 / 姿势任一库选择至少一张参考图，选择后会自动刷新预览。`
    }
    if (/只有\s*\d+\s*个输入|无法裁剪/.test(detail)) {
      return `提示词预览失败。原因：${detail}。下一步：补齐参考图，或切换到输入数更少的工作流后点击「重试」。`
    }
    return `提示词预览失败（HTTP ${cause.status}）。原因：${detail}。下一步：按提示调整后点击「重试」。`
  }

  const message = cause instanceof Error ? cause.message : String(cause)
  return `提示词预览失败。原因：${message}。下一步：确认网络与后端服务正常后点击「重试」。`
}

/** 轮询失败 → 三句式中文错误。 */
export function describePollFailure(cause: unknown, jobId: number | null): string {
  if (cause instanceof RecipeTimeoutError) {
    return `等待出图结果超过 30 分钟。原因：后端队列长时间没有返回终态。下一步：前往任务中心查看任务 #${cause.jobId}，或稍后点击「重试」。`
  }
  const message = cause instanceof Error ? cause.message : String(cause)
  const jobText = jobId ? `任务 #${jobId} ` : '任务'
  return `无法确认任务状态。原因：${message}（连续 3 次查询失败）。下一步：${jobText}可能仍在后端执行，可前往任务中心查看，或稍后点击「重试」。`
}

/** 成功终态但没有任何结果图。 */
export function describeMissingResult(snapshot: RecipeJobSnapshot): string {
  return `任务已完成但未找到结果图。原因：后端任务快照里没有可用的图片记录（任务 #${snapshot.id}）。下一步：前往任务中心查看该任务的输出，或稍后在下方历史记录中查找。`
}

// ---------------------------------------------------------------------------
