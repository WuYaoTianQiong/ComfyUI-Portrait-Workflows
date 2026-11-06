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
import { useReferenceRecipeDraft } from './useReferenceRecipeDraft'
import {
  useWorkflowCaps,
  type QualityOption,
  type WorkflowCaps,
  type WorkflowParams,
} from './useWorkflowCaps'
import type { WorkflowRow } from './useWorkflows'

// ---------------------------------------------------------------------------
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

/** 提交给后端的配方请求（字段名与后端 `RecipeRequest` 逐字一致）。 */
export interface RecipeSubmitRequest {
  portrait_id?: string
  costume_id?: string
  pose_id?: string
  costume_library?: RecipeCostumeLibrary
  extra_path?: string
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
  prompt_suffix: string
  seed: number
  seed_mode: 'fixed' | 'random'
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
  /** 后端按三槽自动组合出的提示词。 */
  prompt?: string
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
  /** 后端探测的注入能力；缺失时由 `useWorkflowCaps` 回落到乐观默认值。 */
  caps?: WorkflowCaps
  /** 画质 / 方向参数描述；用于生成真实档位与比例选项。 */
  params?: WorkflowParams
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
}

/** 批量输入：三槽多选 + 工作流多选 + 尺寸档位多选。 */
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
  const bodyMode: RecipeBodyMode = options.bodyMode === 'bare' ? 'bare' : 'costume'
  const request: RecipeSubmitRequest = {
    costume_library: costumeLibraryOf(slots.costume),
    body_mode: bodyMode,
    style: normalizeRecipeStyle(options.style),
    prompt_suffix: options.promptSuffix.trim(),
    seed: options.seed ?? DEFAULT_RECIPE_SEED,
    seed_mode: options.seedMode ?? 'fixed',
  }

  if (slots.portrait) request.portrait_id = slots.portrait.id
  // 素体模式后端明确拒绝「同时带服装」：这里做最后一道防御，防止槽位清空竞态。
  if (slots.costume && bodyMode !== 'bare') request.costume_id = slots.costume.id
  if (slots.pose) request.pose_id = slots.pose.id

  const extra = options.extraPath.trim()
  if (extra) request.extra_path = extra

  const workflow = options.workflow?.trim()
  if (workflow) request.workflow = workflow

  const quality = options.quality?.trim()
  if (quality) request.quality = quality

  const ratio = options.aspectRatio?.trim()
  if (ratio) request.aspect_ratio = ratio

  if (options.orientation) request.orientation = options.orientation

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
 * 槽位组合数：三个维度各自「空 → 1 种，非空 → 条目数种」。
 *
 * 三槽都为空时返回 0 —— 这不是「1 种空组合」，而是后端会拒绝的 M==0。
 */
export function countSlotCombinations(counts: RecipeSlotCounts): number {
  const dims = [counts.portrait, counts.costume, counts.pose]
  if (dims.every((value) => value <= 0)) return 0
  return dims.reduce((total, value) => total * Math.max(1, value), 1)
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
): number {
  const combos = countSlotCombinations(counts)
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

/** 三槽多选 → 单值槽位组合（空槽维度用 null 占位，计数为 1）。 */
export function buildSlotCombinations(
  portrait: readonly PortraitItem[],
  costume: readonly CostumeItem[],
  pose: readonly PoseItem[],
): RecipeSlots[] {
  const portraitDim: (PortraitItem | null)[] = portrait.length ? [...portrait] : [null]
  const costumeDim: (CostumeItem | null)[] = costume.length ? [...costume] : [null]
  const poseDim: (PoseItem | null)[] = pose.length ? [...pose] : [null]

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

/**
 * 生成四维笛卡尔积分组（= 前端要逐组 POST 的请求清单）。
 *
 * 顺序固定：槽位组合 → 工作流 → 画质 → 比例；第 i 组种子 = baseSeed + i。
 * 工作流维度为空时折叠为 1 条空路径（后端默认工作流），绝不乘成 0；
 * caps 不支持时尺寸维度折叠为「不发参数」（空串），计数仍为 1。
 */
export function buildBatchGroups(input: RecipeBatchInput): RecipeBatchGroup[] {
  const slotCombos = buildSlotCombinations(input.portrait, input.costume, input.pose)
  const workflowDim = input.workflows.length ? [...input.workflows] : ['']
  const qualityDim =
    input.qualityEnabled && input.qualities.length ? [...input.qualities] : ['']
  const ratioDim = input.orientationEnabled && input.ratios.length ? [...input.ratios] : ['']
  const baseSeed = Math.max(0, Math.trunc(Number(input.baseSeed) || DEFAULT_RECIPE_SEED))

  const groups: RecipeBatchGroup[] = []
  let index = 0
  for (const slots of slotCombos) {
    for (const workflow of workflowDim) {
      for (const quality of qualityDim) {
        for (const ratio of ratioDim) {
          groups.push({
            index,
            slots,
            workflow,
            quality,
            aspectRatio: ratio,
            orientation: ratio ? orientationForRatio(ratio) : '',
            seed: baseSeed + index,
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
  const preferred = options.find((option) => option.value === '4K') ?? options[0]
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
      const query = new URLSearchParams({
        filename: image.filename,
        subfolder: image.subfolder ?? '',
        type: image.type || 'output',
      })
      const url = `/api/media/image?${query.toString()}`
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
// HTTP
// ---------------------------------------------------------------------------

/** 读取后端 `{detail}`；非 JSON / 非字符串时回退 `HTTP {status}`。 */
async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body?.detail === 'string' && body.detail.trim()) return body.detail
  } catch {
    // 开发服务器未代理 /api 时会返回 HTML，按状态码处理。
  }
  return `HTTP ${response.status}`
}

/** 提交配方任务；非 2xx / 网络异常统一抛 {@link RecipeSubmitError}。 */
export async function submitRecipe(request: RecipeSubmitRequest): Promise<RecipeSubmitResponse> {
  let response: Response
  try {
    response = await fetch(RECIPE_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  } catch {
    throw new RecipeSubmitError('提交出图任务失败', 0, '网络请求失败')
  }

  if (!response.ok) {
    throw new RecipeSubmitError('提交出图任务失败', response.status, await readErrorDetail(response))
  }

  try {
    return (await response.json()) as RecipeSubmitResponse
  } catch {
    throw new RecipeSubmitError(
      '提交出图任务失败',
      response.status,
      `响应不是 JSON（HTTP ${response.status}）`,
    )
  }
}

/**
 * 只读提示词预览：同一个提交端点 + `dry_run: true`，不产生任务。
 *
 * 与正式提交**互相独立**：这里只取响应里的 `prompt`，绝不把响应当作提交结果，
 * 正式提交仍走 {@link submitRecipe}。
 */
export async function previewRecipePrompt(
  request: RecipeSubmitRequest,
): Promise<RecipePreviewResponse> {
  let response: Response
  try {
    response = await fetch(RECIPE_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...request, dry_run: true }),
    })
  } catch {
    throw new RecipeSubmitError('获取提示词预览失败', 0, '网络请求失败')
  }

  if (!response.ok) {
    throw new RecipeSubmitError(
      '获取提示词预览失败',
      response.status,
      await readErrorDetail(response),
    )
  }

  try {
    const body = (await response.json()) as RecipePreviewResponse
    if (typeof body?.prompt !== 'string') {
      throw new Error('响应缺少 prompt 字段')
    }
    return body
  } catch (cause) {
    if (cause instanceof RecipeSubmitError) throw cause
    throw new RecipeSubmitError(
      '获取提示词预览失败',
      response.status,
      '响应不是有效的 JSON，或缺少 prompt 字段',
    )
  }
}

/**
 * 提交前可裁剪探测：把「已填哪些槽」交给后端，问它空槽能不能裁掉。
 *
 * 与正式提交共用后端同一判定（`_resolve_trim_plan`），因此 `all_trimmable`
 * 为 true 时提交不会再因输入数 400。网络异常 / 非 2xx / 结构异常统一抛出，
 * 由调用方退回原来的确认框 —— 探测失败**绝不**当作可提交放行。
 */
export async function checkRecipeTrim(
  request: RecipeTrimCheckRequest,
): Promise<RecipeTrimCheckResponse> {
  let response: Response
  try {
    response = await fetch(TRIM_CHECK_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  } catch {
    throw new RecipeSubmitError('探测工作流输入数失败', 0, '网络请求失败')
  }

  if (!response.ok) {
    throw new RecipeSubmitError(
      '探测工作流输入数失败',
      response.status,
      await readErrorDetail(response),
    )
  }

  try {
    const body = (await response.json()) as RecipeTrimCheckResponse
    if (!body || !Array.isArray(body.workflows)) throw new Error('响应结构异常')
    return body
  } catch (cause) {
    if (cause instanceof RecipeSubmitError) throw cause
    throw new RecipeSubmitError(
      '探测工作流输入数失败',
      response.status,
      '响应不是有效的 JSON，或缺少 workflows 字段',
    )
  }
}

/** 查询一次任务快照；失败抛可读错误。 */
export async function fetchRecipeJob(jobId: number): Promise<RecipeJobSnapshot> {
  let response: Response
  try {
    response = await fetch(`${RECIPE_JOB_ENDPOINT}/${jobId}`)
  } catch {
    throw new Error('查询任务状态失败：网络请求失败')
  }
  if (!response.ok) {
    throw new Error(`查询任务状态失败：${await readErrorDetail(response)}`)
  }
  try {
    return (await response.json()) as RecipeJobSnapshot
  } catch {
    throw new Error(`查询任务状态失败：响应不是 JSON（HTTP ${response.status}）`)
  }
}

/** 等待 `ms` 毫秒；测试里配合 fake timers 使用。 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)))
}

/**
 * 全局请求闸门（多批次轮询共用）。
 *
 * 每个批次内部仍用 `runWithConcurrency` 限流，但多批同时轮询时真正发出的
 * `GET /api/jobs/{id}` 总数仍必须收敛到 {@link MAX_SUBMIT_CONCURRENCY}，
 * 否则「20 批 × 每组 1 个请求」会把后端打满。
 *
 * 释放时直接把槽位转交给排队者（`active` 保持不变），避免并发计数短暂回落
 * 导致新请求插队、总并发超过上限。
 */
function createRequestGate(limit: number): <T>(task: () => Promise<T>) => Promise<T> {
  const max = Math.max(1, Math.trunc(limit) || 1)
  let active = 0
  const waiting: Array<() => void> = []

  return async function runWithGate<T>(task: () => Promise<T>): Promise<T> {
    if (active >= max) {
      await new Promise<void>((resolve) => waiting.push(resolve))
    } else {
      active += 1
    }

    try {
      return await task()
    } finally {
      const next = waiting.shift()
      if (next) next()
      else active -= 1
    }
  }
}

/** 轮询 GET 的全局并发闸门（上限与提交并发一致）。 */
const pollRequestGate = createRequestGate(MAX_SUBMIT_CONCURRENCY)

/**
 * 轮询任务直到终态。
 *
 * - 默认间隔 1.5s、上限 30 分钟；
 * - 终态集合与 React `recipeClient` 完全一致；
 * - 连续 {@link MAX_CONSECUTIVE_POLL_ERRORS} 次查询失败才抛出，单次抖动继续；
 * - 超时抛 {@link RecipeTimeoutError}，由调用方渲染三句式文案。
 */
export async function pollRecipeJob(
  jobId: number,
  options: {
    intervalMs?: number
    timeoutMs?: number
    onUpdate?: (snapshot: RecipeJobSnapshot) => void
  } = {},
): Promise<RecipeJobSnapshot> {
  const intervalMs =
    options.intervalMs && options.intervalMs > 0 ? options.intervalMs : RECIPE_POLL_INTERVAL_MS
  const timeoutMs =
    options.timeoutMs && options.timeoutMs > 0 ? options.timeoutMs : RECIPE_POLL_TIMEOUT_MS
  const startedAt = Date.now()
  let consecutiveErrors = 0

  for (;;) {
    if (Date.now() - startedAt >= timeoutMs) {
      throw new RecipeTimeoutError(jobId, timeoutMs)
    }

    let snapshot: RecipeJobSnapshot
    try {
      // 多批次同时轮询时，真正发出的 GET 仍受全局闸门限制。
      snapshot = await pollRequestGate(() => fetchRecipeJob(jobId))
    } catch (error) {
      consecutiveErrors += 1
      if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) throw error
      await sleep(intervalMs)
      continue
    }

    consecutiveErrors = 0
    options.onUpdate?.(snapshot)
    if (isJobTerminal(snapshot)) return snapshot

    await sleep(intervalMs)
  }
}

// ---------------------------------------------------------------------------
// 响应解析（后端 `/api/workflows?scope=studio`）
// ---------------------------------------------------------------------------

function optionalNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) {
    return Number(value)
  }
  return null
}

/** 解析后端 caps；字段缺失时保持「可用」的乐观默认，与后端探测口径一致。 */
function parseStudioCaps(raw: unknown): WorkflowCaps | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  return {
    prompt: value.prompt !== false,
    negative: value.negative !== false,
    negative_effective: value.negative_effective !== false,
    negative_cfg: optionalNumber(value.negative_cfg),
    quality: value.quality !== false,
    orientation: value.orientation !== false,
  }
}

/** 解析后端 params；非对象时返回 undefined，交由 `useWorkflowCaps` 回落。 */
function parseStudioParams(raw: unknown): WorkflowParams | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  const qualityModes = new Set(['seedvr', 'scale', 'megapixels', 'none'])
  const orientationModes = new Set(['swap', 'knob', 'none'])
  const qualityMode =
    typeof value.quality_mode === 'string' && qualityModes.has(value.quality_mode)
      ? (value.quality_mode as WorkflowParams['quality_mode'])
      : 'none'
  const orientationMode =
    typeof value.orientation_mode === 'string' && orientationModes.has(value.orientation_mode)
      ? (value.orientation_mode as WorkflowParams['orientation_mode'])
      : 'none'
  const strings = (input: unknown): string[] =>
    Array.isArray(input) ? input.filter((item): item is string => typeof item === 'string') : []

  return {
    quality_mode: qualityMode,
    base_width: optionalNumber(value.base_width),
    base_height: optionalNumber(value.base_height),
    base_megapixels: optionalNumber(value.base_megapixels),
    mp_unit: value.mp_unit === 'mip' ? 'mip' : 'mp',
    post_scale: optionalNumber(value.post_scale) ?? 1,
    orientation_mode: orientationMode,
    aspect_ratios: strings(value.aspect_ratios),
    default_ratio: typeof value.default_ratio === 'string' ? value.default_ratio : '',
    multiple: optionalNumber(value.multiple) ?? undefined,
    quality_tiers: strings(value.quality_tiers),
    default_quality: typeof value.default_quality === 'string' ? value.default_quality : '',
  }
}

// ---------------------------------------------------------------------------
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
  const extraPath = ref('')
  const extraName = ref('')

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

  const slotCounts = computed<RecipeSlotCounts>(() => ({
    portrait: draft.portraitCount.value,
    costume: draft.costumeCount.value,
    pose: draft.poseCount.value,
  }))

  /** 非空槽位名（含第 4 张）：后端按「非空槽数 M」校验工作流输入数。 */
  const filledSlotNames = computed<string[]>(() => {
    const names: string[] = []
    if (draft.portraitCount.value > 0) names.push('人像')
    if (draft.costumeCount.value > 0) names.push('服装')
    if (draft.poseCount.value > 0) names.push('姿势')
    if (extraPath.value.trim()) names.push('第 4 张')
    return names
  })
  const activeSlotCount = computed(() => filledSlotNames.value.length)

  /** 非空槽位的**业务角色**（工作流 `slots` 适用性判定用；空槽不参与）。 */
  const filledSlotRoles = computed<StudioWorkflowSlot[]>(() => {
    const roles: StudioWorkflowSlot[] = []
    if (draft.portraitCount.value > 0) roles.push('portrait')
    if (draft.costumeCount.value > 0) roles.push('costume')
    if (draft.poseCount.value > 0) roles.push('pose')
    if (extraPath.value.trim()) roles.push('extra')
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
   * 全组合数（契约 C-REF-TOTAL@2）：
   * `槽位组合数 × 选中工作流数 × 画质档数 × 比例数`。
   *
   * 常驻展示「当前 N / 上限 100」，提交前也用它做上限判断。
   */
  const batchTotal = computed(() =>
    countBatchTotal(
      slotCounts.value,
      qualityDimension.value,
      ratioDimension.value,
      workflowDimension.value,
    ),
  )
  const batchOverLimit = computed(() => exceedsBatchLimit(batchTotal.value))
  const batchLimitMessage = computed(() =>
    batchOverLimit.value ? describeBatchLimit(batchTotal.value) : '',
  )

  /** Qwen 系（尺寸跟随参考图）：caps 既不支持画质也不支持横竖。 */
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
      activeSlotCount.value > 0 &&
      batchTotal.value > 0 &&
      !batchOverLimit.value,
  )

  // -------------------------------------------------------------------------
  // 提示词 dry-run 预览（只读，不产生任务）
  // -------------------------------------------------------------------------

  /** 后端组合出的提示词；空串表示尚未拿到有效预览。 */
  const previewPrompt = ref('')
  const previewError = ref('')
  const previewLoading = ref(false)

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
    return buildRecipeRequest(
      {
        portrait: draft.portrait.value[0] ?? null,
        costume: bodyMode.value === 'bare' ? null : (draft.costume.value[0] ?? null),
        pose: draft.pose.value[0]?.item ?? null,
      },
      {
        style: style.value,
        promptSuffix: promptSuffix.value,
        extraPath: '',
        workflow: previewWorkflow.value?.path ?? '',
        bodyMode: bodyMode.value,
        seed: baseSeed.value,
        seedMode: 'fixed',
      },
    )
  }

  /** 预览代表工作流：永远取第一条生效工作流。 */
  const previewWorkflow = computed<StudioWorkflowOption | null>(
    () => effectiveWorkflows.value[0] ?? null,
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
    const blocked = previewWorkflowSkipReason.value
    if (blocked) {
      // 前置校验命中：不发请求，直接展示现象 / 原因 / 下一步。
      previewRequestSeq += 1
      previewTimer = null
      previewPrompt.value = ''
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
      if (!previewPrompt.value) {
        previewError.value =
          '提示词预览为空。原因：后端未返回 prompt 字段。下一步：点击「重试」再次请求，仍为空请检查工作流是否支持提示词。'
      }
    } catch (cause) {
      if (seq !== previewRequestSeq) return
      previewPrompt.value = ''
      previewError.value = describePreviewFailure(cause)
    } finally {
      if (seq === previewRequestSeq) previewLoading.value = false
    }
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
   * 开启时**同时清空服装槽**：后端规定 `body_mode='bare'` 与服装同时出现会 400。
   * 关闭时只切回 `costume`，不影响其他槽位。
   */
  function setBodyMode(mode: RecipeBodyMode): void {
    if (mode === 'bare') {
      bodyMode.value = 'bare'
      if (draft.costumeCount.value > 0) draft.removeCostume()
      return
    }
    bodyMode.value = 'costume'
  }

  /** 消费后清空自动取消提示，避免同一条消息重复弹出。 */
  function clearWorkflowSelectionNotice(): void {
    workflowSelectionNotice.value = ''
  }

  /** 消费后清空自动裁剪提示，避免同一条消息重复弹出。 */
  function clearWorkflowTrimNotice(): void {
    workflowTrimNotice.value = ''
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
    extraPath.value = path
    extraName.value = name
  }

  function clearExtra(): void {
    extraPath.value = ''
    extraName.value = ''
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
    })
    batches.value.push(batch)
    syncLatestView(batch)

    const outcomes = await runWithConcurrency(
      groups,
      MAX_SUBMIT_CONCURRENCY,
      async (group): Promise<SubmitOutcome> => {
        const request = buildRecipeRequest(group.slots, {
          style: style.value,
          promptSuffix: promptSuffix.value,
          extraPath: extraPath.value,
          // 每组提交自己的工作流（契约 C-REF-TOTAL@2）；空串由后端用默认工作流。
          workflow: group.workflow,
          quality: group.quality,
          aspectRatio: group.aspectRatio,
          orientation: group.orientation,
          bodyMode: bodyMode.value,
          seed: group.seed,
          seedMode: 'fixed',
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

    const pollOutcomes = await runWithConcurrency(
      submitted,
      MAX_SUBMIT_CONCURRENCY,
      async (outcome): Promise<PollOutcome> => {
        const id = outcome.response.job_id
        try {
          const snapshot = await pollRecipeJob(id, {
            onUpdate: (next) => {
              aggregates.set(id, {
                total: Number(next.total) || 1,
                done: Number(next.done_count) || 0,
              })
              updateBatchAggregates()
              syncLatestView(batch)
            },
          })
          return { outcome, snapshot, error: null }
        } catch (error) {
          return { outcome, snapshot: null, error }
        }
      },
    )

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
    return buildBatchGroups({
      portrait: draft.portrait.value,
      // 素体模式：即使槽位有残留服装也绝不进入组合（后端 bare + 服装 = 400）。
      costume: costumeDimensionForBodyMode(draft.costume.value, bodyMode.value),
      pose: draft.pose.value.map((entry) => entry.item),
      workflows: effectiveWorkflows.value.map((item) => item.path),
      qualities: qualitySelection.value,
      ratios: ratioSelection.value,
      qualityEnabled: caps.value.quality,
      orientationEnabled: caps.value.orientation,
      baseSeed: baseSeed.value,
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

    if (activeSlotCount.value === 0) {
      return rejectBeforeSubmit(
        '无法提交。原因：请至少选择一个参考图或上传一张参考图。下一步：从人像 / 服装 / 姿势任一库选择参考图，或上传第 4 张后再提交。',
      )
    }

    if (batchOverLimit.value) {
      return rejectBeforeSubmit(
        `无法提交。原因：${batchLimitMessage.value}。下一步：减少素材或尺寸档位后重试。`,
      )
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
    setExtra,
    clearExtra,
    // 提示词只读预览（dry_run，与正式提交完全独立）
    previewPrompt,
    previewError,
    previewLoading,
    refreshPreviewPrompt,
    previewWorkflow,
    previewWorkflowSkipReason,
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