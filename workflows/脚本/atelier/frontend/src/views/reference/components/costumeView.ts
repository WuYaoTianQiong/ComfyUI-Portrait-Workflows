/**
 * 服装库视图层纯逻辑（阶段 2.2）。
 *
 * 本文件只放「可以脱离 Vue 组件单测」的算法，逐条平移 React
 * `gallery-web/src/routes/costumes.tsx`：
 * - 一级分类（全部 / 现实 / 二次元）收窄；
 * - 分类药丸（计数 + ` · 18+` 文本后缀）与标签下拉 `allTags` 的联动；
 * - 搜索（只匹配后端预拼的 `检索` 串，与 React 一致）；
 * - 加载更多（初始 60、每次 +60，**不是分页**）；
 * - 图片地址（唯一出口 `referenceImageUrl`，禁止二次拼接）；
 * - 外链来源标注与下载分流（CharaDB 不提供下载，现实条目可下载）。
 *
 * 安全模式、选中态、灯箱下标等展示状态留在 `ReferenceCostumesTab.vue`。
 */

import {
  costumeCategoryHasNsfw,
  referenceImageUrl,
} from '../../../api/reference'
import type { CostumeItem, ReferenceItemDto } from '../../../api/reference'

// 加载更多的计数 / 步进是姿势与服装共用的通用算法，直接复用阶段 2.1 的实现，
// 不在这里重造一份（避免两套口径漂移）。
import { loadMoreState, nextShown } from './poseView'
import type { LoadMoreState } from './poseView'

/** 一级分类按钮组；「全部」是不限。 */
export const COSTUME_KINDS = ['全部', '现实', '二次元'] as const
export type CostumeKind = (typeof COSTUME_KINDS)[number]

/** 初始展示 60 套（与 React `useState(60)` 一致）。 */
export const INITIAL_COSTUME_COUNT = 60
/** 「加载更多」每次追加 60 套（与 React `setShown((s) => s + 60)` 一致）。 */
export const COSTUME_LOAD_STEP = 60

/** 标签下拉的「全部」哨兵值（与 React 的 `tag === 'all'` 一致）。 */
export const COSTUME_ALL_TAGS = 'all'

/** 外链条目的来源名（React 适配层固定写入 `来源 = 'CharaDB'`）。 */
export const REMOTE_COSTUME_SOURCE = 'CharaDB'
/** 现实条目的来源兜底文案（React 卡片：`item.来源 || 'ギア · 现实服装'`）。 */
export const REAL_COSTUME_SOURCE = 'ギア · 现实服装'
/** 外链素材说明（React 弹窗原文）。 */
export const REMOTE_COSTUME_NOTE = '二次元素材 · 仅作参考，请勿再分发'

/** 搜索栏占位文案（与 React 逐字一致）。 */
export const COSTUME_SEARCH_PLACEHOLDER =
  '搜索服装款式、颜色、材质、英文词条 (如 denim, lace, 针织, 迷你裙)…'

/** 分类药丸展示信息。 */
export interface CostumeCategorySummary {
  name: string
  /** 在**当前一级分类 + 安全模式**范围内的条目数（React `cnt`） */
  count: number
  /** 该分类是否含 18+ 条目：决定 ` · 18+` 文本后缀 */
  nsfw: boolean
}

/** 筛选条件；`category` 为空串 = 全部分类，`tag` 为 `'all'` = 全部标签。 */
export interface CostumeFilters {
  category: string
  tag: string
  query: string
}

/** 一级分类匹配。 */
export function matchesCostumeKind(item: CostumeItem, kind: CostumeKind): boolean {
  return kind === '全部' || item.一级分类 === kind
}

/** 外链二次元条目判定：适配层同时写入 `library` 与 `remote`，两者任一即可。 */
export function isRemoteCostume(item: CostumeItem): boolean {
  return item.library === 'costume-anime' || item.remote === true
}

/**
 * 一级分类 + 安全模式过滤后的条目（React `baseCostumes`）。
 *
 * 安全模式按 `nsfw` 字段过滤；后端通常已过滤敏感条目，这里是客户端兜底。
 */
export function costumeBaseItems(
  items: CostumeItem[],
  kind: CostumeKind,
  safeMode: boolean,
): CostumeItem[] {
  return items.filter(
    (item) => matchesCostumeKind(item, kind) && (!safeMode || !item.nsfw),
  )
}

/** 当前一级分类下被安全模式隐藏的 18+ 条目数（React `hiddenNsfwCount`）。 */
export function costumeHiddenNsfwCount(items: CostumeItem[], kind: CostumeKind): number {
  return items.filter((item) => matchesCostumeKind(item, kind) && Boolean(item.nsfw)).length
}

/**
 * 实际生效的分类筛选（React `activeCategory`）。
 *
 * 安全模式下，若仍选中了含 18+ 条目的分类，自动落回「全部」，避免切回安全模式
 * 后停留在被隐藏的分类上看到空列表。
 */
export function resolveActiveCategory(
  category: string,
  safeMode: boolean,
  items: CostumeItem[],
): string {
  if (!safeMode || !category) return category
  return costumeCategoryHasNsfw(items, category) ? '' : category
}

/**
 * 分类药丸列表。
 *
 * - 顺序按条目首次出现（现实库在前，故现实分类在前）；
 * - 计数只统计当前一级分类 + 安全模式范围内的条目（React `baseCostumes`）；
 * - `nsfw` 标记按**全部已加载条目**聚合（React `costumeCategoryHasNsfw(costumes, c)`）；
 * - 空分类剔除，避免渲染出 ` (N)` 这种无意义药丸。
 */
export function costumeCategorySummaries(
  baseItems: CostumeItem[],
  allItems: CostumeItem[],
): CostumeCategorySummary[] {
  const counts = new Map<string, number>()
  for (const item of baseItems) {
    if (!item.分类) continue
    counts.set(item.分类, (counts.get(item.分类) ?? 0) + 1)
  }
  return [...counts.entries()].map(([name, count]) => ({
    name,
    count,
    nsfw: costumeCategoryHasNsfw(allItems, name),
  }))
}

/**
 * 标签下拉选项（React `allTags`）。
 *
 * 来源是「一级分类 + 安全模式 + 当前分类收窄」后的条目，按首次出现顺序去重；
 * 只取中文单品 / 颜色标签，不做分词。
 */
export function costumeTagOptions(baseItems: CostumeItem[], activeCategory: string): string[] {
  const scoped = activeCategory
    ? baseItems.filter((item) => item.分类 === activeCategory)
    : baseItems
  const tags: string[] = []
  const seen = new Set<string>()
  for (const item of scoped) {
    for (const tag of item.标签) {
      if (!tag || seen.has(tag)) continue
      seen.add(tag)
      tags.push(tag)
    }
  }
  return tags
}

/**
 * 实际生效的标签筛选（React `activeTag`）。
 *
 * 选中的标签在「当前分类收窄后」不再存在时落回「全部」，
 * 否则下拉会出现「已选但列表为空」的悬空状态。
 */
export function resolveActiveTag(
  tag: string,
  baseItems: CostumeItem[],
  activeCategory: string,
): string {
  if (tag === COSTUME_ALL_TAGS) return COSTUME_ALL_TAGS
  const hit = baseItems.some(
    (item) =>
      (!activeCategory || item.分类 === activeCategory) && item.标签.includes(tag),
  )
  return hit ? tag : COSTUME_ALL_TAGS
}

/** 搜索归一：去首尾空白 + 小写（与 React `query.trim().toLowerCase()` 一致）。 */
export function normalizeCostumeQuery(query: string): string {
  return query.trim().toLowerCase()
}

/**
 * 最终列表筛选。
 *
 * 与 React 一致：分类精确匹配、标签包含、搜索只匹配 `检索` 串
 * （`检索` 已由后端拼好名称 / 分类 / 标签 / 英文关键词，前端不重复拼）。
 */
export function filterCostumes(items: CostumeItem[], filters: CostumeFilters): CostumeItem[] {
  const needle = normalizeCostumeQuery(filters.query)
  return items.filter((item) => {
    if (filters.category && item.分类 !== filters.category) return false
    if (filters.tag !== COSTUME_ALL_TAGS && !item.标签.includes(filters.tag)) return false
    if (needle && !item.检索.toLowerCase().includes(needle)) return false
    return true
  })
}

/** 加载更多的展示状态；单位用「张」（见 ReferenceGrid 的 unit 枚举限制）。 */
export function costumeLoadMore(shown: number, total: number): LoadMoreState {
  return loadMoreState(shown, total, '张')
}

/** 下一次点击「加载更多」后的展示条数（+60，到末尾收敛）。 */
export function nextCostumeShown(shown: number, total: number): number {
  return nextShown(shown, total, COSTUME_LOAD_STEP)
}

/** 卡片上展示的标签：只取前 5 个（React `(item.标签 || []).slice(0, 5)`）。 */
export function costumeTagPreview(item: CostumeItem, limit = 5): string[] {
  return item.标签.slice(0, Math.max(0, limit))
}

/** 来源展示文案：外链固定 CharaDB，现实条目回落到作者署名。 */
export function costumeSourceLabel(item: CostumeItem): string {
  if (item.来源) return item.来源
  return isRemoteCostume(item) ? REMOTE_COSTUME_SOURCE : REAL_COSTUME_SOURCE
}

/**
 * 把视图层条目还原成 `ReferenceItemDto` 形状，交给 `referenceImageUrl`。
 *
 * 图片地址的唯一出口必须是 `referenceImageUrl`（§0 铁律 5 / §9 R7），
 * 因此这里按字段语义原样回填。`image_url` 取「预览图 → 原图」，
 * 与 React 灯箱 `预览图 || 原图` 的取图口径一致。
 */
export function costumeItemDto(item: CostumeItem): ReferenceItemDto {
  const library = item.library === 'costume-anime' ? 'costume-anime' : 'costume'
  return {
    id: item.id,
    library,
    name: item.服装名称,
    subtitle: item.日文名称 ?? '',
    group: item.一级分类 ?? (library === 'costume-anime' ? '二次元' : '现实'),
    facet: item.分类,
    angle: '',
    tags: item.标签,
    keywords: item.关键词,
    thumb_url: item.缩略图 || null,
    image_url: item.预览图 || item.原图 || null,
    depth_url: null,
    depth_thumb_url: null,
    hot: false,
    featured: false,
    nsfw: Boolean(item.nsfw),
    remote: isRemoteCostume(item),
    number: '',
    source_url: item.来源地址 ?? item.sourceUrl ?? null,
    search_text: item.检索,
  }
}

/** 卡片缩略图地址（`kind=thumb`）；无图返回 null，调用方渲染占位。 */
export function costumeThumbnailUrl(item: CostumeItem): string | null {
  return referenceImageUrl(costumeItemDto(item), 'thumb')
}

/** 灯箱大图地址（`kind=image`，预览图优先、原图兜底）；无图返回 null。 */
export function costumePreviewUrl(item: CostumeItem): string | null {
  return referenceImageUrl(costumeItemDto(item), 'image')
}

/** 下载文件名：`{id}.webp`（仅现实条目使用）。 */
export function costumeDownloadName(item: CostumeItem): string {
  return `${item.id}.webp`
}

/**
 * 外链地址安全化。
 *
 * §0 铁律 / §9 R7 要求：外链不得直连 `*.pages.dev` 静态托管（CharaDB 实际
 * `source_url` 就是该域名），一律走后端端点。返回 null 时调用方必须回落后端
 * 图片端点，绝不把原始外链写进 href。
 */
export function safeExternalUrl(raw: string | null | undefined): string | null {
  const value = (raw ?? '').trim()
  if (!value) return null
  try {
    const url = new URL(value)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
    if (url.hostname.endsWith('.pages.dev')) return null
    return value
  } catch {
    return null
  }
}

/**
 * 「原作者站点」链接。
 *
 * 优先使用上游来源地址；来源地址被安全化拦截（`*.pages.dev`）时回落到
 * 后端原图端点 —— 与 React `来源地址 || referenceImageUrl(原图)` 的兜底顺序一致，
 * 但保证 href 永远不直连外链静态托管。
 */
export function costumeAuthorSiteUrl(item: CostumeItem, fallback: string | null): string | null {
  return (
    safeExternalUrl(item.来源地址) ??
    safeExternalUrl(item.sourceUrl) ??
    fallback
  )
}

/** 灯箱信息表：分类 / 来源 / 素材说明 / 全量标签（不截断）。 */
export function costumeLightboxMeta(item: CostumeItem): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = [
    { label: '分类', value: item.分类 || '—' },
    { label: '来源', value: costumeSourceLabel(item) },
  ]
  if (isRemoteCostume(item)) {
    rows.push({ label: '素材说明', value: REMOTE_COSTUME_NOTE })
  }
  rows.push({
    label: '标签',
    value: item.标签.length > 0 ? item.标签.join('、') : '—',
  })
  return rows
}

/** 灯箱计数文案，如「12 / 1068」。 */
export function costumeCounter(index: number, total: number): string {
  if (total <= 0) return ''
  return `${index + 1} / ${total}`
}

/** 灯箱翻页下标：循环，与 React `(i + 1) % len` 一致。 */
export function stepCostumeIndex(index: number, total: number, direction: number): number {
  if (total <= 0) return 0
  return ((index + direction) % total + total) % total
}