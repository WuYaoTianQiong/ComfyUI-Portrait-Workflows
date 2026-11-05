/**
 * 合成台槽位展示逻辑（阶段 3）。
 *
 * 三个槽位的缩略图必须走 `referenceImageUrl`（§0 铁律 5 / §9 R7），而数据层
 * 把 DTO 映射成中文键条目后丢掉了原始字段名，所以这里按字段语义还原成
 * `ReferenceItemDto` 形状再取图。
 *
 * 姿势槽复用阶段 2.1 的 `poseThumbnailUrl`（白模 / 深度图双模式），
 * 避免两处各写一份深度图回退逻辑。
 */

import type { CostumeItem, PortraitItem, ReferenceItemDto } from '../../../../api/reference'
import { referenceImageUrl } from '../../../../api/reference'
import type { PoseItem } from '../../../../api/reference'

import { poseThumbnailUrl } from '../poseView'

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