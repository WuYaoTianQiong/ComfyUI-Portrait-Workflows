/**
 * 参考图条目 → 画廊灯箱 `HistoryItem` 适配层单测。
 *
 * 覆盖：
 * - 全字段显式构造（不能靠 `as unknown as` 绕过类型检查）；
 * - 原图优先、缩略图回退，都没有时 `view_url` 为 null；
 * - 宽高未知时回落 0（`resolution()` 因此不输出假尺寸）；
 * - 同一 key 的 id 稳定、翻页/重渲染不漂移；批量投影保持原顺序。
 */

import { describe, expect, it } from 'vitest'

import type { SlotSelectedItem } from './slotView'

import {
  slotSelectedItemToHistoryItem,
  slotSelectedItemsToHistoryItems,
} from './slotHistoryItem'

function slotItem(overrides: Partial<SlotSelectedItem> = {}): SlotSelectedItem {
  return {
    key: 'P001_正面',
    name: '站姿 · 正面',
    thumb: '/api/reference/items/pose/P001_%E6%AD%A3%E9%9D%A2/image?kind=thumb',
    image: '/api/reference/items/pose/P001_%E6%AD%A3%E9%9D%A2/image?kind=image',
    ...overrides,
  }
}

describe('slotSelectedItemToHistoryItem', () => {
  it('按条目显式补齐 HistoryItem 全字段', () => {
    const item = slotItem()

    expect(slotSelectedItemToHistoryItem(item)).toEqual({
      id: expect.any(Number),
      filename: 'P001_正面',
      subfolder: '',
      img_type: 'output',
      view_url: item.image,
      width: 0,
      height: 0,
      file_size: null,
      created_at: '',
      captured_at: '',
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
    })
  })

  it('无原图时 view_url 回退缩略图；完全无图时为 null', () => {
    const thumbOnly = slotSelectedItemToHistoryItem(slotItem({ image: null }))
    const noImage = slotSelectedItemToHistoryItem(slotItem({ image: null, thumb: null }))

    expect(thumbOnly.view_url).toBe(slotItem().thumb)
    expect(noImage.view_url).toBeNull()
  })

  it('宽高未知回落 0（不伪造分辨率）', () => {
    const item = slotSelectedItemToHistoryItem(slotItem())

    expect(item.width).toBe(0)
    expect(item.height).toBe(0)
  })

  it('key 缺失时 filename 回退名称', () => {
    const item = slotSelectedItemToHistoryItem(slotItem({ key: '', name: '白衬衫' }))

    expect(item.filename).toBe('白衬衫')
  })

  it('同一 key 的 id 稳定且避开 0', () => {
    const first = slotSelectedItemToHistoryItem(slotItem())
    const second = slotSelectedItemToHistoryItem(slotItem({ name: '换个名字' }))

    expect(first.id).toBeGreaterThan(0)
    expect(second.id).toBe(first.id)
  })
})

describe('slotSelectedItemsToHistoryItems', () => {
  it('保持槽位加入顺序', () => {
    const items = slotSelectedItemsToHistoryItems([
      slotItem({ key: 'C2', name: '水手服' }),
      slotItem({ key: 'C1', name: '白衬衫' }),
    ])

    expect(items.map((item) => item.filename)).toEqual(['C2', 'C1'])
    expect(items.map((item) => item.id)).not.toEqual([items[1]?.id, items[0]?.id])
  })

  it('空数组返回空数组', () => {
    expect(slotSelectedItemsToHistoryItems([])).toEqual([])
  })
})