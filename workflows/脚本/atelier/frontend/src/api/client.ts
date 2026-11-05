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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
  })
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '')
    throw new Error(`${resp.status} ${detail.slice(0, 200)}`)
  }
  return (await resp.json()) as T
}

export function apiGet<T>(path: string, params: QueryParams = {}): Promise<T> {
  return request<T>(path + buildQuery(params))
}

export function apiPost<T>(path: string, body?: unknown, params: QueryParams = {}): Promise<T> {
  return request<T>(path + buildQuery(params), {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
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

/**
 * 缩略图访问地址（画廊/工作台共用，避免各处手拼 query 串）。
 *
 * `v` 是内容版本：优先用后端 `/api/images` 返回的 `version`（源文件 st_mtime_ns 字符串），
 * 缺失时回落记录 id。前者让"同名覆盖"也会换 URL（配合后端 immutable 缓存头），
 * 后者只保证不同记录不撞 URL。注意空串要按"没给"处理（`||` 而非 `??`），
 * 否则后端缺源文件时的空串会顶掉 id 回落，让 URL 彻底失去 cache-busting。
 */
export function thumbnailUrl(
  item: ImageRef & { id?: number; version?: string | null },
  size = 600,
): string {
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

/** 原图地址 */
export function viewUrl(item: ImageRef): string {
  return (
    '/api/media/image' +
    buildQuery({
      filename: item.filename,
      subfolder: item.subfolder ?? '',
      type: item.img_type ?? 'output',
    })
  )
}
