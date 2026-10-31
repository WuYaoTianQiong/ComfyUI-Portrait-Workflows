/** 极薄的请求封装：统一错误处理与查询参数拼装。 */

import type { HistoryItem } from './types'

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

/** 图片访问地址（缩略图/原图都走这里，避免各处手拼 query 串）。 */
export function thumbnailUrl(item: Pick<HistoryItem, 'filename' | 'subfolder' | 'img_type' | 'id'>, size = 600): string {
  return (
    '/api/media/thumbnail' +
    buildQuery({
      filename: item.filename,
      subfolder: item.subfolder ?? '',
      type: item.img_type ?? 'output',
      size,
      v: item.id,
    })
  )
}

/** 原图地址 */
export function viewUrl(item: Pick<HistoryItem, 'filename' | 'subfolder' | 'img_type'>): string {
  return (
    '/api/media/image' +
    buildQuery({
      filename: item.filename,
      subfolder: item.subfolder ?? '',
      type: item.img_type ?? 'output',
    })
  )
}
