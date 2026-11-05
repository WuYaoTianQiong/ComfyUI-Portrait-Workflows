/**
 * 合成台批量提交与轮询（契约 C-REF-RECIPES@2 / C-JOB-PROGRESS@1）。
 *
 * 与阶段 3 最薄版的差异（本次升级）：
 * - 三槽改为**多选**：每槽 N 张，前端按「槽位组合 × 画质档 × 比例」做笛卡尔积，
 *   **每组独立 POST**（后端 `RecipeRequest` 的槽位仍是单值）；
 * - 全组合上限 {@link MAX_BATCH_RECIPES}（100），超限时页面禁用提交；
 * - 提交并发上限 {@link MAX_SUBMIT_CONCURRENCY}（2），不一次打满后端；
 * - 种子按组派生：第 i 组 `seed = base_seed + i`、`seed_mode='fixed'`；
 * - 提交体透传 `workflow` / `quality` / `aspect_ratio` / `orientation`，
 *   但 `caps.quality` / `caps.orientation` 为 false 时**绝不发送**对应字段；
 * - 非空槽数 M < 所选工作流 input_count N 时，提交前弹出降级确认框
 *   （列出 `input_count <= M` 的候选），不做静默自动切换。
 *
 * 明确不迁（施工手册 §7 冻结）：配方草稿持久化、未决任务恢复追踪、
 * 通用参数面板、提示词只读预览。本文件不读写 localStorage / IndexedDB。
 */

import { computed, onBeforeUnmount, ref, watch } from 'vue'


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
/** 任务快照端点前缀。 */
export const RECIPE_JOB_ENDPOINT = '/api/jobs'
/** 工作流目录（合成台只看能塞参考图的工作流）。 */
export const STUDIO_WORKFLOWS_ENDPOINT = '/api/workflows?scope=studio'
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
  seed?: number
  seedMode?: 'fixed' | 'random'
}

/** 批量输入：三槽多选 + 尺寸档位多选。 */
export interface RecipeBatchInput {
  portrait: readonly PortraitItem[]
  costume: readonly CostumeItem[]
  pose: readonly PoseItem[]
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
  const request: RecipeSubmitRequest = {
    costume_library: costumeLibraryOf(slots.costume),
    style: normalizeRecipeStyle(options.style),
    prompt_suffix: options.promptSuffix.trim(),
    seed: options.seed ?? DEFAULT_RECIPE_SEED,
    seed_mode: options.seedMode ?? 'fixed',
  }

  if (slots.portrait) request.portrait_id = slots.portrait.id
  if (slots.costume) request.costume_id = slots.costume.id
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
 * 全组合数 = 槽位组合数 × 画质档数 × 比例数。
 *
 * 尺寸维度传 0 表示「该能力不可用 / 未选择」，按 1 计。
 */
export function countBatchTotal(
  counts: RecipeSlotCounts,
  qualityCount: number,
  ratioCount: number,
): number {
  const combos = countSlotCombinations(counts)
  if (combos === 0) return 0
  return combos * Math.max(1, qualityCount) * Math.max(1, ratioCount)
}

/** 是否超过全组合上限。 */
export function exceedsBatchLimit(total: number): boolean {
  return total > MAX_BATCH_RECIPES
}

/** 超限文案（与页面按钮禁用提示逐字一致）。 */
export function describeBatchLimit(total: number): string {
  return `全组合共 ${total} 张，超过上限 ${MAX_BATCH_RECIPES} 张；请减少素材或尺寸档位`
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
 * 生成笛卡尔积分组（= 前端要逐组 POST 的请求清单）。
 *
 * 顺序固定：槽位组合 → 画质 → 比例；第 i 组种子 = baseSeed + i。
 * caps 不支持时对应维度折叠为「不发参数」（空串），计数仍为 1。
 */
export function buildBatchGroups(input: RecipeBatchInput): RecipeBatchGroup[] {
  const slotCombos = buildSlotCombinations(input.portrait, input.costume, input.pose)
  const qualityDim =
    input.qualityEnabled && input.qualities.length ? [...input.qualities] : ['']
  const ratioDim = input.orientationEnabled && input.ratios.length ? [...input.ratios] : ['']
  const baseSeed = Math.max(0, Math.trunc(Number(input.baseSeed) || DEFAULT_RECIPE_SEED))

  const groups: RecipeBatchGroup[] = []
  let index = 0
  for (const slots of slotCombos) {
    for (const quality of qualityDim) {
      for (const ratio of ratioDim) {
        groups.push({
          index,
          slots,
          quality,
          aspectRatio: ratio,
          orientation: ratio ? orientationForRatio(ratio) : '',
          seed: baseSeed + index,
        })
        index += 1
      }
    }
  }
  return groups
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
      snapshot = await fetchRecipeJob(jobId)
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

/** 提交状态机。 */
export type RecipeRunStatus = 'idle' | 'submitting' | 'polling' | 'success' | 'failed'

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

/** 批量进度聚合：按 job 记录各组的 total / done。 */
function describeBatchProgress(
  aggregates: ReadonlyMap<number, { total: number; done: number }>,
): RecipeProgress {
  let total = 0
  let done = 0
  for (const value of aggregates.values()) {
    total += Math.max(0, value.total)
    done += Math.max(0, value.done)
  }
  if (total <= 0) {
    return { stage: 'running', message: '正在出图…', percent: null }
  }
  const percent = Math.min(100, Math.max(0, Math.round((done / total) * 100)))
  return {
    stage: 'running',
    message: `正在出图…（已完成 ${done}/${total}）`,
    percent,
  }
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
  const workflowPath = ref('')
  const workflowsLoading = ref(false)
  const workflowsError = ref('')

  const style = ref<RecipeStyle>('realistic')
  const promptSuffix = ref('')
  const extraPath = ref('')
  const extraName = ref('')

  /** 尺寸档位 / 比例均为多选；空数组表示本轮不发对应参数。 */
  const qualitySelection = ref<string[]>([])
  const ratioSelection = ref<string[]>([])
  /** 基础种子；第 i 组 = baseSeed + i。 */
  const baseSeed = ref<number>(DEFAULT_RECIPE_SEED)

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
  /** 非空时页面渲染降级确认框；用户确认切换后才继续提交。 */
  const workflowDowngrade = ref<WorkflowDowngradePrompt | null>(null)

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

  /** 当前工作流：input_count 用于提交前能力预判。 */
  const currentWorkflow = computed(
    () => workflows.value.find((item) => item.path === workflowPath.value) ?? null,
  )
  const workflowInputCount = computed(() => currentWorkflow.value?.inputCount ?? 0)

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

  /** 尺寸维度：caps 不支持时折叠为 1（页面也会隐藏控件）。 */
  const qualityDimension = computed(() =>
    caps.value.quality ? qualitySelection.value.length : 0,
  )
  const ratioDimension = computed(() =>
    caps.value.orientation ? ratioSelection.value.length : 0,
  )

  /** 全组合数（常驻展示 N/100，提交前也用它做上限判断）。 */
  const batchTotal = computed(() =>
    countBatchTotal(slotCounts.value, qualityDimension.value, ratioDimension.value),
  )
  const batchOverLimit = computed(() => exceedsBatchLimit(batchTotal.value))
  const batchLimitMessage = computed(() =>
    batchOverLimit.value ? describeBatchLimit(batchTotal.value) : '',
  )

  /** Qwen 系（尺寸跟随参考图）：caps 既不支持画质也不支持横竖。 */
  const followsReferenceSize = computed(
    () => !caps.value.quality && !caps.value.orientation,
  )

  const busy = computed(() => status.value === 'submitting' || status.value === 'polling')
  const progressPercent = computed<number | null>(() => {
    const value = progress.value.percent
    if (typeof value !== 'number' || !Number.isFinite(value)) return null
    return Math.min(100, Math.max(0, Math.round(value)))
  })
  const primaryResultUrl = computed(() => resultUrls.value[0] ?? '')
  const selectedCount = computed(() => draft.totalSelected.value)
  const canSubmit = computed(
    () =>
      !busy.value &&
      !workflowsLoading.value &&
      Boolean(workflowPath.value) &&
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
   * 第 4 张按需求不参与预览。带上当前工作流，避免默认工作流输入数不匹配。
   */
  function buildPreviewRequest(): RecipeSubmitRequest {
    return buildRecipeRequest(
      {
        portrait: draft.portrait.value[0] ?? null,
        costume: draft.costume.value[0] ?? null,
        pose: draft.pose.value[0]?.item ?? null,
      },
      {
        style: style.value,
        promptSuffix: promptSuffix.value,
        extraPath: '',
        workflow: workflowPath.value,
        seed: baseSeed.value,
        seedMode: 'fixed',
      },
    )
  }

  /** 立即刷新预览（按请求序号丢弃过期响应）；失败只写 `previewError`，不影响提交状态机。 */
  async function refreshPreviewPrompt(): Promise<void> {
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
      workflowPath,
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
          caps: parseStudioCaps(item.caps),
          params: parseStudioParams(item.params),
        })
      }

      workflows.value = options
      workflowDefault.value = typeof body.default === 'string' ? body.default : ''
      const stillUsable =
        Boolean(workflowPath.value) && options.some((item) => item.path === workflowPath.value)
      if (!stillUsable) {
        workflowPath.value = resolveInitialWorkflowPath(options, workflowDefault.value)
      }
      reconcileSizeSelections()
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      workflowsError.value = `读取工作流列表失败。原因：${message}。下一步：点击「重试」重新读取，或确认后端服务在线。`
    } finally {
      workflowsLoading.value = false
    }
  }

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
  function clearRunState(): void {
    status.value = 'idle'
    progress.value = { stage: 'submit', message: '', percent: null }
    errorMessage.value = ''
    resultUrls.value = []
    jobIds.value = []
    jobId.value = null
    workflowDowngrade.value = null
  }

  /**
   * 逐组提交 + 聚合轮询。
   *
   * 提交并发上限 2；每组独立 job，种子已在分组阶段派生。
   * 返回 true 表示全部组成功且至少有一张结果图。
   */
  async function runBatch(groups: RecipeBatchGroup[]): Promise<boolean> {
    status.value = 'submitting'
    progress.value = {
      stage: 'submit',
      message: `正在提交 0/${groups.length} 组…`,
      percent: 0,
    }

    let submittedCount = 0
    const outcomes = await runWithConcurrency(
      groups,
      MAX_SUBMIT_CONCURRENCY,
      async (group): Promise<SubmitOutcome> => {
        const request = buildRecipeRequest(group.slots, {
          style: style.value,
          promptSuffix: promptSuffix.value,
          extraPath: extraPath.value,
          workflow: workflowPath.value,
          quality: group.quality,
          aspectRatio: group.aspectRatio,
          orientation: group.orientation,
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
          submittedCount += 1
          progress.value = {
            stage: 'submit',
            message: `正在提交 ${submittedCount}/${groups.length} 组…`,
            percent: Math.round((submittedCount / groups.length) * 100),
          }
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

    if (!submitted.length) {
      const first = submitFailures[0]
      errorMessage.value = describeSubmitFailure(
        first?.error ?? new RecipeSubmitError('提交出图任务失败', 0, '提交分组为空'),
      )
      status.value = 'failed'
      progress.value = { stage: 'done', message: '提交失败', percent: null }
      return false
    }

    jobIds.value = submitted.map((outcome) => outcome.response.job_id)
    jobId.value = jobIds.value[0] ?? null
    status.value = 'polling'

    const aggregates = new Map<number, { total: number; done: number }>()
    for (const id of jobIds.value) aggregates.set(id, { total: 1, done: 0 })
    progress.value = {
      stage: 'queued',
      message: `已提交 ${jobIds.value.length} 个任务，正在排队…`,
      percent: 0,
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
              progress.value = describeBatchProgress(aggregates)
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
      if (result.snapshot && isJobSucceeded(result.snapshot)) {
        urls.push(...recipeJobResultUrls(result.snapshot))
      } else if (result.snapshot) {
        failureMessages.push(describeJobFailure(result.snapshot))
      } else {
        failureMessages.push(
          describePollFailure(result.error, result.outcome.response.job_id),
        )
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

    resultUrls.value = [...new Set(urls)]
    if (failureMessages.length) {
      errorMessage.value = failureMessages.slice(0, 3).join('\n')
      status.value = 'failed'
      progress.value = {
        stage: 'done',
        message: `部分任务失败（成功 ${resultUrls.value.length} 张）`,
        percent: progressPercent.value,
      }
      return false
    }

    if (!resultUrls.value.length) {
      errorMessage.value = describeMissingResult(
        lastSnapshot ?? { id: jobId.value ?? 0, status: 'done', total: 0, done_count: 0, error_count: 0, items: [] },
      )
      status.value = 'failed'
      progress.value = {
        stage: 'done',
        message: '任务已完成，但没有可展示的结果图',
        percent: 100,
      }
      return false
    }

    previousResultUrl.value = resultUrls.value[0]
    status.value = 'success'
    progress.value = {
      stage: 'done',
      message: `已完成 ${resultUrls.value.length} 张`,
      percent: 100,
    }
    return true
  }

  /** 用当前工作流与当前选择构造分组（提交前 / 强制提交共用）。 */
  function buildCurrentBatchGroups(): RecipeBatchGroup[] {
    return buildBatchGroups({
      portrait: draft.portrait.value,
      costume: draft.costume.value,
      pose: draft.pose.value.map((entry) => entry.item),
      qualities: qualitySelection.value,
      ratios: ratioSelection.value,
      qualityEnabled: caps.value.quality,
      orientationEnabled: caps.value.orientation,
      baseSeed: baseSeed.value,
    })
  }

  /**
   * 提交入口。
   *
   * 返回 false 有两种含义：真的失败（`errorMessage` 已写好三句式文案），或
   * 需要先过降级确认框（`workflowDowngrade` 非空，页面据此弹窗）。
   */
  async function submit(): Promise<boolean> {
    if (busy.value) return false
    workflowDowngrade.value = null
    errorMessage.value = ''
    // 先记住上一次成功的结果，再清空本次结果：失败区「查看上一张结果」依赖它。
    if (resultUrls.value[0]) previousResultUrl.value = resultUrls.value[0]
    resultUrls.value = []
    jobIds.value = []
    jobId.value = null

    if (!workflowPath.value) {
      errorMessage.value =
        '无法提交。原因：尚未选择出图工作流。下一步：在工作流下拉中选择一个可用工作流后重试。'
      status.value = 'failed'
      return false
    }

    if (activeSlotCount.value === 0) {
      errorMessage.value =
        '无法提交。原因：请至少选择一个参考图或上传一张参考图。下一步：从人像 / 服装 / 姿势任一库选择参考图，或上传第 4 张后再提交。'
      status.value = 'failed'
      return false
    }

    if (batchOverLimit.value) {
      errorMessage.value = `无法提交。原因：${batchLimitMessage.value}。下一步：减少素材或尺寸档位后重试。`
      status.value = 'failed'
      return false
    }

    // 能力预判：M（非空槽数）< N（工作流输入数）时先确认，不做静默自动切换。
    const inputCount = workflowInputCount.value
    if (inputCount > 0 && activeSlotCount.value < inputCount) {
      workflowDowngrade.value = {
        message: describeWorkflowDowngrade(inputCount, activeSlotCount.value),
        slotCount: activeSlotCount.value,
        inputCount,
        candidates: buildWorkflowDowngradeCandidates(
          workflows.value,
          workflowPath.value,
          activeSlotCount.value,
        ),
      }
      return false
    }

    const groups = buildCurrentBatchGroups()
    return runBatch(groups)
  }

  /** 降级确认：切到候选工作流（按新 caps 重建尺寸）后继续提交。 */
  async function confirmWorkflowDowngrade(path: string): Promise<boolean> {
    if (!workflowDowngrade.value) return false
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
  async function confirmCurrentWorkflowDowngrade(): Promise<boolean> {
    if (!workflowDowngrade.value) return false
    workflowDowngrade.value = null
    return runBatch(buildCurrentBatchGroups())
  }

  /** 取消降级：不提交，保持当前工作流与选择。 */
  function cancelWorkflowDowngrade(): void {
    workflowDowngrade.value = null
    errorMessage.value = ''
    status.value = 'idle'
  }

  /** 重试：清空失败态后重新提交（沿用当前槽位与设置）。 */
  async function retry(): Promise<boolean> {
    clearRunState()
    return submit()
  }

  return {
    // 工作流目录
    workflows,
    workflowDefault,
    workflowPath,
    workflowsLoading,
    workflowsError,
    loadStudioWorkflows,
    currentWorkflow,
    workflowInputCount,
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
    // 降级确认
    workflowDowngrade,
    confirmWorkflowDowngrade,
    confirmCurrentWorkflowDowngrade,
    cancelWorkflowDowngrade,
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
    selectedCount,
    canSubmit,
    submit,
    retry,
    clearRunState,
  }
}