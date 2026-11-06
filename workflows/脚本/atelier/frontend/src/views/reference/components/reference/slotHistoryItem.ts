/**
 * 参考图条目 → 画廊灯箱（`components/Lightbox.vue`）契约的**只读**适配。
 *
 * 合成台槽位预览不再自己写灯箱外壳，而是复用画廊那套查看器（缩放 / 平移 /
 * 旋转 / 翻转 / 信息面板 / 快捷键）。Gallery 查看器吃的是 `HistoryItem[]`
 * （`api/types.ts` 里对 `Schemas['HistoryItem']` 套了 `Required<>`，全字段必填），
 * 而参考图条目只有 `key / name / thumb / image`，所以这里逐字段显式补齐。
 *
 * 边界：
 * - 只做「读」的投影。收藏 / 删除 / 重出图 / 投喂工作流等写操作语义一律不投影，
 *   灯箱以 `readonly` 打开后这些按钮本来就不会渲染；
 * - `filename` 用条目 key（同一条目翻页时保持稳定），`view_url` 保留参考图真实
 *   地址（后端 `/api/reference/items/.../image`）；
 * - 参考条目不携带真实宽高 / 时间 / 文件大小，缺失项按「0 / 空串 / null / []」
 *   回落，不做任何伪造或 `as unknown as HistoryItem` 强转。
 */

import type { HistoryItem } from '../../../../api/types'

import type { SlotSelectedItem } from './slotView'

/**
 * FNV-1a 32 位哈希：把参考条目的字符串 key 投影成**稳定**的数字 id。
 *
 * 灯箱内部用 `item.id` 做 `<img>` 的 key、刷新恢复与详情请求，翻页时 id 必须
 * 保持不变；同时避开 0（画廊里 0 表示「未入库」的占位记录）。
 */
function stableNumericId(key: string): number {
  let hash = 0x811c9dc5
  for (let index = 0; index < key.length; index += 1) {
    hash ^= key.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }
  return ((hash >>> 0) % 0x7fffffff) + 1
}

/**
 * 单条参考图条目 → 灯箱可渲染的 `HistoryItem`。
 *
 * 字段来源：
 * - 来自条目：`filename`（key，缺失回退 name）、`view_url`（原图优先，回退缩略图）、
 *   `id`（key 的稳定哈希）；
 * - 固定默认：`subfolder=''`、`img_type='output'`、`width/height=0`、
 *   `created_at/captured_at=''`、`file_size=null`、`prompt_id/job_id/...=null`、
 *   `is_favorite/missing=false`、`categories/tags=[]`。
 */
export function slotSelectedItemToHistoryItem(item: SlotSelectedItem): HistoryItem {
  const filename = item.key || item.name || 'reference-item'

  return {
    id: stableNumericId(filename),
    filename,
    subfolder: '',
    img_type: 'output',
    view_url: item.image ?? item.thumb,
    width: 0,
    height: 0,
    file_size: null,
    created_at: '',
    captured_at: '',
    // `sourceLabel` 对未知值原样透传：直接给中文，信息面板才可读。
    source: '参考图库',
    prompt_id: null,
    job_id: null,
    prompt_name: '',
    prompt_params: null,
    comfyui_prompt_id: null,
    is_favorite: false,
    missing: false,
    categories: [],
    tags: [],
  }
}

/** 批量投影，保持槽位内的加入顺序（灯箱左右翻页依赖这个顺序）。 */
export function slotSelectedItemsToHistoryItems(
  items: readonly SlotSelectedItem[],
): HistoryItem[] {
  return items.map(slotSelectedItemToHistoryItem)
}