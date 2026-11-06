/**
 * 姿势库视图层纯逻辑（阶段 2.1）。
 *
 * 本文件只放「可以脱离 Vue 组件单测」的算法：
 * - 体系药丸 / 分类下拉 / 视角胶囊 / 搜索的筛选语义（逐条对齐 React `poses.tsx`）；
 * - 三库共用的分页切片（每页 20 / 60 / 100 / 200，页码从 1 开始）；
 * - 卡片与灯箱的图片地址（统一走 `referenceImageUrl`，禁止二次拼接）。
 *
 * 深度图模式是顶栏、卡片、角度条、灯箱共享的一份状态，因此放在模块级 ref；
 * 它不是持久化状态（不在本阶段落盘），切页签后仍保留当前选择。
 */

import { ref } from 'vue'

import { referenceImageUrl } from '../../../api/reference'
import type { PoseGroup, PoseItem, ReferenceItemDto } from '../../../api/reference'
import { ANGLES } from '../../../composables/useReferenceLibrary'
import { readSession, writeSession } from '../../../composables/useSessionState'

/** 组内角度展示顺序（§7 冻结：正面/俯视/仰视/侧面/斜侧）。 */
export { ANGLES }

/** 每页条数下拉的合法取值。 */
export const PAGE_SIZES = [20, 60, 100, 200] as const

/** 默认每页 60 条（与旧「首屏 60」口径一致）。 */
export const DEFAULT_PAGE_SIZE = 60

/** 三库共用的每页条数记忆键（值形如 `{ pageSize: 60 }`）。 */
export const PAGE_SIZE_STORAGE_KEY = 'pb.reference_page_size_v1'

/** 每页条数本地存档的形状。 */
export interface ReferencePageSizeSession {
  pageSize: number
}

/**
 * 每页条数归一：只接受 20 / 60 / 100 / 200，其余（缺失、脏值、0、非数字）一律回落 60。
 */
export function normalizePageSize(value: unknown): number {
  const candidate = Number(value)
  return (PAGE_SIZES as readonly number[]).includes(candidate) ? candidate : DEFAULT_PAGE_SIZE
}

/**
 * 按页切片：页码从 1 开始，`page = 1` 返回前 `pageSize` 条。
 *
 * 页码与每页条数先归一（非法页码回 1、非法条数回 60），
 * 所以越界页返回空数组而不是把负数下标透给 `slice`。
 */
export function pageSlice<T>(items: readonly T[], page: number, pageSize: number): T[] {
  const size = normalizePageSize(pageSize)
  const safePage = Number.isFinite(page) ? Math.max(1, Math.trunc(page)) : 1
  const start = (safePage - 1) * size
  return items.slice(start, start + size)
}

/** 总页数：向上取整，空列表也至少 1 页（分页条不会显示「第 1 / 0 页」）。 */
export function pageCount(total: number, pageSize: number): number {
  const size = normalizePageSize(pageSize)
  const count = Number.isFinite(total) ? Math.max(0, Math.trunc(total)) : 0
  return Math.max(1, Math.ceil(count / size))
}

/**
 * 页码夹取：筛选后结果变少时把当前页夹到最后一个合法页。
 *
 * 非法页码（0 / 负数 / NaN）统一回第 1 页；空结果为 1。
 */
export function clampPage(page: number, total: number, pageSize: number): number {
  const last = pageCount(total, pageSize)
  const current = Number.isFinite(page) ? Math.max(1, Math.trunc(page)) : 1
  return Math.min(current, last)
}

/** 读取三库共用的每页条数；读写失败或脏值回落 60。 */
export function loadReferencePageSize(): number {
  try {
    const saved = readSession<ReferencePageSizeSession>(PAGE_SIZE_STORAGE_KEY, {
      pageSize: DEFAULT_PAGE_SIZE,
    })
    return normalizePageSize(saved.pageSize)
  } catch {
    return DEFAULT_PAGE_SIZE
  }
}

/** 写入三库共用的每页条数（用户在任一库改动，另两库下次进入沿用）。 */
export function saveReferencePageSize(pageSize: number): void {
  writeSession(PAGE_SIZE_STORAGE_KEY, { pageSize: normalizePageSize(pageSize) })
}

/**
 * 深度图模式：`false` 素体白模、`true` 深度图。
 *
 * 顶栏分段按钮与灯箱内分段共享这一份状态（React 的 `poseDepthMode`），
 * 避免两处各存一份出现「顶栏切了、灯箱没切」。
 */
export const poseDepthMode = ref(false)

/** 修改深度图模式（供顶栏 / 灯箱 / 未来的合成台共用）。 */
export function setPoseDepthMode(value: boolean): void {
  poseDepthMode.value = value
}

/** 筛选条件；空串表示不限制。新三轴字段与旧体系/分类字段并存，旧字段仅兼容旧调用。 */
export interface PoseFilters {
  /** 构图：'' / full / upper / pair */
  composition?: string
  /** 来源：'' / upstream / pose-studio-lite */
  source?: string
  /** 分级：'' / general / nsfw */
  rating?: string
  /** 姿势类型：'all' 或 canonical 值 */
  poseType?: string
  /** 风格：'all' 或 canonical 值 */
  style?: string
  angle: string
  query: string
  /** @deprecated 旧「体系」筛选；新 UI 不再使用 */
  line?: string
  /** @deprecated 旧「动作分类」筛选；新 UI 不再使用 */
  category?: string
}

/** 构图胶囊的展示信息；count 是**姿势组数**，不是图片数。 */
export interface PoseCompositionSummary {
  key: string
  label: string
  count: number
  images: number
}

export const COMPOSITION_OPTIONS = [
  { key: '', label: '全部' },
  { key: 'full', label: '全身单人' },
  { key: 'upper', label: '上半身单人' },
  { key: 'pair', label: '双人' },
  { key: 'unknown', label: '未分类' },
] as const

const POSE_TYPE_ORDER = [
  '站立',
  '坐姿',
  '跪姿',
  '躺卧',
  '蹲姿',
  '前倾',
  '后仰',
  '扭转',
  '上半身',
  '特殊',
  '未分类',
] as const

const STYLE_ORDER = ['标准', '性感', '可爱', '胸线强调', '特殊', '未分类'] as const

/** 条目来源；旧数据没有 source 时按 `psl-` 前缀兜底。 */
export function poseSourceOf(item: PoseItem): string {
  return item.source || (item.id.startsWith('psl-') ? 'pose-studio-lite' : 'upstream')
}

/** 条目构图；旧数据缺字段时归为 unknown。 */
export function poseCompositionOf(item: PoseItem): string {
  return item.composition || 'unknown'
}

/** 条目姿势类型；旧数据缺字段时归为未分类。 */
export function poseTypeOf(item: PoseItem): string {
  return item.poseType || '未分类'
}

/** 条目风格；旧数据缺字段时归为未分类。 */
export function poseStyleOf(item: PoseItem): string {
  return item.style || '未分类'
}

/** 分级匹配：''/all 不加限制。 */
function matchesRating(item: PoseItem, rating?: string): boolean {
  if (!rating || rating === 'all') return true
  if (rating === 'general') return !item.nsfw
  if (rating === 'nsfw') return Boolean(item.nsfw)
  return true
}

/** 三个筛选轴（来源/分级/构图）的上下文匹配，供类型/风格选项收窄。 */
function matchesPoseContext(item: PoseItem, filters: PoseFilters): boolean {
  if (filters.source && poseSourceOf(item) !== filters.source) return false
  if (filters.composition && poseCompositionOf(item) !== filters.composition) return false
  return matchesRating(item, filters.rating)
}

/** 体系药丸的展示信息。 */
export interface PoseSystemSummary {
  /** 体系（一级分类）名 */
  line: string
  /** 该体系在**全部已加载条目**中的数量（与 React 一致，不受筛选影响） */
  count: number
  /** 该体系是否含 18+ 条目：决定 ` · 18+` 文本后缀 */
  nsfw: boolean
  /** 安全模式下是否可见（含敏感条目的体系整体隐藏） */
  visible: boolean
}

/** 搜索归一：去首尾空白 + 小写；空串表示不限制。 */
export function normalizePoseQuery(query: string): string {
  return query.trim().toLowerCase()
}

/**
 * 单条目的搜索匹配。
 *
 * 与 React 一致：把「姿势名称 / id / 分类 / 姿势编号 / 体系」拼成一个串做
 * 子串匹配；不做分词、不匹配标签（姿势 DTO 没有标签）。
 */
export function matchesPoseQuery(item: PoseItem, query: string): boolean {
  const needle = normalizePoseQuery(query)
  if (!needle) return true
  const sourceLabel = poseSourceOf(item) === 'pose-studio-lite' ? '扩展库' : '原图库'
  const haystack =
    `${item.姿势名称} ${item.id} ${item.分类} ${item.姿势编号} ${item.体系} ` +
    `${sourceLabel} ${poseCompositionOf(item)} ${poseTypeOf(item)} ${poseStyleOf(item)}`
  return haystack.toLowerCase().includes(needle)
}

/** 单条目是否命中来源/分级/构图/类型/风格/视角/搜索。 */
export function matchesPoseFilters(item: PoseItem, filters: PoseFilters): boolean {
  // 旧字段兼容：旧 UI / 旧测试仍可只传 line/category。
  if (filters.line && item.体系 !== filters.line) return false
  if (filters.category && filters.category !== 'all' && item.分类 !== filters.category) return false
  if (!matchesPoseContext(item, filters)) return false
  if (filters.poseType && filters.poseType !== 'all' && poseTypeOf(item) !== filters.poseType) {
    return false
  }
  if (filters.style && filters.style !== 'all' && poseStyleOf(item) !== filters.style) {
    return false
  }
  if (filters.angle && item.角度 !== filters.angle) return false
  return matchesPoseQuery(item, filters.query)
}

/**
 * 分组视图筛选。
 *
 * 与 React 一致：体系 / 分类按**组**过滤，角度与搜索只要组内**任一角度**
 * 命中即保留整组（角度条仍展示全部角度，便于切换对照）。
 */
export function filterPoseGroups(groups: PoseGroup[], filters: PoseFilters): PoseGroup[] {
  const needle = normalizePoseQuery(filters.query)
  return groups.filter((group) => {
    if (filters.line && group.system !== filters.line) return false
    if (filters.category && filters.category !== 'all' && group.category !== filters.category) return false
    const head = group.items[0]
    if (!head) return false
    // 组内同一体系/编号的 canonical 字段应一致；取首条即可。
    if (filters.source && poseSourceOf(head) !== filters.source) return false
    if (filters.composition && poseCompositionOf(head) !== filters.composition) return false
    if (!matchesRating(head, filters.rating)) return false
    if (filters.poseType && filters.poseType !== 'all' && poseTypeOf(head) !== filters.poseType) {
      return false
    }
    if (filters.style && filters.style !== 'all' && poseStyleOf(head) !== filters.style) {
      return false
    }
    return group.items.some((item) => {
      if (filters.angle && item.角度 !== filters.angle) return false
      if (needle && !matchesPoseQuery(item, needle)) return false
      return true
    })
  })
}

/** 单张视图筛选：逐条目过滤，语义与分组视图的「组内命中」一致。 */
export function filterPoseSingles(items: PoseItem[], filters: PoseFilters): PoseItem[] {
  return items.filter((item) => matchesPoseFilters(item, filters))
}

/**
 * 动作分类下拉选项。
 *
 * 来源是「安全模式过滤后 + 当前体系收窄后」的条目，按中文排序，
 * 与 React 的 `categories` 一致；空分类剔除，避免出现空选项。
 */
export function poseCategoryOptions(items: PoseItem[], activeLine: string): string[] {
  const scoped = activeLine ? items.filter((item) => item.体系 === activeLine) : items
  return [...new Set(scoped.map((item) => item.分类).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, 'zh-CN'),
  )
}

function sortByOrder(values: string[], order: readonly string[]): string[] {
  const rank = new Map(order.map((value, index) => [value, index]))
  return values.sort((a, b) => {
    const ra = rank.get(a)
    const rb = rank.get(b)
    if (ra !== undefined || rb !== undefined) return (ra ?? 999) - (rb ?? 999)
    return a.localeCompare(b, 'zh-CN')
  })
}

/**
 * 构图胶囊（三轴的一级筛选）。
 *
 * 计数单位是**姿势组数**，不是图片数；来源/分级会改变计数，构图本身不改变。
 */
export function compositionSummaries(
  groups: PoseGroup[],
  filters: Pick<PoseFilters, 'source' | 'rating'> = {},
): PoseCompositionSummary[] {
  const counts = new Map<string, { count: number; images: number }>()
  for (const group of groups) {
    const head = group.items[0]
    if (!head) continue
    if (filters.source && poseSourceOf(head) !== filters.source) continue
    if (!matchesRating(head, filters.rating)) continue
    const key = poseCompositionOf(head)
    const entry = counts.get(key) ?? { count: 0, images: 0 }
    entry.count += 1
    entry.images += group.items.length
    counts.set(key, entry)
  }
  return COMPOSITION_OPTIONS.filter((option) => option.key !== 'unknown' || counts.has('unknown'))
    .map((option) => {
      if (option.key === '') {
        const all = [...counts.values()]
        return {
          key: '',
          label: option.label,
          count: all.reduce((sum, entry) => sum + entry.count, 0),
          images: all.reduce((sum, entry) => sum + entry.images, 0),
        }
      }
      const entry = counts.get(option.key)
      return {
        key: option.key,
        label: option.label,
        count: entry?.count ?? 0,
        images: entry?.images ?? 0,
      }
    })
}

/** 姿势类型选项：来源/分级/构图收窄；不按当前 poseType 收窄。
 *
 * 构图=全部时不把双人体位混进下拉：先选「双人」再选体位；若当前过滤后只剩双人，
 * 则回退到双人体位，避免下拉为空。
 */
export function poseTypeOptions(items: PoseItem[], filters: PoseFilters): string[] {
  const scoped = items.filter((item) => matchesPoseContext(item, filters))
  const nonPair = filters.composition
    ? scoped
    : scoped.filter((item) => poseCompositionOf(item) !== 'pair')
  const sourceItems = nonPair.length > 0 ? nonPair : scoped
  return sortByOrder(
    [...new Set(sourceItems.map((item) => poseTypeOf(item)).filter(Boolean))],
    POSE_TYPE_ORDER,
  )
}

/** 风格选项：来源/分级/构图/姿势类型收窄；不按当前 style 收窄。 */
export function styleOptions(items: PoseItem[], filters: PoseFilters): string[] {
  const scoped = items.filter((item) => {
    if (!matchesPoseContext(item, filters)) return false
    if (filters.poseType && filters.poseType !== 'all' && poseTypeOf(item) !== filters.poseType) {
      return false
    }
    return true
  })
  return sortByOrder([...new Set(scoped.map((item) => poseStyleOf(item)).filter(Boolean))], STYLE_ORDER)
}

/** 安全模式下被隐藏的 18+ 姿势组数（用于「解锁」胶囊文案）。 */
export function hiddenNsfwGroupCount(groups: PoseGroup[]): number {
  return groups.filter((group) => group.items.some((item) => Boolean(item.nsfw))).length
}

/**
 * 体系药丸列表。
 *
 * - 数量按**全部条目**统计（含被安全模式隐藏的条目），与 React 的 `cnt` 一致；
 * - `nsfw` 决定药丸文本后缀 ` · 18+`；
 * - 安全模式下含敏感条目的体系整体不可见（`visible=false`），由调用方决定是否渲染。
 */
export function poseSystemSummaries(
  lines: string[],
  items: PoseItem[],
  safeMode: boolean,
): PoseSystemSummary[] {
  const counts = new Map<string, number>()
  const risky = new Set<string>()
  for (const item of items) {
    counts.set(item.体系, (counts.get(item.体系) ?? 0) + 1)
    if (item.nsfw) risky.add(item.体系)
  }
  return lines.map((line) => {
    const nsfw = risky.has(line)
    return {
      line,
      count: counts.get(line) ?? 0,
      nsfw,
      visible: !safeMode || !nsfw,
    }
  })
}

/**
 * 实际生效的体系筛选。
 *
 * 安全模式下如果当前选中的体系含 18+，自动落回「全部」，
 * 避免切回安全模式后仍显示被隐藏体系的空列表（React `activeLine`）。
 */
export function resolveActiveLine(
  line: string,
  safeMode: boolean,
  items: PoseItem[],
): string {
  if (!safeMode || !line) return line
  const hasNsfw = items.some((item) => item.体系 === line && Boolean(item.nsfw))
  return hasNsfw ? '' : line
}

/** 安全模式下被隐藏的 18+ 条目数（用于「解锁」药丸文案）。 */
export function hiddenNsfwCount(items: PoseItem[]): number {
  return items.filter((item) => Boolean(item.nsfw)).length
}

/** 数据中第一个含 18+ 条目的体系；全部安全时为空串。 */
export function firstNsfwLine(lines: string[], items: PoseItem[]): string {
  return lines.find((line) => items.some((item) => item.体系 === line && Boolean(item.nsfw))) ?? ''
}


/** 卡片上当前生效的角度：鼠标悬停 / 点击过的角度优先，其次是筛选视角，最后取组内首张。 */
export function activeGroupItem(
  group: PoseGroup,
  overrides: Record<string, string>,
  angle: string,
): PoseItem | undefined {
  const override = overrides[group.key]
  if (override && group.angles[override]) return group.angles[override]
  if (angle && group.angles[angle]) return group.angles[angle]
  return group.order[0]
}

/** 组内某个角度对应的条目；没有该角度时返回 undefined（角度条该格留空）。 */
export function groupAngleItem(group: PoseGroup, angle: string): PoseItem | undefined {
  return group.angles[angle]
}

/** 单张视图点开灯箱时，定位到条目所属分组的下标；找不到返回 0（与 React `Math.max(0, gIdx)` 一致）。 */
export function groupIndexOfItem(groups: PoseGroup[], itemId: string): number {
  const index = groups.findIndex((group) => group.items.some((item) => item.id === itemId))
  return index < 0 ? 0 : index
}

/** 组内按顺序翻页：`direction = 1` 下一角度，`-1` 上一角度，循环。 */
export function stepGroupItem(group: PoseGroup, currentId: string, direction: number): PoseItem | undefined {
  if (group.order.length === 0) return undefined
  const index = group.order.findIndex((item) => item.id === currentId)
  const base = index < 0 ? 0 : index
  return group.order[(base + direction + group.order.length) % group.order.length]
}

/**
 * 把视图层的姿势条目还原成 `ReferenceItemDto` 形状，交给 `referenceImageUrl`。
 *
 * 数据层把 DTO 映射成中文键条目时丢掉了 `library` 之外的原始字段名，
 * 但图片地址的唯一出口必须是 `referenceImageUrl`（§0 铁律 5 / §9 R7），
 * 所以这里按字段语义原样回填。`library` 固定 `pose` —— 深度图仅 pose 可用。
 */
export function poseItemDto(item: PoseItem): ReferenceItemDto {
  return {
    id: item.id,
    library: 'pose',
    name: item.姿势名称,
    subtitle: '',
    group: item.体系,
    facet: item.分类,
    angle: item.角度,
    tags: [],
    keywords: '',
    thumb_url: item.缩略图 || null,
    image_url: item.原图 || null,
    depth_url: item.depthUrl ?? null,
    depth_thumb_url: item.depthThumbUrl ?? null,
    hot: false,
    featured: false,
    nsfw: Boolean(item.nsfw),
    has_depth: item.hasDepth !== false,
    remote: false,
    number: item.姿势编号,
    source_url: null,
    search_text: item.检索,
  }
}

/**
 * 卡片 / 角度条缩略图地址。
 *
 * - 白模：`kind=thumb`；
 * - 深度图：优先 `depth_thumb`，缺失退回 `depth`；
 * - 该条目根本没有深度图时回退白模（PSL 等多来源姿势没有深度变体）；
 * - 完全无图返回 `null`，调用方渲染占位，绝不产出 `src=""`。
 */
export function poseThumbnailUrl(item: PoseItem, useDepth: boolean): string | null {
  const dto = poseItemDto(item)
  if (!useDepth || item.hasDepth === false) {
    return referenceImageUrl(dto, 'thumb')
  }
  return referenceImageUrl(dto, item.depthThumbUrl ? 'depth_thumb' : 'depth')
}

/** 灯箱大图地址：白模 `kind=image`；无深度条目即使切到深度模式也回退原图。 */
export function posePreviewUrl(item: PoseItem, useDepth: boolean): string | null {
  const dto = poseItemDto(item)
  if (!useDepth || item.hasDepth === false) {
    return referenceImageUrl(dto, 'image')
  }
  return referenceImageUrl(dto, 'depth')
}