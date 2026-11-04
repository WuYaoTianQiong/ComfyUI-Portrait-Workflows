/**
 * AI 参考图库只读接口（M1）。
 *
 * 契约见《AI参考图库_atelier融合计划_20261104》§3：四库统一 DTO、
 * 分页响应 `{items,total,page,page_size}`、图片端点 `kind=thumb|image|depth`。
 * 后端的 `remote` 条目（440 条外链服装）在 DTO 里直接给远程 URL，
 * 前端只做热链展示，不能拿它出图。
 *
 * TODO(gen_api_types): 骨架生成的 openapi.d.ts 还没有 reference schema，
 * 这里的类型先手写；波次 D 由 `tools/gen_api_types.py` 统一替换。
 */
import { apiGet } from './client'

export type ReferenceLibraryKey = 'pose' | 'costume' | 'portrait' | 'costume-anime'
export type ReferenceImageKind = 'thumb' | 'image' | 'depth'

export interface ReferenceFacetValue {
  value: string
  count: number
}

export interface ReferenceLibraryStats {
  library: string
  label: string
  total: number
  local: number
  remote: number
  /** NSFW 过滤后当前可见的条数（默认过滤敏感分类）。 */
  visible: number
  available: boolean
  groups: ReferenceFacetValue[]
  facets: ReferenceFacetValue[]
  angles: ReferenceFacetValue[]
}

export interface ReferenceLibraryListResponse {
  libraries: ReferenceLibraryStats[]
}

export interface ReferenceItem {
  id: string
  library: string
  name: string
  subtitle: string
  group: string
  facet: string
  angle: string
  tags: string[]
  keywords: string
  thumb_url: string
  image_url: string
  depth_url: string | null
  hot: boolean
  featured: boolean
  nsfw: boolean
  remote: boolean
}

export interface ReferenceItemPage {
  items: ReferenceItem[]
  total: number
  page: number
  page_size: number
}

export interface ReferenceItemQuery {
  library: string
  search?: string
  group?: string
  facet?: string
  angle?: string
  /** false = 只看非敏感；true = 只看敏感；不传 = 全部（仅 ALLOW_NSFW=1 时有效）。 */
  nsfw?: boolean | null
  page?: number
  page_size?: number
}

export function listReferenceLibraries(): Promise<ReferenceLibraryListResponse> {
  return apiGet<ReferenceLibraryListResponse>('/api/reference/libraries')
}

export function listReferenceItems(query: ReferenceItemQuery): Promise<ReferenceItemPage> {
  return apiGet<ReferenceItemPage>('/api/reference/items', {
    library: query.library,
    search: query.search,
    group: query.group,
    facet: query.facet,
    angle: query.angle,
    // false 是有效值（只看非敏感），buildQuery 不会跳过
    nsfw: query.nsfw ?? undefined,
    page: query.page,
    page_size: query.page_size,
  })
}

export function getReferenceItem(library: string, id: string): Promise<ReferenceItem> {
  return apiGet<ReferenceItem>(
    `/api/reference/items/${encodeURIComponent(library)}/${encodeURIComponent(id)}`,
  )
}

/** 从 DTO 里取对应版本的图片地址；外链条目的深度图为 null。 */
export function referenceImageUrl(item: ReferenceItem, kind: ReferenceImageKind): string {
  if (kind === 'depth') return item.depth_url ?? ''
  if (kind === 'image') return item.image_url
  return item.thumb_url
}

/** 姿势卡片的「姿势编号」：subtitle 形如 `P001 · 正面`。 */
export function poseCodeOf(item: ReferenceItem): string {
  if (item.library !== 'pose') return ''
  const code = (item.subtitle.split('·')[0] ?? '').trim()
  return /^[A-Za-z]+\d+$/.test(code) ? code : ''
}