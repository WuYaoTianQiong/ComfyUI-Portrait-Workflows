/** 极薄的请求封装：统一错误处理与查询参数拼装。 */

export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue>

/** 拼查询串，跳过空值。注意 `missing=false` 是有效值，只跳过 '' / null / undefined。 */
export function buildQuery(params: QueryParams = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

/** 后端统一的错误形状（FastAPI 的 `detail` 可能是字符串，也可能是校验错误数组）。 */
function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'detail' in detail) {
    const inner = (detail as { detail: unknown }).detail
    return typeof inner === 'string' ? inner : JSON.stringify(inner)
  }
  return JSON.stringify(detail)
}

/** 请求失败时抛这个，调用方可以按 status 分支，并按 requestId 去日志里串一次操作。 */
export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown
  readonly requestId: string | null

  constructor(status: number, detail: unknown, requestId: string | null) {
    super(`${status} ${detailText(detail).slice(0, 200)}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.requestId = requestId
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    let detail: unknown = text
    if (text) {
      try {
        detail = JSON.parse(text)
      } catch {
        // 非 JSON 错误体（反向代理 502 等）保留原文
      }
    }
    throw new ApiError(resp.status, detail, resp.headers.get('X-Request-ID'))
  }
  // 204 / 空体在代理和未来端点里都可能出现；直接 resp.json() 会抛 SyntaxError，
  // 绕过 ApiError，让调用方拿不到 status。
  const text = await resp.text()
  if (!text) return null as T
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError(resp.status, text, resp.headers.get('X-Request-ID'))
  }
}

export function apiGet<T>(path: string, params: QueryParams = {}): Promise<T> {
  return request<T>(path + buildQuery(params))
}

export interface PostOptions {
  headers?: Record<string, string>
  /** 传了就带 `X-Idempotency-Key`，后端据此保证同一次点击只建一个任务。 */
  idempotencyKey?: string
}

export function newIdempotencyKey(): string {
  const cryptoApi = globalThis.crypto
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID()
  }
  return `idem-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function apiPost<T>(
  path: string,
  body?: unknown,
  params: QueryParams = {},
  options: PostOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers ?? {}),
  }
  if (options.idempotencyKey) headers['X-Idempotency-Key'] = options.idempotencyKey
  return request<T>(path + buildQuery(params), {
    method: 'POST',
    headers: Object.keys(headers).length ? headers : undefined,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function apiPut<T>(path: string, body?: unknown, params: QueryParams = {}): Promise<T> {
  return request<T>(path + buildQuery(params), {
    method: 'PUT',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function apiDelete<T>(path: string, params: QueryParams = {}): Promise<T> {
  return request<T>(path + buildQuery(params), { method: 'DELETE' })
}

/**
 * 图片地址的入参：只要求有 filename，其余可缺可 null。
 * 宽进（`string | null`）是因为任务快照里的 `images` 项与历史记录都靠它拼 URL，
 * 两边的可空性不完全一致，硬要求 `string` 只会让调用点堆 `?? undefined`。
 */
interface ImageRef {
  filename: string
  subfolder?: string | null
  img_type?: string | null
}

export type AssetKind = 'thumb' | 'raw'

/**
 * 图片资产地址的唯一构造器。
 *
 * `v` 是内容版本：优先用后端 `/api/images` 返回的 `version`（源文件 st_mtime_ns 字符串），
 * 缺失时回落记录 id。前者让"同名覆盖"也会换 URL（配合后端 immutable 缓存头），
 * 后者只保证不同记录不撞 URL。注意空串要按"没给"处理（`||` 而非 `??`），
 * 否则后端缺源文件时的空串会顶掉 id 回落，让 URL 彻底失去 cache-busting。
 */
export function assetUrl(
  item: ImageRef & { id?: number; version?: string | null },
  kind: AssetKind = 'raw',
  size = 600,
): string {
  if (kind === 'thumb') {
    return (
      '/api/media/thumbnail' +
      buildQuery({
        filename: item.filename,
        subfolder: item.subfolder ?? '',
        type: item.img_type ?? 'output',
        size,
        v: item.version || item.id,
      })
    )
  }
  return (
    '/api/media/image' +
    buildQuery({
      filename: item.filename,
      subfolder: item.subfolder ?? '',
      type: item.img_type ?? 'output',
    })
  )
}

export function thumbnailUrl(
  item: ImageRef & { id?: number; version?: string | null },
  size = 600,
): string {
  return assetUrl(item, 'thumb', size)
}

export function viewUrl(item: ImageRef): string {
  return assetUrl(item, 'raw')
}
