/**
 * 参考图库 DTO 适配层（契约 C-REF-ADAPTER@1，DTO 契约 C-REF-ITEM-DTO@2）。
 *
 * 职责：
 * - 分页拉取后端 `GET /api/reference/items` 的全量条目；
 * - 把后端 DTO 还原为页面既有的中文结构，避免三个页面各写一份映射；
 * - 图片 URL 全部使用后端端点（本地库由后端解析文件，外链库由后端缓存/代理）；
 * - 18+ 判定只读 DTO 的 `nsfw` 字段，前端不再硬编码体系/分类名单。
 *
 * 设计要点：
 * - 分页固定 `page_size=200`；首屏请求拿到 total 后，其余页最多 6 个并发，
 *   禁止串行 `for + await`（四库合计约 4.8k 条，串行会明显拖慢首屏）。
 * - 合并按页序拼接，按 id 去重保序，避免重复页造成 React key 冲突。
 * - 任一页失败整体 reject，错误文本带 library 与 page，不返回半成品。
 * - 所有 null 字符串在适配层统一转 ''（depthUrl/depthThumbUrl 保留 null），
 *   `tags` 缺失转 []，避免渲染出 `<img src="undefined">` 或 `src=""`。
 */

import type { CostumeItem, PoseGroup, PoseItem, PortraitItem, ReferenceLibraryId } from '@/types/gallery'

export type { ReferenceLibraryId }

/** 后端 `ReferenceItem` 的 JSON 形状（C-REF-ITEM-DTO@2，字段名保持 snake_case）。 */
export interface ReferenceItemDto {
  id: string
  library: string
  name: string
  subtitle: string
  group: string
  facet: string
  angle: string
  tags: string[]
  keywords: string
  thumb_url: string | null
  image_url: string | null
  depth_url: string | null
  depth_thumb_url: string | null
  hot: boolean
  featured: boolean
  nsfw: boolean
  remote: boolean
  /** 仅 pose 非空：上游「姿势编号」 */
  number: string
  /** 仅 costume-anime 且上游有「来源地址」时非空 */
  source_url: string | null
  /** 与后端过滤一致的预拼检索串（小写前的原文） */
  search_text: string
}

/** 后端 `ReferenceItemListResponse`。 */
export interface ReferenceItemListDto {
  items: ReferenceItemDto[]
  total: number
  page: number
  page_size: number
}

/** 交给后端的可选过滤条件；页面默认不传，保持客户端筛选语义。 */
export interface ReferenceQueryFilters {
  search?: string
  nsfw?: boolean
}

const REFERENCE_ITEMS_PATH = '/api/reference/items'
/** 与后端 `page_size` 上限一致，满页可减少请求数 */
const PAGE_SIZE = 200
/** 其余页的并发上限（契约要求最多 6 个，不得串行） */
const MAX_CONCURRENT_PAGES = 6
/** 总页数上限，防止 total 异常导致无限翻页（200 页 x 200 条 = 4 万条） */
const MAX_PAGES = 200

/** 空值归一：null/undefined/非字符串统一转空串。 */
function text(value: string | null | undefined): string {
  return typeof value === 'string' ? value : ''
}

/** 空值归一：标签缺失转 []，并剔除空串，避免渲染空 badge。 */
function tagList(value: string[] | null | undefined): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((tag): tag is string => typeof tag === 'string' && tag.trim().length > 0)
}

/** 拼一页的请求地址；枚举值不编码，search 由 URLSearchParams 处理。 */
function buildPageUrl(library: ReferenceLibraryId, page: number, filters?: ReferenceQueryFilters): string {
  const params = new URLSearchParams({
    library,
    page: String(page),
    page_size: String(PAGE_SIZE),
  })
  if (filters?.search) params.set('search', filters.search)
  if (typeof filters?.nsfw === 'boolean') params.set('nsfw', String(filters.nsfw))
  return `${REFERENCE_ITEMS_PATH}?${params.toString()}`
}

/**
 * 拉取单页。
 *
 * 失败语义：网络异常、非 2xx、响应不是 JSON、结构异常都抛出带 library/page 的错误，
 * 由 `fetchAllReferenceItems` 整体 reject。
 */
async function fetchPage(
  library: ReferenceLibraryId,
  page: number,
  filters?: ReferenceQueryFilters,
): Promise<ReferenceItemListDto> {
  const prefix = `加载参考库 ${library} 第 ${page} 页失败`

  let response: Response
  try {
    response = await fetch(buildPageUrl(library, page, filters))
  } catch {
    throw new Error(`${prefix}：网络请求失败`)
  }

  if (!response.ok) {
    throw new Error(`${prefix}：HTTP ${response.status}`)
  }

  let body: ReferenceItemListDto
  try {
    body = (await response.json()) as ReferenceItemListDto
  } catch {
    // 开发服务器未代理 /api 时会返回 index.html，按不可读响应处理。
    throw new Error(`${prefix}：响应不是 JSON`)
  }

  if (!body || !Array.isArray(body.items)) {
    throw new Error(`${prefix}：响应结构异常`)
  }

  return body
}

/** 生成 [start, end] 的页号数组；end < start 时返回空数组。 */
function rangePages(start: number, end: number): number[] {
  if (end < start) return []
  const pages: number[] = []
  for (let page = start; page <= end; page += 1) pages.push(page)
  return pages
}

/**
 * 以最多 6 个 worker 并发拉取指定页，结果按入参页序回填。
 *
 * 使用共享游标而不是 `pages.map(fetchPage)`，避免一次性打开上百个请求；
 * 也不用串行 `for + await`，保证首屏时间不被页数线性放大。
 */
async function fetchPages(
  library: ReferenceLibraryId,
  pages: number[],
  filters?: ReferenceQueryFilters,
): Promise<ReferenceItemListDto[]> {
  const results: (ReferenceItemListDto | undefined)[] = Array.from({ length: pages.length })
  let cursor = 0
  const workerCount = Math.min(MAX_CONCURRENT_PAGES, pages.length)

  const workers = Array.from({ length: workerCount }, async () => {
    while (cursor < pages.length) {
      const index = cursor
      cursor += 1
      results[index] = await fetchPage(library, pages[index], filters)
    }
  })

  await Promise.all(workers)
  // 所有页都在上面被赋值；断言仅用于消除 undefined 类型。
  return results as ReferenceItemListDto[]
}

/** 总页数超过上限时抛出明确错误，避免异常 total 造成无限翻页。 */
function assertPageLimit(library: ReferenceLibraryId, totalPages: number): void {
  if (totalPages > MAX_PAGES) {
    throw new Error(
      `加载参考库 ${library} 失败：总页数 ${totalPages} 超过上限 ${MAX_PAGES}，已中止分页加载`,
    )
  }
}

/**
 * 拉取某库的全部条目（契约 C-REF-ADAPTER@1 分页算法）。
 *
 * 1. `page_size=200`，先请求 page=1，用 total 计算总页数；
 * 2. 其余页最多 6 并发；
 * 3. 按页序拼接，按 id 去重保序；
 * 4. 任一页失败整体 reject；
 * 5. total 变大时最多补拉一轮增量页，总页数上限 200。
 */
export async function fetchAllReferenceItems(
  library: ReferenceLibraryId,
  filters?: ReferenceQueryFilters,
): Promise<ReferenceItemDto[]> {
  const first = await fetchPage(library, 1, filters)
  let knownTotal = first.total
  const totalPages = Math.ceil(knownTotal / PAGE_SIZE)
  assertPageLimit(library, totalPages)

  const restPages = rangePages(2, totalPages)
  const rest = restPages.length > 0 ? await fetchPages(library, restPages, filters) : []
  let pages: ReferenceItemListDto[] = [first, ...rest]

  // total 可能在分页期间变大（上游数据刷新）：最多补拉一轮增量页，避免漏条目或无限循环。
  const observedTotal = pages.reduce((max, page) => Math.max(max, page.total), knownTotal)
  if (observedTotal > knownTotal) {
    knownTotal = observedTotal
    const extendedPages = Math.ceil(knownTotal / PAGE_SIZE)
    assertPageLimit(library, extendedPages)
    const missingPages = rangePages(totalPages + 1, extendedPages)
    if (missingPages.length > 0) {
      const extra = await fetchPages(library, missingPages, filters)
      pages = [...pages, ...extra]

    }
  }

  const seen = new Set<string>()
  const merged: ReferenceItemDto[] = []
  for (const page of pages) {
    for (const item of page.items) {
      if (!item || !item.id || seen.has(item.id)) continue
      seen.add(item.id)
      merged.push(item)
    }
  }
  return merged
}

/** DTO → 姿势条目（映射口径见 C-REF-ADAPTER@1 字段映射表）。 */
export function toPoseItem(dto: ReferenceItemDto): PoseItem {
  return {
    id: dto.id,
    体系: text(dto.group),
    姿势编号: text(dto.number),
    分类: text(dto.facet),
    姿势名称: text(dto.name),
    角度: text(dto.angle),
    缩略图: text(dto.thumb_url),
    原图: text(dto.image_url) || text(dto.thumb_url),
    检索: text(dto.search_text),
    library: 'pose',
    remote: false,
    nsfw: Boolean(dto.nsfw),
    // 深度图端点保留 null（页面据此判断是否有深度图）
    depthUrl: text(dto.depth_url) || null,
    depthThumbUrl: text(dto.depth_thumb_url) || null,
  }
}

/**
 * 外链服装库的一级分类收窄。
 *
 * 后端 `costume-anime` 的 `group` 取自上游「一级分类」，正常为「二次元」；
 * 这里做枚举收窄，异常值归入「二次元」，避免污染页面的一级分类筛选。
 */
function animeFirstLevel(dto: ReferenceItemDto): '现实' | '二次元' {
  return dto.group === '现实' ? '现实' : '二次元'
}

/** DTO → 服装条目；`library` 决定免费/外链两条映射分支。 */
export function toCostumeItem(dto: ReferenceItemDto): CostumeItem {
  const anime = dto.library === 'costume-anime'
  const thumb = text(dto.thumb_url)
  const image = text(dto.image_url) || thumb

  const item: CostumeItem = {
    id: dto.id,
    分类: text(anime ? dto.facet : dto.group),
    一级分类: anime ? animeFirstLevel(dto) : '现实',
    服装名称: text(dto.name),
    标签: tagList(dto.tags),
    关键词: text(dto.keywords),
    缩略图: thumb,
    预览图: text(dto.image_url),
    原图: image,
    检索: text(dto.search_text),
    library: anime ? 'costume-anime' : 'costume',
    remote: anime,
    nsfw: Boolean(dto.nsfw),
    敏感: Boolean(dto.nsfw),
  }

  if (anime) {
    item.来源 = 'CharaDB'
    item.日文名称 = text(dto.subtitle)
    item.来源地址 = dto.source_url ?? undefined
    item.source = 'charadb'
    item.sourceUrl = dto.source_url ?? null
  }

  return item
}

/** DTO → 人像条目。 */
export function toPortraitItem(dto: ReferenceItemDto): PortraitItem {
  const thumb = text(dto.thumb_url)
  return {
    id: dto.id,
    分区: text(dto.group),
    发长: text(dto.facet),
    发型名称: text(dto.subtitle),
    标题: text(dto.name),
    // 后端 DTO 未下发原图尺寸/字节数，保持字段必填语义并回填 0；
    // 页面如需展示尺寸，由 T9 决定是否隐藏该行。
    宽: 0,
    高: 0,
    字节数: 0,
    精选: Boolean(dto.featured),
    热门: Boolean(dto.hot),
    缩略图: thumb,
    原图: text(dto.image_url) || thumb,
    检索: text(dto.search_text),
    library: 'portrait',
    nsfw: Boolean(dto.nsfw),
  }
}

/** 姿势条目或分组的 18+ 判定，唯一来源为 `nsfw` 字段。 */
export function isNsfwPoseItem(item: PoseItem | PoseGroup): boolean {
  if ('items' in item) {
    return item.items.some((entry) => Boolean(entry.nsfw))
  }
  return Boolean(item.nsfw)
}

/** 服装条目的 18+ 判定，唯一来源为 `nsfw` 字段。 */
export function isNsfwCostumeItem(item: CostumeItem): boolean {
  return Boolean(item.nsfw)
}

/** 在当前已加载的姿势数组上聚合体系是否含 18+ 条目（用于药丸标记）。 */
export function poseSystemHasNsfw(items: PoseItem[], system: string): boolean {
  return items.some((item) => item.体系 === system && Boolean(item.nsfw))
}

/** 在当前已加载的服装数组上聚合分类是否含 18+ 条目（用于药丸标记）。 */
export function costumeCategoryHasNsfw(items: CostumeItem[], category: string): boolean {
  return items.some((item) => item.分类 === category && Boolean(item.nsfw))
}