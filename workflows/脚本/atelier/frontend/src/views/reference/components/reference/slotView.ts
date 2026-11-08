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

/** 双人姿势人数风险类型（2026-11-08 0.5x 多 seed 实测结果）。 */
export type PairPoseRiskKind = 'multi' | 'missing' | 'unstable' | ''

/**
 * 已实测的双人姿势风险表（按**精确姿势 id**，不按基 id 归并）。
 *
 * 同一姿势不同角度的实测结果不同（例如 `pair60_P020_diag` 稳定 2 人、
 * `pair60_P020_front` 稳定 3 人），按基 id 归并会误伤正常角度，所以这里
 * 只标记真正跑过的那个条目。数据来自 117 个唯一双人姿势条目的 0.5x
 * 全量抽样，非 2 人条目再做多 seed 复验；结果见
 * `_tmp_ui_audit/pair_pose_counts.jsonl`。
 */
const PAIR_POSE_RISK: Readonly<Record<string, PairPoseRiskKind>> = {
  // 多次 seed 都稳定 3 人
  'psl-D003': 'multi', // [3,3,3,3,3,3,3]
  'pair60_P063_front': 'multi', // [3,3]
  'psl-D005': 'multi', // [3,3]
  'pair60_P020_front': 'multi', // [3,3]
  'pair60_P030_front': 'multi', // [3,3]
  'pair60_P044_front': 'multi', // [3,3]
  'pair60_P005_front': 'multi', // [3,3]
  'psl-D040': 'multi', // [3,3]
  // 多次 seed 都稳定 1 人（丢失其中一人）
  'pair60_P049_diag': 'missing', // [1,1,1,1,1]
  'psl-D011': 'missing', // [1,1]
  'psl-D028': 'missing', // [1,1]
  'pair60_P032_front': 'missing', // [1,1]
  'pair60_P042_front': 'missing', // [1,1]
  'pair60_P049_front': 'missing', // [1,1]
  'pair60_P004_front': 'missing', // [1,1]
  'pair60_P006_front': 'missing', // [1,1]
  // 多 seed 间在 1/2/3 之间波动
  'psl-D037': 'unstable', // [2,3]
  'pair60_P002_diag': 'unstable', // [2,3,4]
  'pair60_P042_diag': 'unstable', // [1,2]
  'pair60_P055_diag': 'unstable', // [1,2]
  'pair60_P057_diag': 'unstable', // [1,2]
  'psl-D008': 'unstable', // [1,2]
  'psl-D017': 'unstable', // [2,3]
  'psl-D034': 'unstable', // [1,2]
  'psl-D049': 'unstable', // [1,2]
  'psl-D035': 'unstable', // [2,3]
  'psl-D023': 'unstable', // [1,3]
  'psl-D025': 'unstable', // [1,2]
  'psl-D031': 'unstable', // [2,3]
  'pair60_P062_front': 'unstable', // [1,2]
  'psl-D006': 'unstable', // [2,3]
  'pair60_P041_front': 'unstable', // [1,3]
  'pair60_P053_front': 'unstable', // [2,3]
  'pair60_P013_front': 'unstable', // [2,3]
  'pair60_P015_front': 'unstable', // [2,3]
  'pair60_P018_front': 'unstable', // [1,2]
}

/** 是否双人构图；与后端 `is_pair` 判定口径一致。 */
export function isPairPose(
  item: Pick<PoseItem, 'id' | 'composition'> | null | undefined,
): boolean {
  if (!item) return false
  return item.composition === 'pair' || item.id.startsWith('pair')
}

/** 双人姿势人数风险；非双人或未录入返回空串。 */
export function pairPoseRiskOf(
  item: Pick<PoseItem, 'id' | 'composition'> | null | undefined,
): PairPoseRiskKind {
  if (!isPairPose(item)) return ''
  return PAIR_POSE_RISK[item!.id] ?? ''
}

/** 风险提示文案；无风险返回空串。 */
export function describePairPoseRisk(
  item: Pick<PoseItem, 'id' | 'composition' | '姿势名称'> | null | undefined,
): string {
  const kind = pairPoseRiskOf(item)
  if (!kind) return ''
  const name = item?.姿势名称 || '当前双人姿势'
  if (kind === 'multi') {
    return `该双人姿势实测可能多画人物（出现第三人）：${name}。建议换姿势，或生成后检查人数。`
  }
  if (kind === 'missing') {
    return `该双人姿势实测可能只画一个人（丢失人物A或B）：${name}。建议换姿势，或生成后检查人数。`
  }
  return `该双人姿势实测人数不稳定（2/3/1 都出现过）：${name}。建议多生成几张或换姿势。`
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