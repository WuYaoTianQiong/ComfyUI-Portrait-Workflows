/**
 * 参考图库数据层（契约 C-REF-ADAPTER@1，DTO 契约 C-REF-ITEM-DTO@2）。
 *
 * 本文件是 React 版 `gallery-web/src/lib/referenceAdapter.ts` 的 Vue 侧平移，
 * 只搬算法语义，不搬 React 组件：
 * - 分页固定 `page_size=200`，先取第 1 页拿 total，其余页最多 6 个 worker 并发；
 * - 按页序合并、按 `id` 去重保序；
 * - 任一页失败整体 reject，错误文本带 library 与 page，不返回半成品；
 * - `null/undefined` 字符串归一为 `''`，`tags` 缺失归一为 `[]`，
 *   `depthUrl/depthThumbUrl` 保留 `null`；
 * - 图片地址一律走 `referenceImageUrl`，禁止把完整 URL 再做一次 `/` 拼接
 *   （历史事故：`//api/...` 被浏览器当成协议相对地址）。
 *
 * 与 React 版的唯一差异是类型写在本地文件、不再从 `types/gallery.ts` 取，
 * 字段名（含中文键名）与取值口径逐字保留。
 */

/** 参考库标识；`costume-anime` 为外链服装库。 */
export type ReferenceLibraryId = 'pose' | 'costume' | 'costume-anime' | 'portrait' | 'hair'

/** 后端 `ReferenceItem` 的 JSON 形状（字段名保持 snake_case）。 */
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
  /** 该条目是否有深度变体；旧响应缺字段按 true 兼容 */
  has_depth?: boolean
  remote: boolean
  /** 仅 pose 非空：上游「姿势编号」 */
  number: string
  /** canonical 三轴字段（仅 pose 非空） */
  source?: string
  /** 来源展示名（如角色创作库署名）；为空时沿用库默认文案 */
  source_label?: string
  composition?: string
  pose_type?: string
  style?: string
  /** 仅 costume-anime 且上游有「来源地址」时非空 */
  source_url: string | null
  /** 仅 hair：正/背面裁切图端点；单面发型为 null */
  hair_front_url?: string | null
  hair_back_url?: string | null
  /** 仅 hair：是否有背面无脸图可用于第 4 槽 */
  hair_usable?: boolean
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

/** 姿势条目（字段口径与 React 版一致）。 */
export interface PoseItem {
  id: string
  体系: string
  姿势编号: string
  分类: string
  姿势名称: string
  角度: string
  缩略图: string
  原图: string
  检索: string
  /** 条目来源库；旧持久化数据可能没有该字段 */
  library?: ReferenceLibraryId
  /** canonical 三轴字段；旧持久化数据缺省按 unknown/未分类处理 */
  source?: string
  composition?: string
  poseType?: string
  style?: string
  /** 是否外链条目（仅 costume-anime 为 true） */
  remote?: boolean
  /** 敏感标记；唯一来源为后端 DTO 的 nsfw 字段 */
  nsfw?: boolean
  /** 后端深度图端点；无深度图时为 null */
  depthUrl?: string | null
  /** 后端深度缩略图端点；无派生缩略图时为 null */
  depthThumbUrl?: string | null
  /** 该条目是否有深度变体；缺省按 true 兼容旧持久化数据 */
  hasDepth?: boolean
}

/** 姿势分组：同一「体系 + 姿势编号」的多个角度归一组。 */
export interface PoseGroup {
  key: string
  system: string
  number: string
  name: string
  category: string
  items: PoseItem[]
  angles: Record<string, PoseItem>
  order: PoseItem[]
}

/** 服装条目（现实库与外链二次元库共用形状，靠 library 区分）。 */
export interface CostumeItem {
  id: string
  分类: string
  一级分类?: '现实' | '二次元'
  服装名称: string
  标签: string[]
  关键词: string
  缩略图: string
  预览图: string
  原图: string
  检索: string
  /** 仅外链二次元条目存在 */
  来源?: string
  /** 仅外链二次元条目存在 */
  来源地址?: string
  /** 仅外链二次元条目存在 */
  日文名称?: string
  /** 敏感标记；唯一来源为后端 DTO 的 nsfw 字段 */
  敏感?: boolean
  library?: 'costume' | 'costume-anime'
  remote?: boolean
  nsfw?: boolean
  /** 外链条目的上游来源页；其他库为 null/undefined */
  sourceUrl?: string | null
}

/** 人像条目。 */
export interface PortraitItem {
  id: string
  分区: string
  发长: string
  发型名称: string
  标题: string
  宽: number
  高: number
  字节数: number
  精选: boolean
  热门: boolean
  缩略图: string
  原图: string
  检索: string
  library?: 'portrait'
  nsfw?: boolean
}

/** 发型条目。 */
export interface HairItem {
  id: string
  分区: string
  视图: string
  标题: string
  标签: string[]
  缩略图: string
  原图: string
  正面: string
  背面: string
  可用于发型槽: boolean
  检索: string
  library?: 'hair'
  nsfw?: boolean
}

/** 图片种类；`depth|depth_thumb` 仅 pose 库支持，`front|back` 仅 hair 库支持。 */
export type ReferenceImageKind = 'thumb' | 'image' | 'depth_thumb' | 'depth' | 'front' | 'back'

/** 后端条目列表端点前缀（不含尾斜杠）。 */
export const REFERENCE_ITEMS_PATH = '/api/reference/items'
/** 与后端 `page_size` 上限一致，满页可减少请求数。 */
export const REFERENCE_PAGE_SIZE = 200
/** 其余页的并发上限（契约要求最多 6 个，不得串行）。 */
export const REFERENCE_MAX_CONCURRENT_PAGES = 6
/** 总页数上限，防止 total 异常导致无限翻页（200 页 × 200 条 = 4 万条）。 */
export const REFERENCE_MAX_PAGES = 200

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
function buildPageUrl(
  library: ReferenceLibraryId,
  page: number,
  filters?: ReferenceQueryFilters,
): string {
  const params = new URLSearchParams({
    library,
    page: String(page),
    page_size: String(REFERENCE_PAGE_SIZE),
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
  const workerCount = Math.min(REFERENCE_MAX_CONCURRENT_PAGES, pages.length)

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
  if (totalPages > REFERENCE_MAX_PAGES) {
    throw new Error(
      `加载参考库 ${library} 失败：总页数 ${totalPages} 超过上限 ${REFERENCE_MAX_PAGES}，已中止分页加载`,
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
  const totalPages = Math.ceil(knownTotal / REFERENCE_PAGE_SIZE)
  assertPageLimit(library, totalPages)

  const restPages = rangePages(2, totalPages)
  const rest = restPages.length > 0 ? await fetchPages(library, restPages, filters) : []
  let pages: ReferenceItemListDto[] = [first, ...rest]

  // total 可能在分页期间变大（上游数据刷新）：最多补拉一轮增量页，避免漏条目或无限循环。
  const observedTotal = pages.reduce((max, page) => Math.max(max, page.total), knownTotal)
  if (observedTotal > knownTotal) {
    knownTotal = observedTotal
    const extendedPages = Math.ceil(knownTotal / REFERENCE_PAGE_SIZE)
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
    source: text(dto.source) || (dto.id.startsWith('psl-') ? 'pose-studio-lite' : 'upstream'),
    composition: text(dto.composition) || 'unknown',
    poseType: text(dto.pose_type) || '未分类',
    style: text(dto.style) || '未分类',
    nsfw: Boolean(dto.nsfw),
    // 深度图端点保留 null；能力位缺省 true（兼容旧响应/旧持久化数据）
    hasDepth: dto.has_depth !== false,
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

/** DTO → 服装条目；`library` 决定本地/外链两条映射分支。 */
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
    item.sourceUrl = dto.source_url ?? null
  } else if (text(dto.source_label)) {
    // 角色创作库等第二来源：卡片 meta-left / 灯箱「来源」直接显示署名。
    // 不写 sourceUrl：它是本地图，下载仍应走后端原图端点。
    item.来源 = text(dto.source_label)
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
    // 页面如需展示尺寸，由视图层决定是否隐藏该行。
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

/** DTO → 发型条目。 */
export function toHairItem(dto: ReferenceItemDto): HairItem {
  const thumb = text(dto.thumb_url)
  return {
    id: dto.id,
    分区: text(dto.group),
    视图: text(dto.facet) || text(dto.subtitle),
    标题: text(dto.name),
    标签: tagList(dto.tags),
    缩略图: thumb,
    原图: text(dto.image_url) || thumb,
    正面: text(dto.hair_front_url),
    背面: text(dto.hair_back_url),
    可用于发型槽: Boolean(dto.hair_usable),
    检索: text(dto.search_text),
    library: 'hair',
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

/**
 * 按后端契约构造图片端点。
 *
 * 关键：路径段先 `encodeURIComponent` 再 `join('/')`。编码后的 library/id
 * 不可能以 `/` 开头，因此不会拼出 `//api/...`；调用方也不得把本函数结果
 * 与任何以 `/` 开头的字符串再做二次拼接。
 */
export function referenceImageEndpoint(
  library: string,
  itemId: string,
  kind: ReferenceImageKind,
): string {
  const segments = [
    REFERENCE_ITEMS_PATH,
    encodeURIComponent(library),
    encodeURIComponent(itemId),
    'image',
  ]
  return `${segments.join('/')}?kind=${kind}`
}

/** 取 DTO 上该 kind 对应的后端下发字段。 */
function dtoImageField(dto: ReferenceItemDto, kind: ReferenceImageKind): string | null {
  const value =
    kind === 'thumb'
      ? dto.thumb_url
      : kind === 'image'
        ? dto.image_url
        : kind === 'depth'
          ? dto.depth_url
          : kind === 'depth_thumb'
            ? dto.depth_thumb_url
            : kind === 'front'
              ? dto.hair_front_url
              : dto.hair_back_url
  return typeof value === 'string' && value.trim().length > 0 ? value : null
}

/**
 * 图片地址统一入口：`kind ∈ thumb|image|depth_thumb|depth`，depth 仅 pose。
 *
 * 口径：
 * - 后端已下发对应 URL 时原样使用（后端保证以 `/api/` 开头）；
 * - `thumb` 缺失但有原图时，构造 thumb 端点（本地库必有缩略图）；
 * - `image` 缺失时回退缩略图地址，避免裂图；
 * - `depth` 仅 pose：非 pose 直接返回 null；pose 缺字段时按契约构造端点；
 * - `depth_thumb` 缺失保持 null —— 后端只在派生缩略图真实存在时下发，
 *   构造默认端点会得到 404，破坏"是否有深度缩略图"的判断；
 * - 完全无图（`costume-anime` 上游缺图）返回 null，调用方据此渲染占位，
 *   绝不产出 `src=""`。
 */
export function referenceImageUrl(dto: ReferenceItemDto, kind: ReferenceImageKind): string | null {
  // 空 id/library 无法构成合法路径；直接返回 null，杜绝拼出 `//image` 这类地址。
  if (!dto.id || !dto.library) return null
  // 深度图只有姿势库有，非 pose 一律不可用，避免给服装/人像构造 404 地址。
  if ((kind === 'depth' || kind === 'depth_thumb') && dto.library !== 'pose') return null
  // 正/背面裁切只有发型库有。
  if ((kind === 'front' || kind === 'back') && dto.library !== 'hair') return null

  const direct = dtoImageField(dto, kind)
  if (direct) return direct

  switch (kind) {
    case 'thumb':
      return dtoImageField(dto, 'image')
        ? referenceImageEndpoint(dto.library, dto.id, 'thumb')
        : null
    case 'image':
      return dtoImageField(dto, 'thumb')
    case 'depth':
      // pose 的深度图是上游固有资源，缺字段时按契约端点取。
      return dto.library === 'pose'
        ? referenceImageEndpoint(dto.library, dto.id, 'depth')
        : null
    case 'depth_thumb':
      return null
    case 'front':
    case 'back':
      return null
  }
}