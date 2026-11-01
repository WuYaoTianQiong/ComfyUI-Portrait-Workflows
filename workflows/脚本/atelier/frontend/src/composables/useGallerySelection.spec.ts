import { describe, expect, it } from 'vitest'

import { useGallerySelection } from './useGallerySelection'

describe('useGallerySelection', () => {
  it('切换、全选本页、全选筛选、清空', () => {
    let pageIds = [1, 2]
    const selection = useGallerySelection(() => pageIds)

    selection.toggle(1)
    expect(selection.has(1)).toBe(true)
    expect(selection.selectedCount.value).toBe(1)

    selection.toggle(1)
    expect(selection.has(1)).toBe(false)

    selection.selectPage()
    expect(Array.from(selection.selected.value).sort()).toEqual([1, 2])

    selection.selectAll([7, 8, 9])
    expect(selection.selectedCount.value).toBe(3)
    expect(selection.has(8)).toBe(true)

    pageIds = [3, 4]
    selection.selectPage()
    expect(Array.from(selection.selected.value).sort()).toEqual([3, 4])

    selection.clear()
    expect(selection.selectedCount.value).toBe(0)
  })
})
