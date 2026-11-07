/** 合成台 HTTP 层：提交 / 预览 / 裁剪探测 / 任务快照与轮询。 */

import type { WorkflowCaps, WorkflowParams } from './useWorkflowCaps'
import {
  MAX_CONSECUTIVE_POLL_ERRORS,
  MAX_SUBMIT_CONCURRENCY,
  RECIPE_ENDPOINT,
  RECIPE_JOB_ENDPOINT,
  RECIPE_POLL_INTERVAL_MS,
  RECIPE_POLL_TIMEOUT_MS,
  RecipeSubmitError,
  RecipeTimeoutError,
  TRIM_CHECK_ENDPOINT,
  isJobTerminal,
} from './recipeModel'
import type {
  RecipeJobSnapshot,
  RecipePreviewResponse,
  RecipeSubmitRequest,
  RecipeSubmitResponse,
  RecipeTrimCheckRequest,
  RecipeTrimCheckResponse,
} from './recipeModel'

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
export function parseStudioCaps(raw: unknown): WorkflowCaps | undefined {
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
export function parseStudioParams(raw: unknown): WorkflowParams | undefined {
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
