/**
 * 人像库视图层纯逻辑（阶段 2.3a）。
 *
 * 本文件只放「可以脱离 Vue 组件单测」的算法，逐条对齐 React
 * `gallery-web/src/routes/portraits.tsx`（363 行）与施工手册 §7 人像 4 行：
 * - 分区（正脸参考 / 造型氛围）与发长（短发 / 中发 / 中长发 / 长发）药丸，
 *   **再次点击同一项取消**；药丸数量按全库条目统计，不受当前筛选影响；
 * - 发型细分下拉按「当前分区 + 发长」联动收窄，中文排序；
 * - 搜索匹配以 `检索` 串为主（后端已拼入 id / 分区 / 发长 / 发型名称），
 *   附加 id 兜底，保证「搜 ID」一定可用；
 * - 分页切片与每页条数归一复用姿势库的共用实现（三库口径一致）；
 * - 灯箱前后翻页在筛选结果内循环；
 * - 图片地址一律走 `referenceImageUrl`，禁止二次拼接（§0 铁律 5 / §9 R7），
 *   无图返回 null，由卡片 / 灯箱渲染占位。
 *
 * 不做精选 / 热门：§7 已冻结「不迁移」，React 侧本就没有渲染这两个字段。
 */

import { referenceImageUrl } from '../../../api/reference'
import type { PortraitItem, ReferenceItemDto } from '../../../api/reference'

// 分页切片 / 页码夹取是姿势、服装、人像共用的通用算法，直接复用姿势库实现。
export {
  DEFAULT_PAGE_SIZE,
  PAGE_SIZES,
  PAGE_SIZE_STORAGE_KEY,
  clampPage,
  loadReferencePageSize,
  normalizePageSize,
  pageCount,
  pageSlice,
  saveReferencePageSize,
} from './poseView'

/** 分区枚举与展示顺序（与 React 的 `(['正脸参考','造型氛围'] as const)` 一致）。 */
export const PORTRAIT_SECTIONS = ['正脸参考', '造型氛围'] as const

/** 发长枚举与展示顺序（与 React 的 `HAIRS` 一致）。 */
export const PORTRAIT_HAIRS = ['短发', '中发', '中长发', '长发'] as const

/** 发型下拉「全部」的哨兵值（与 React 的 `styleName = 'all'` 一致）。 */
export const ALL_STYLES = 'all'

/** 人像筛选条件；空串 / `ALL_STYLES` 表示不限制。 */
export interface PortraitFilters {
  /** 分区；空串 = 全部分区 */
  section: string
  /** 发长；空串 = 全部发长 */
  hair: string
  /** 发型名称；`ALL_STYLES` = 全部发型 */
  styleName: string
  /** 搜索词 */
  query: string
}

/** 药丸 / 下拉的计数项。 */
export interface PortraitCountItem {
  value: string
  count: number
}

/** 搜索归一：去首尾空白 + 小写；空串表示不限制。 */
export function normalizePortraitQuery(query: string): string {
  return query.trim().toLowerCase()
}

/**
 * 单条目搜索匹配。
 *
 * React 只匹配 `item.检索`；这里额外拼上 `id`，因为上游 `检索` 字段是
 * 预生成串，个别条目可能不含 id，而页面提示明确让用户「搜索 … 或 ID」。
 * 其余字段（分区 / 发长 / 发型名称）后端已拼进 `检索`，不重复叠加。
 */
export function matchesPortraitQuery(item: PortraitItem, query: string): boolean {
  const needle = normalizePortraitQuery(query)
  if (!needle) return true
  const haystack = `${item.检索} ${item.id}`.toLowerCase()
  return haystack.includes(needle)
}

/** 单条目是否命中分区 / 发长 / 发型 / 搜索四类条件（AND）。 */
export function matchesPortraitFilters(item: PortraitItem, filters: PortraitFilters): boolean {
  if (filters.section && item.分区 !== filters.section) return false
  if (filters.hair && item.发长 !== filters.hair) return false
  if (filters.styleName !== ALL_STYLES && item.发型名称 !== filters.styleName) return false
  return matchesPortraitQuery(item, filters.query)
}

/** 列表筛选：逐条过滤，语义与 React 的 `filtered` 一致。 */
export function filterPortraits(items: PortraitItem[], filters: PortraitFilters): PortraitItem[] {
  return items.filter((item) => matchesPortraitFilters(item, filters))
}

/**
 * 药丸「再次点击取消」的语义：点中当前项 → 空串（全部），否则切到该项。
 *
 * 分区与发长各自独立生效（可同时选中），与 React 的分段 state 一致。
 */
export function togglePortraitSection(current: string, next: string): string {
  return current === next ? '' : next
}

/** 发长药丸的二次点击取消；见 `togglePortraitSection`。 */
export function togglePortraitHair(current: string, next: string): string {
  return current === next ? '' : next
}

/** 各分区在全库中的条目数；顺序固定 `PORTRAIT_SECTIONS`。 */
export function portraitSectionCounts(items: PortraitItem[]): PortraitCountItem[] {
  return PORTRAIT_SECTIONS.map((value) => ({
    value,
    count: items.filter((item) => item.分区 === value).length,
  }))
}

/** 各发长在全库中的条目数；顺序固定 `PORTRAIT_HAIRS`。 */
export function portraitHairCounts(items: PortraitItem[]): PortraitCountItem[] {
  return PORTRAIT_HAIRS.map((value) => ({
    value,
    count: items.filter((item) => item.发长 === value).length,
  }))
}

/**
 * 发型细分下拉选项：按「当前分区 + 当前发长」收窄，去空、按中文排序。
 *
 * 逐条平移 React 的 `styleOptions`：`localeCompare(a, b, 'zh-CN')`，
 * 收窄发生在分区 / 发长变化后，因此下拉项会实时变少。
 */
export function portraitStyleOptions(
  items: PortraitItem[],
  section: string,
  hair: string,
): string[] {
  const scoped = items.filter(
    (item) => (!section || item.分区 === section) && (!hair || item.发长 === hair),
  )
  return [...new Set(scoped.map((item) => item.发型名称).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, 'zh-CN'),
  )
}

/**
 * 当前生效的发型筛选。
 *
 * 分区 / 发长变化后如果原选项已不在收窄结果里，自动落回「全部」，
 * 避免出现「下拉显示一个不存在的选项、列表却是空的」。
 */
export function activePortraitStyle(current: string, options: string[]): string {
  if (current === ALL_STYLES) return current
  return options.includes(current) ? current : ALL_STYLES
}


/**
 * 灯箱前后翻页：在筛选结果内循环。
 *
 * `total <= 0` 返回 0；越界下标先归一，保证任何情况下都落在合法范围。
 */
export function stepPortraitIndex(index: number, delta: number, total: number): number {
  if (total <= 0) return 0
  const base = ((Math.trunc(index) % total) + total) % total
  return ((base + Math.trunc(delta)) % total + total) % total
}

/** 原图尺寸文案；宽高缺失（后端未下发 / 尚未测得）时显示「—」，不显示 `0 × 0`。 */
export function formatPortraitSize(width: number, height: number): string {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return '—'
  }
  return `${Math.round(width)} × ${Math.round(height)}`
}

/**
 * 把视图层的人像条目还原成 `ReferenceItemDto`，交给 `referenceImageUrl`。
 *
 * 数据层映射把 DTO 压成了中文键，图片地址的唯一出口仍必须是
 * `referenceImageUrl`；`library` 固定 `portrait`，`subtitle` 是发型名称。
 */
export function portraitItemDto(item: PortraitItem): ReferenceItemDto {
  return {
    id: item.id,
    library: 'portrait',
    name: item.标题,
    subtitle: item.发型名称,
    group: item.分区,
    facet: item.发长,
    angle: '',
    tags: [],
    keywords: '',
    thumb_url: item.缩略图 || null,
    image_url: item.原图 || null,
    depth_url: null,
    depth_thumb_url: null,
    // 精选 / 热门不参与 UI（§7 冻结），仅按原值回填以保持 DTO 形状完整。
    hot: item.热门,
    featured: item.精选,
    nsfw: Boolean(item.nsfw),
    remote: false,
    number: '',
    source_url: null,
    search_text: item.检索,
  }
}

/**
 * 卡片缩略图地址（`kind=thumb`）。
 *
 * 缩略图缺失但有原图时，`referenceImageUrl` 会按契约构造 thumb 端点；
 * 完全无图返回 null，卡片渲染占位，绝不输出 `src=""`。
 */
export function portraitThumbnailUrl(item: PortraitItem): string | null {
  return referenceImageUrl(portraitItemDto(item), 'thumb')
}

/** 灯箱大图地址（`kind=image`）；缺失时由 `referenceImageUrl` 回退缩略图。 */
export function portraitPreviewUrl(item: PortraitItem): string | null {
  return referenceImageUrl(portraitItemDto(item), 'image')
}