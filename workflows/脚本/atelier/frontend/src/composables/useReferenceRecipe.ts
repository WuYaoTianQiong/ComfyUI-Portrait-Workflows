/**
 * 合成台提交与轮询（阶段 3 最薄版，契约 C-REF-RECIPES@2 / C-JOB-PROGRESS@1）。
 *
 * 逐条平移 React 侧 `services/recipeClient.ts` + `store/studioStore.tsx` 的提交语义：
 * - 提交：`POST /api/reference/recipes`，提交体字段以后端 `RecipeRequest` 为准；
 * - 查询：`GET /api/jobs/{id}`，轮询间隔 1500ms，上限 30 分钟；
 * - 终态集合与 React 一致（success/done/completed/finished 与
 *   failed/error/cancelled/canceled/stopped）；
 * - 连续 3 次查询失败才抛错，单次网络抖动继续重试；
 * - 结果图只取后端同源的 `/api/media/image?filename=...`，**零**直连 8188 /
 *   `/prompt` / `/comfy`；
 * - 错误统一转成中文三句式（现象 + 原因 + 下一步），由页面直接渲染。
 *
 * 明确不迁（施工手册 §7 冻结）：配方草稿持久化、未决任务恢复追踪、
 * 通用参数面板、提示词只读预览。因此本文件不读写 localStorage / IndexedDB，
 * 也不提交 workflow_path —— 后端 `RecipeRequest` 没有该字段，出图工作流由
 * 后端按「是否有第 4 张」固定选择。
 */

import { computed, ref, watch } from 'vue'
import type { Router } from 'vue-router'

import type { CostumeItem, PoseItem, PortraitItem } from '../api/reference'
import { useReferenceRecipeDraft } from './useReferenceRecipeDraft'
import type { RecipeSlotKey } from './useReferenceRecipeDraft'

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
  imageSlots: number
  recommended: boolean
}

/** 工作流目录响应。 */
export interface StudioWorkflowCatalog {
  workflows: StudioWorkflowOption[]
  default: string
}

/** 三槽当前选择（只取提交需要的字段）。 */
export interface RecipeSlots {
  portrait: PortraitItem | null
  costume: CostumeItem | null
  pose: PoseItem | null
}

/** 提交体构造参数。 */
export interface RecipeRequestOptions {
  style: RecipeStyle
  promptSuffix: string
  /** 第 4 张上传图的后端路径；空串表示不带第 4 张 */
  extraPath: string
  seed?: number
  seedMode?: 'fixed' | 'random'
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
 * 构造提交体。
 *
 * 与 React `startGeneration` 的差异只有一处：不发送 workflow_path / 参数覆盖，
 * 因为后端 `RecipeRequest` 没有这些字段（D4 冻结：节点映射由后端固定）。
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

  return request
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

/** 提交失败 → 三句式中文错误（现象 + 原因 + 下一步）。 */
export function describeSubmitFailure(cause: unknown): string {
  if (cause instanceof RecipeSubmitError) {
    const detail = cause.detail
    if (cause.status === 0) {
      return '提交出图任务失败。原因：无法连接后端（网络中断或服务未启动）。下一步：确认后端服务在线后点击「重试」。'
    }
    if (/uploads|上传目录|上传的/i.test(detail)) {
      return `第 4 张参考图被后端拒绝。原因：${detail}（后端只接受通过上传接口落盘的图片）。下一步：用页面上的「添加附加参考图」重新上传后再提交，不要填本地磁盘路径。`
    }
    if (detail.includes('缺少')) {
      return `提交被拒绝。原因：${detail}。下一步：补齐人像、服装、姿势三槽参考图后再提交。`
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
// 「选完图自动回合成台」：跨页签的一次性跳转约定
// ---------------------------------------------------------------------------

/**
 * 从合成台槽位跳到对应库页签后，用户一旦「加入配方」，自动把 `?tab=` 切回
 * `studio`。
 *
 * 为什么放在模块级：合成台组件在跳走时已卸载，组件内 watch 无法存活；
 * 而库页（阶段 2 已完成）不允许改。因此这里注册一次性的模块级 watch：
 * - 记录被点击的槽位与点击前的条目 id（baseline）；
 * - 只有该槽位真的被**换成另一条**时才跳回，点同一张取消不跳；
 * - 跳转前校验当前仍在对应库页签（用户已手动回合成台则不跳，避免抢导航）；
 * - 跳转后立即解除，避免后续浏览时被意外拉回。
 */
let returnRouter: Router | null = null
let returnSlot: RecipeSlotKey | null = null
let returnBaselineId = ''
let returnWatcherInstalled = false

function slotIdOf(slot: RecipeSlotKey): string {
  const draft = useReferenceRecipeDraft()
  if (slot === 'portrait') return draft.portrait.value?.id ?? ''
  if (slot === 'costume') return draft.costume.value?.id ?? ''
  return draft.pose.value?.item.id ?? ''
}

function disarmStudioReturn(): void {
  returnRouter = null
  returnSlot = null
  returnBaselineId = ''
}

function handleSlotChange(slot: RecipeSlotKey, id: string): void {
  if (!returnRouter || returnSlot !== slot) return
  if (!id || id === returnBaselineId) return

  const router = returnRouter
  const route = router.currentRoute.value
  const tab = typeof route.query.tab === 'string' ? route.query.tab : ''
  if (tab !== slot) {
    disarmStudioReturn()
    return
  }

  disarmStudioReturn()
  void router.replace({
    path: route.path,
    query: { ...route.query, tab: 'studio' },
    hash: route.hash,
  })
}

function ensureReturnWatcher(): void {
  if (returnWatcherInstalled) return
  returnWatcherInstalled = true
  const draft = useReferenceRecipeDraft()
  watch(draft.portrait, (value) => handleSlotChange('portrait', value?.id ?? ''))
  watch(draft.costume, (value) => handleSlotChange('costume', value?.id ?? ''))
  watch(draft.pose, (value) => handleSlotChange('pose', value?.item.id ?? ''))
}

/** 合成台槽位点击时调用：登记「选完自动回合成台」。 */
export function armStudioReturn(slot: RecipeSlotKey, router: Router): void {
  ensureReturnWatcher()
  returnRouter = router
  returnSlot = slot
  returnBaselineId = slotIdOf(slot)
}

/** 合成台挂载 / 手动回到合成台时解除，避免历史登记残留。 */
export function resetStudioReturn(): void {
  disarmStudioReturn()
}

// ---------------------------------------------------------------------------
// Composable
// ---------------------------------------------------------------------------

/** 提交状态机。 */
export type RecipeRunStatus = 'idle' | 'submitting' | 'polling' | 'success' | 'failed'

/**
 * 合成台提交与进度状态。
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

  const status = ref<RecipeRunStatus>('idle')
  const progress = ref<RecipeProgress>({
    stage: 'submit',
    message: '',
    percent: null,
  })
  const jobId = ref<number | null>(null)
  const resultUrls = ref<string[]>([])
  const previousResultUrl = ref('')
  const errorMessage = ref('')

  const busy = computed(() => status.value === 'submitting' || status.value === 'polling')
  const progressPercent = computed<number | null>(() => {
    const value = progress.value.percent
    if (typeof value !== 'number' || !Number.isFinite(value)) return null
    return Math.min(100, Math.max(0, Math.round(value)))
  })
  const primaryResultUrl = computed(() => resultUrls.value[0] ?? '')
  const selectedCount = computed(() => draft.count.value)
  const missingSlots = computed(() => {
    const missing: string[] = []
    if (!draft.portrait.value) missing.push('人像')
    if (!draft.costume.value) missing.push('服装')
    if (!draft.pose.value) missing.push('姿势')
    return missing
  })
  const canSubmit = computed(
    () => !busy.value && missingSlots.value.length === 0 && !workflowsLoading.value,
  )

  /**
   * 读取本机工作流目录（scope=studio）。
   *
   * 自动选中后端 `default`；它缺失或不在列表时回落第一条。用户已手动选择
   * 且该路径仍可用时保留用户选择（重试刷新不应覆盖）。
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
          recommended: item.recommended === true,
        })
      }

      workflows.value = options
      workflowDefault.value = typeof body.default === 'string' ? body.default : ''
      const stillUsable =
        Boolean(workflowPath.value) && options.some((item) => item.path === workflowPath.value)
      if (!stillUsable) {
        workflowPath.value = resolveInitialWorkflowPath(options, workflowDefault.value)
      }
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      workflowsError.value = `读取工作流列表失败。原因：${message}。下一步：点击「重试」重新读取，或确认后端服务在线。`
    } finally {
      workflowsLoading.value = false
    }
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
  }

  /**
   * 提交 + 轮询。
   *
   * 返回 true 表示拿到成功终态（结果图可能为空，由页面按 `resultUrls` 判断）；
   * false 表示失败 / 中断，`errorMessage` 已写好三句式文案。
   *
   * 不做 abort：切换页签只放弃展示，后端任务继续执行（本阶段不迁任务恢复）。
   */
  async function submit(): Promise<boolean> {
    if (busy.value) return false
    errorMessage.value = ''
    // 先记住上一次成功的结果，再清空本次结果：失败区「查看上一张结果」依赖它。
    if (resultUrls.value[0]) previousResultUrl.value = resultUrls.value[0]
    resultUrls.value = []

    const missing = missingSlots.value
    if (missing.length) {
      errorMessage.value = `提交缺少必要槽位。原因：当前未选择${missing.join('、')}。下一步：从对应图库各选一条参考图后再提交。`
      status.value = 'failed'
      return false
    }

    const request = buildRecipeRequest(
      {
        portrait: draft.portrait.value,
        costume: draft.costume.value,
        pose: draft.pose.value?.item ?? null,
      },
      {
        style: style.value,
        promptSuffix: promptSuffix.value,
        extraPath: extraPath.value,
      },
    )

    status.value = 'submitting'
    progress.value = { stage: 'submit', message: '正在提交出图任务…', percent: null }
    jobId.value = null

    try {
      const submitted = await submitRecipe(request)
      if (!submitted?.success || !submitted.job_id) {
        const detail = submitted?.errors?.filter(Boolean).join('；') || '后端未返回任务编号'
        throw new RecipeSubmitError('提交出图任务失败', 0, detail)
      }

      jobId.value = submitted.job_id
      status.value = 'polling'
      progress.value = { stage: 'queued', message: '任务已提交，正在排队…', percent: null }

      const snapshot = await pollRecipeJob(submitted.job_id, {
        onUpdate: (next) => {
          progress.value = describeJobProgress(next)
        },
      })

      if (isJobSucceeded(snapshot)) {
        resultUrls.value = recipeJobResultUrls(snapshot)
        status.value = 'success'
        if (resultUrls.value.length) {
          progress.value = { stage: 'done', message: '任务已完成', percent: 100 }
          previousResultUrl.value = resultUrls.value[0]
          return true
        }
        progress.value = { stage: 'done', message: '任务已完成，但没有可展示的结果图', percent: 100 }
        errorMessage.value = describeMissingResult(snapshot)
        status.value = 'failed'
        return false
      }

      errorMessage.value = describeJobFailure(snapshot)
      status.value = 'failed'
      return false
    } catch (cause) {
      errorMessage.value =
        cause instanceof RecipeTimeoutError
          ? describePollFailure(cause, jobId.value)
          : status.value === 'submitting'
            ? describeSubmitFailure(cause)
            : describePollFailure(cause, jobId.value)
      status.value = 'failed'
      return false
    }
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
    // 提交设置
    style,
    promptSuffix,
    extraPath,
    extraName,
    setExtra,
    clearExtra,
    // 运行状态
    status,
    progress,
    progressPercent,
    jobId,
    resultUrls,
    primaryResultUrl,
    previousResultUrl,
    errorMessage,
    busy,
    selectedCount,
    missingSlots,
    canSubmit,
    submit,
    retry,
    clearRunState,
  }
}