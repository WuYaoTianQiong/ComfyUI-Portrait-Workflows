import { queryOptions } from '@tanstack/react-query'
import {
  fetchAllReferenceItems,
  isNsfwCostumeItem,
  isNsfwPoseItem,
  toCostumeItem,
  toPortraitItem,
  toPoseItem,
} from '@/lib/referenceAdapter'
import type { CostumeItem, PoseGroup, PoseItem } from '@/types/gallery'

export const ANGLES = ['正面', '俯视', '仰视', '侧面', '斜侧'] as const

export const PREFERRED_POSE_LINE_ORDER = [
  '全身单人・标准系',
  '上半身单人',
  '全身单人・性感系',
  '双人缠绵',
] as const

/**
 * 姿势条目的 18+ 判定（名称保留，减少页面改动面）。
 *
 * 数据源改为适配层的 `nsfw` 字段（来自后端 DTO），不再硬编码体系名单。
 */
export function isNsfwPose(item: PoseItem | PoseGroup): boolean {
  return isNsfwPoseItem(item)
}

/**
 * 服装条目的 18+ 判定（名称保留，减少页面改动面）。
 *
 * 数据源改为适配层的 `nsfw` 字段（来自后端 DTO），不再硬编码分类名单。
 */
export function isNsfwCostume(item: CostumeItem): boolean {
  return isNsfwCostumeItem(item)
}

export function buildPoseGroups(items: PoseItem[]): { items: PoseItem[]; groups: PoseGroup[]; lines: string[] } {
  const rawLines = [...new Set(items.map((x) => x.体系))]
  const lines = rawLines.sort((a, b) => {
    const ia = PREFERRED_POSE_LINE_ORDER.indexOf(a as (typeof PREFERRED_POSE_LINE_ORDER)[number])
    const ib = PREFERRED_POSE_LINE_ORDER.indexOf(b as (typeof PREFERRED_POSE_LINE_ORDER)[number])
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
  })
  const groupMap = new Map<string, PoseGroup>()
  const groups: PoseGroup[] = []

  for (const item of items) {
    // 分组键使用上游「姿势编号」（DTO.number），跨角度条目才会归入同一组；
    // 编号缺失时回退 id，避免空编号把所有条目挤成一组。
    const key = `${item.体系}|${item.姿势编号 || item.id}`
    let group = groupMap.get(key)
    if (!group) {
      group = {
        key,
        system: item.体系,
        number: item.姿势编号,
        name: item.姿势名称,
        category: item.分类,
        items: [],
        angles: {},
        order: [],
      }
      groupMap.set(key, group)
      groups.push(group)
    }
    group.items.push(item)
    if (item.角度 && !group.angles[item.角度]) {
      group.angles[item.角度] = item
    }
  }

  groups.sort((a, b) => lines.indexOf(a.system) - lines.indexOf(b.system) || String(a.number).localeCompare(String(b.number)))
  for (const group of groups) {
    group.order = ANGLES.map((a) => group.angles[a]).filter(Boolean)
    for (const item of group.items) {
      if (!group.order.includes(item)) group.order.push(item)
    }
  }

  return { items, groups, lines }
}

export const posesQuery = queryOptions({
  queryKey: ['gallery', 'poses'],
  staleTime: Infinity,
  queryFn: async () => {
    const items = await fetchAllReferenceItems('pose')
    return buildPoseGroups(items.map(toPoseItem))
  },
})

export const costumesQuery = queryOptions({
  queryKey: ['gallery', 'costumes'],
  staleTime: Infinity,
  queryFn: async () => {
    // 并行拉取两个服装库；合并顺序固定为现实在前、外链二次元在后。
    const [local, anime] = await Promise.all([
      fetchAllReferenceItems('costume'),
      fetchAllReferenceItems('costume-anime'),
    ])
    return [...local.map(toCostumeItem), ...anime.map(toCostumeItem)]
  },
})

export const portraitsQuery = queryOptions({
  queryKey: ['gallery', 'portraits'],
  staleTime: Infinity,
  queryFn: async () => {
    const items = await fetchAllReferenceItems('portrait')
    return items.map(toPortraitItem)
  },
})