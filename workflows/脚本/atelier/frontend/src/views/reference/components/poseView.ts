/**
 * 姿势库视图层纯逻辑（阶段 2.1）。
 *
 * 本文件只放「可以脱离 Vue 组件单测」的算法：
 * - 体系药丸 / 分类下拉 / 视角胶囊 / 搜索的筛选语义（逐条对齐 React `poses.tsx`）；
 * - 加载更多的计数与文案（60 组 / 96 张，每次 +60，不是分页）；
 * - 卡片与灯箱的图片地址（统一走 `referenceImageUrl`，禁止二次拼接）。
 *
 * 深度图模式是顶栏、卡片、角度条、灯箱共享的一份状态，因此放在模块级 ref；
 * 它不是持久化状态（不在本阶段落盘），切页签后仍保留当前选择。
 */

import { ref } from 'vue'

import { referenceImageUrl } from '../../../api/reference'
import type { PoseGroup, PoseItem, ReferenceItemDto } from '../../../api/reference'
import { ANGLES } from '../../../composables/useReferenceLibrary'

/** 组内角度展示顺序（§7 冻结：正面/俯视/仰视/侧面/斜侧）。 */
export { ANGLES }

/** 分组视图初始展示 60 组。 */
export const INITIAL_GROUP_COUNT = 60
/** 单张视图初始展示 96 张。 */
export const INITIAL_SINGLE_COUNT = 96
/** 「加载更多」每次追加 60（组或张）。 */
export const LOAD_MORE_STEP = 60

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

/** 筛选条件；空串表示不限制。 */
export interface PoseFilters {
  line: string
  category: string
  angle: string
  query: string
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
  const haystack =
    `${item.姿势名称} ${item.id} ${item.分类} ${item.姿势编号} ${item.体系}`.toLowerCase()
  return haystack.includes(needle)
}

/** 单条目是否命中体系 / 分类 / 视角 / 搜索四类条件。 */
export function matchesPoseFilters(item: PoseItem, filters: PoseFilters): boolean {
  if (filters.line && item.体系 !== filters.line) return false
  // `'all'` 是「全部动作分类」的哨兵值（与 React 的 Select 默认值一致）
  if (filters.category && filters.category !== 'all' && item.分类 !== filters.category) return false
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

/** 加载更多的展示状态。 */
export interface LoadMoreState {
  hasMore: boolean
  /** 还剩多少条未展示（组或张） */
  remaining: number
  /** 按钮文案，带剩余数量 */
  label: string
}

/**
 * 加载更多状态。
 *
 * 注意这是「加载更多」而不是分页：React 版没有页码，只有 60 的步进，
 * 阶段 2.1 不得改用 `Pager`（§7 冻结结论）。
 */
export function loadMoreState(shown: number, total: number, unit: '组' | '张'): LoadMoreState {
  const remaining = Math.max(0, total - shown)
  return {
    hasMore: remaining > 0,
    remaining,
    label: `加载更多（剩余 ${remaining} ${unit}）`,
  }
}

/** 下一次点击「加载更多」后的展示条数；已到末尾时保持不变。 */
export function nextShown(shown: number, total: number, step: number = LOAD_MORE_STEP): number {
  return Math.min(Math.max(0, total), shown + Math.max(1, step))
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
 * - 深度图：优先后端下发的 `depth_thumb`，缺失时退回 `depth`
 *   （与 React `depthThumbUrl ?? depthUrl` 一致）；
 * - 完全无图返回 `null`，调用方渲染占位，绝不产出 `src=""`。
 */
export function poseThumbnailUrl(item: PoseItem, useDepth: boolean): string | null {
  const dto = poseItemDto(item)
  if (!useDepth) return referenceImageUrl(dto, 'thumb')
  return referenceImageUrl(dto, item.depthThumbUrl ? 'depth_thumb' : 'depth')
}

/** 灯箱大图地址：白模 `kind=image`，深度图 `kind=depth`（仅 pose）。 */
export function posePreviewUrl(item: PoseItem, useDepth: boolean): string | null {
  const dto = poseItemDto(item)
  return referenceImageUrl(dto, useDepth ? 'depth' : 'image')
}