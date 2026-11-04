/**
 * 生成记录数据源（atelier 后端 `GET /api/images`，契约 C-IMAGES-HISTORY@1）。
 *
 * 合成台的“生成记录”区不再读写 IndexedDB，改为只读后端画廊：
 * - 固定每页 30 条，按最新排序（`captured_at` 缺失时后端回退 `created_at`）。
 * - 请求使用同源相对路径：gallery-web 由 atelier 挂载在 `/ref-web` 下，
 *   站点根路径 `/api` 即后端 API，产物可直接作为 `<img src>`。
 * - 只消费契约列出的字段，未列出的字段忽略，避免后端扩展时前端类型漂移。
 */

import type { GenerationHistoryItem } from '@/types/gallery'

/** 后端 `HistoryItem` 中本页实际消费的字段（C-IMAGES-HISTORY@1）。 */
export interface HistoryItemDto {
  id: number
  filename: string
  subfolder: string | null
  img_type: string | null
  view_url: string | null
  created_at: string
  captured_at: string
  prompt_name: string
  prompt_params: Record<string, unknown> | null
  source: string
  width: number | null
  height: number | null
  file_size: number | null
  is_favorite: boolean
  missing: boolean
}

export interface HistoryListDto {
  items: HistoryItemDto[]
  total: number
  page: number
  page_size: number
}

export interface FetchHistoryParams {
  page?: number
  pageSize?: number
}

const DEFAULT_PAGE_SIZE = 30
const HISTORY_ERROR_PREFIX = '加载生成记录失败：'

/** 安全读取字符串：`prompt_params` 是后端任意 JSON 对象，字段类型不可信任。 */
function readString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/**
 * 后端条目 → 前端历史条目。
 *
 * 映射口径见契约 C-IMAGES-HISTORY@1；`imageUrl` 为空串时由卡片渲染占位，
 * 不能把空串塞进 `<img src>` 造成裂图。
 */
export function toGenerationHistoryItem(dto: HistoryItemDto): GenerationHistoryItem {
  const parsedAt = Date.parse(dto.captured_at || dto.created_at)
  const params = dto.prompt_params ?? null
  return {
    id: String(dto.id),
    createdAt: Number.isNaN(parsedAt) ? Date.now() : parsedAt,
    prompt: readString(params?.prompt) || dto.prompt_name || '',
    recipeSummary: dto.prompt_name || dto.filename,
    model: readString(params?.model),
    imageUrl: dto.view_url || '',
    provider: 'comfyui',
  }
}

/**
 * 拉取最新生成记录（后端分页）。
 *
 * 失败语义（契约 C-IMAGES-HISTORY@1）：网络错误、非 2xx、响应不是 JSON
 * 都会抛出带 `加载生成记录失败：` 前缀的可读错误，由页面 toast 提示；
 * 调用方不得因此阻塞图库与合成台的其余功能。
 */
export async function fetchHistory({
  page = 1,
  pageSize = DEFAULT_PAGE_SIZE,
}: FetchHistoryParams = {}): Promise<GenerationHistoryItem[]> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    sort: 'newest',
  })

  let response: Response
  try {
    response = await fetch(`/api/images?${query.toString()}`)
  } catch {
    throw new Error(`${HISTORY_ERROR_PREFIX}网络请求失败`)
  }

  if (!response.ok) {
    throw new Error(`${HISTORY_ERROR_PREFIX}HTTP ${response.status}`)
  }

  let body: HistoryListDto
  try {
    body = (await response.json()) as HistoryListDto
  } catch {
    // 开发服务器未代理 /api 时会返回 index.html，这里按不可读响应处理。
    throw new Error(`${HISTORY_ERROR_PREFIX}HTTP ${response.status}`)
  }

  if (!Array.isArray(body?.items)) {
    throw new Error(`${HISTORY_ERROR_PREFIX}响应结构异常`)
  }

  return body.items.map(toGenerationHistoryItem)
}