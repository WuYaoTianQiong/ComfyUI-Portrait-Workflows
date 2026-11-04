/**
 * 合成台后端提交与任务轮询客户端（契约 C-JOB-PROGRESS@1）。
 *
 * 本模块只与 atelier 同源 API 通信：
 * - 提交：`POST /api/reference/recipes`
 * - 查询：`GET /api/jobs/{id}`
 * - 结果图：`/api/media/image?...`
 *
 * 不再直连本地出图服务，也不再做连接级进度跟踪；节点映射与提示词
 * 生成全部由后端承担。所有请求使用同源绝对路径，站点可由 atelier 挂在
 * `/ref-web` 下而不影响 API 根路径。
 */

/** 提交给后端的三图/四图配方请求（C-REF-RECIPES@2）。 */
export interface RecipeSubmitRequest {
  portrait_id?: string
  costume_id?: string
  pose_id?: string
  costume_library?: 'costume' | 'costume-anime'
  portrait_path?: string
  costume_path?: string
  pose_path?: string
  extra_library?: string
  extra_id?: string
  extra_path?: string
  style: 'none' | 'realistic'
  prompt_suffix?: string
  seed: number
  seed_mode?: 'fixed' | 'random' | 'increment'
}

/** `POST /api/reference/recipes` 的响应（C-REF-RECIPES@2）。 */
export interface RecipeSubmitResponse {
  success: boolean
  job_id: number
  total: number
  submitted: number
  queued: number
  errors: string[]
  async: boolean
  prompt: string
  workflow_path: string
  slots: Array<Record<string, unknown>>
  references: Record<string, string>
}

/** 后端返回的任务快照（`GET /api/jobs/{id}`）。 */
export interface JobSnapshotDto {
  id: number
  job_type: string
  status: string
  title: string
  total: number
  done_count: number
  error_count: number
  items: Array<{
    prompt_id?: number
    status?: string
    error?: string
    images: Array<{ filename: string; subfolder?: string; type?: string }>
  }>
  workflow_path?: string
  extra?: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

/** 合成台进度状态（C-JOB-PROGRESS@1），由 studio.tsx 直接渲染。 */
export interface GenerationProgress {
  stage: 'submit' | 'queued' | 'running' | 'download'
  message: string
  /** 0-100，仅当后端 total > 0 时提供。 */
  percent?: number
}

/** 持久化的未决任务（C-JOB-PROGRESS@1）；刷新后按 jobId 恢复轮询。 */
export interface ActiveJobInfo {
  jobId: number
  prompt: string
  summary: string
  submittedAt: number
}

/** 提交阶段的错误：保留 HTTP 状态码与后端 `detail` 文案。 */
export class RecipeSubmitError extends Error {
  readonly status: number
  readonly detail: string

  constructor(detail: string, status: number) {
    super(detail)
    this.name = 'RecipeSubmitError'
    this.status = status
    this.detail = detail
  }
}

const RECIPES_ENDPOINT = '/api/reference/recipes'
const JOBS_ENDPOINT = '/api/jobs'
const DEFAULT_POLL_INTERVAL_MS = 1500
/** 后端单批任务可能长时间排队，轮询上限与计划一致（30 分钟）。 */
const DEFAULT_POLL_TIMEOUT_MS = 30 * 60 * 1000
const MAX_CONSECUTIVE_POLL_ERRORS = 3

const SUCCESS_STATUSES = new Set(['success', 'done', 'completed', 'finished'])
const FAILURE_STATUSES = new Set(['failed', 'error', 'cancelled', 'canceled', 'stopped'])

function abortError(): DOMException {
  return new DOMException('已停止跟踪，后台任务继续执行', 'AbortError')
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  )
}

/** 读取后端 `{detail}`；非 JSON 或非字符串时回退 `HTTP {status}`。 */
async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body?.detail === 'string' && body.detail.trim()) return body.detail
  } catch {
    // 开发服务器未代理 /api 时会返回 HTML，按状态码处理。
  }
  return `HTTP ${response.status}`
}

/**
 * 提交配方任务。
 *
 * 非 2xx 统一抛 {@link RecipeSubmitError}；网络中断同样抛出该错误
 * （`status = 0`），调用方只需处理这一种错误类型。
 */
export async function submitRecipe(req: RecipeSubmitRequest): Promise<RecipeSubmitResponse> {
  let response: Response
  try {
    response = await fetch(RECIPES_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })
  } catch {
    throw new RecipeSubmitError('提交出图任务失败：网络请求失败', 0)
  }

  if (!response.ok) {
    throw new RecipeSubmitError(await readErrorDetail(response), response.status)
  }

  try {
    return (await response.json()) as RecipeSubmitResponse
  } catch {
    throw new RecipeSubmitError(`提交出图任务失败：响应不是 JSON（HTTP ${response.status}）`, response.status)
  }
}

async function requestJob(jobId: number, signal?: AbortSignal): Promise<JobSnapshotDto> {
  let response: Response
  try {
    response = await fetch(`${JOBS_ENDPOINT}/${jobId}`, { signal })
  } catch (error) {
    if (isAbortError(error)) throw abortError()
    throw new Error('查询任务状态失败：网络请求失败')
  }
  if (!response.ok) {
    const detail = await readErrorDetail(response)
    throw new Error(`查询任务状态失败：${detail}`)
  }
  try {
    return (await response.json()) as JobSnapshotDto
  } catch {
    throw new Error(`查询任务状态失败：响应不是 JSON（HTTP ${response.status}）`)
  }
}

/** 查询单次任务快照；失败抛可读错误。 */
export async function fetchJob(jobId: number): Promise<JobSnapshotDto> {
  return requestJob(jobId)
}

/** signal 中止时立即 reject，避免轮询等待期间无法退出。 */
function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError())
      return
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, Math.max(0, ms))
    const onAbort = () => {
      clearTimeout(timer)
      reject(abortError())
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/**
 * 轮询任务直到终态。
 *
 * - 默认间隔 1.5s，最长 30 分钟；
 * - `success|done|completed|finished` 与 `failed|error|cancelled|canceled|stopped`
 *   均视为终态并返回快照，由调用方根据状态展示结果或失败原因；
 * - `signal` 中止时抛 `AbortError`，不改变后端任务；
 * - 连续 3 次查询失败才抛出，单次抖动继续重试。
 */
export async function pollJob(
  jobId: number,
  opts: {
    intervalMs?: number
    timeoutMs?: number
    signal?: AbortSignal
    onUpdate?: (snapshot: JobSnapshotDto) => void
  } = {}
): Promise<JobSnapshotDto> {
  const intervalMs = opts.intervalMs && opts.intervalMs > 0 ? opts.intervalMs : DEFAULT_POLL_INTERVAL_MS
  const timeoutMs = opts.timeoutMs && opts.timeoutMs > 0 ? opts.timeoutMs : DEFAULT_POLL_TIMEOUT_MS
  const startedAt = Date.now()
  let consecutiveErrors = 0

  for (;;) {
    if (opts.signal?.aborted) throw abortError()
    if (Date.now() - startedAt >= timeoutMs) {
      throw new Error('等待出图结果超时（30 分钟），请前往任务中心查看')
    }

    let snapshot: JobSnapshotDto
    try {
      snapshot = await requestJob(jobId, opts.signal)
    } catch (error) {
      // 中止必须原样透传，不能被网络错误重试逻辑吞掉。
      if (isAbortError(error)) throw error
      consecutiveErrors += 1
      if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
        throw error instanceof Error ? error : new Error('查询任务状态失败：未知错误')
      }
      await wait(intervalMs, opts.signal)
      continue
    }

    consecutiveErrors = 0
    opts.onUpdate?.(snapshot)

    const status = String(snapshot?.status ?? '').toLowerCase()
    if (SUCCESS_STATUSES.has(status) || FAILURE_STATUSES.has(status)) return snapshot

    await wait(intervalMs, opts.signal)
  }
}

/** 任务是否处于成功终态。 */
export function isJobSucceeded(snapshot: JobSnapshotDto): boolean {
  return SUCCESS_STATUSES.has(String(snapshot?.status ?? '').toLowerCase())
}

/** 汇总任务内条目的错误文案，供失败提示使用。 */
export function jobErrorMessages(snapshot: JobSnapshotDto): string[] {
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
 * 顺序按 items 与 images 的返回顺序，重复 URL 只保留首次出现。
 * 缺省 `type=output`，与后端媒体端点默认值一致。
 */
export function jobResultUrls(snapshot: JobSnapshotDto): string[] {
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
export function describeJobProgress(snapshot: JobSnapshotDto): GenerationProgress {
  const status = String(snapshot?.status ?? '').toLowerCase()
  const total = Number(snapshot?.total) || 0
  const done = Number(snapshot?.done_count) || 0
  const percent = total > 0 ? Math.min(100, Math.max(0, Math.round((done / total) * 100))) : undefined
  const counts = total > 0 ? `（已完成 ${done}/${total}）` : ''

  if (SUCCESS_STATUSES.has(status)) {
    return { stage: 'download', message: `任务已完成，正在获取生成结果…${counts}`, percent }
  }
  if (FAILURE_STATUSES.has(status)) {
    return { stage: 'download', message: `任务已结束（${status}），正在确认结果…${counts}`, percent }
  }
  if (status === 'pending' || status === 'queued' || status === 'waiting') {
    return { stage: 'queued', message: `任务已提交，正在排队…${counts}`, percent }
  }
  return { stage: 'running', message: `正在出图…${counts}`, percent }
}