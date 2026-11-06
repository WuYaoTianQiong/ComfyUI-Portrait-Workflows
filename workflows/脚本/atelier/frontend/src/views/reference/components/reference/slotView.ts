/**
 * 合成台槽位展示逻辑（阶段 3）。
 *
 * 三个槽位的缩略图必须走 `referenceImageUrl`（§0 铁律 5 / §9 R7），而数据层
 * 把 DTO 映射成中文键条目后丢掉了原始字段名，所以这里按字段语义还原成
 * `ReferenceItemDto` 形状再取图。
 *
 * 姿势槽复用阶段 2.1 的 `poseThumbnailUrl`（白模 / 深度图双模式），
 * 避免两处各写一份深度图回退逻辑。
 *
 * 2026-11-05：槽位卡改为「点缩略图开灯箱」，因此每个展示条目额外带 `image`
 * （灯箱原图地址）；`thumb` 语义保持不变，其它代码可继续按缩略图使用。
 */

import type { CostumeItem, PortraitItem, ReferenceItemDto } from '../../../../api/reference'
import { referenceImageUrl } from '../../../../api/reference'
import type { PoseItem } from '../../../../api/reference'

import { costumePreviewUrl } from '../costumeView'
import { posePreviewUrl, poseThumbnailUrl } from '../poseView'
import { portraitPreviewUrl } from '../portraitView'

/** 人像条目 → `ReferenceItemDto`（只服务 `kind=thumb`，其余字段填占位值）。 */
export function portraitSlotDto(item: PortraitItem): ReferenceItemDto {
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
    hot: false,
    featured: false,
    nsfw: Boolean(item.nsfw),
    remote: false,
    number: '',
    source_url: null,
    search_text: item.检索,
  }
}

/** 服装条目 → `ReferenceItemDto`；`library` 决定现实库 / 二次元外链库。 */
export function costumeSlotDto(item: CostumeItem): ReferenceItemDto {
  return {
    id: item.id,
    library: item.library ?? 'costume',
    name: item.服装名称,
    subtitle: item.日文名称 ?? '',
    group: item.分类,
    facet: '',
    angle: '',
    tags: Array.isArray(item.标签) ? item.标签 : [],
    keywords: item.关键词,
    thumb_url: item.缩略图 || null,
    image_url: item.原图 || null,
    depth_url: null,
    depth_thumb_url: null,
    hot: false,
    featured: false,
    nsfw: Boolean(item.nsfw),
    remote: Boolean(item.remote),
    number: '',
    source_url: item.sourceUrl ?? null,
    search_text: item.检索,
  }
}

/** 人像槽缩略图。 */
export function portraitSlotThumb(item: PortraitItem | null): string | null {
  return item ? referenceImageUrl(portraitSlotDto(item), 'thumb') : null
}

/** 服装槽缩略图。 */
export function costumeSlotThumb(item: CostumeItem | null): string | null {
  return item ? referenceImageUrl(costumeSlotDto(item), 'thumb') : null
}

/** 姿势槽缩略图（按加入时的白模 / 深度图模式取）。 */
export function poseSlotThumb(item: PoseItem | null, useDepth: boolean): string | null {
  return item ? poseThumbnailUrl(item, useDepth) : null
}

/** 人像槽展示名：优先发型名，缺失回退标题（React 合成台同口径）。 */
export function portraitSlotName(item: PortraitItem | null): string {
  if (!item) return ''
  return item.发型名称 || item.标题 || ''
}

/** 服装槽展示名。 */
export function costumeSlotName(item: CostumeItem | null): string {
  return item?.服装名称 ?? ''
}

/** 姿势槽展示名：`姿势名称 · 角度`（React 同口径）。 */
export function poseSlotName(item: PoseItem | null): string {
  if (!item) return ''
  return item.角度 ? `${item.姿势名称} · ${item.角度}` : item.姿势名称
}
// ---------------------------------------------------------------------------
// 多选槽位视图（合成台展示「已选数量 + 前 N 张缩略图」）
// ---------------------------------------------------------------------------

/**
 * 单个已选槽位条目的展示数据。
 *
 * `thumb` 保持既有语义（卡片缩略图 / 回退图），`image` 专门给灯箱看大图；
 * 两者都允许 null（条目无图），调用方必须渲染占位而不是输出空 `src`。
 */
export interface SlotSelectedItem {
  key: string
  name: string
  thumb: string | null
  /** 原图 URL（灯箱使用）；无原图时为 null，由调用方回退到 `thumb`。 */
  image: string | null
}

/** 人像槽：数组 → 展示条目（顺序即加入顺序）。 */
export function portraitSlotItems(items: readonly PortraitItem[]): SlotSelectedItem[] {
  return items.map((item) => ({
    key: item.id,
    name: portraitSlotName(item),
    thumb: portraitSlotThumb(item),
    image: portraitPreviewUrl(item),
  }))
}

/** 服装槽：数组 → 展示条目。 */
export function costumeSlotItems(items: readonly CostumeItem[]): SlotSelectedItem[] {
  return items.map((item) => ({
    key: item.id,
    name: costumeSlotName(item),
    thumb: costumeSlotThumb(item),
    image: costumePreviewUrl(item),
  }))
}

/** 姿势槽：数组 → 展示条目；每条按自身加入时的白模 / 深度图模式取图。 */
export function poseSlotItems(
  items: readonly { item: PoseItem; useDepth: boolean }[],
): SlotSelectedItem[] {
  return items.map((entry) => ({
    key: entry.item.id,
    name: poseSlotName(entry.item),
    thumb: poseSlotThumb(entry.item, entry.useDepth),
    // 灯箱大图与缩略图共用同一模式：深度模式下看深度大图，白模模式下看原图。
    image: posePreviewUrl(entry.item, entry.useDepth),
  }))
}