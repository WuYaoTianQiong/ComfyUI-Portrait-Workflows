import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { usePromptSelection } from './usePromptSelection'

function setup(pageIds: number[], allIds: number[] = []) {
  const selectedIds = ref(new Set<number>())
  const onNotify = vi.fn()
  const allIdsSpy = vi.fn(async () => allIds)
  const selection = usePromptSelection({
    selectedIds,
    pageIds: () => pageIds,
    allIds: allIdsSpy,
    onNotify,
  })
  return { selection, selectedIds, onNotify, allIdsSpy }
}

describe('usePromptSelection', () => {
  it('切换与清空', () => {
    const { selection } = setup([1, 2])
    selection.toggle(1)
    expect(selection.selectedCount.value).toBe(1)
    selection.toggle(1)
    expect(selection.selectedCount.value).toBe(0)

    selection.toggle(2)
    selection.clear()
    expect(selection.selectedCount.value).toBe(0)
  })

  it('全选本页是追加：不冲掉其他页的勾选', () => {
    const { selection } = setup([3, 4])
    selection.toggle(1)
    selection.toggle(2)
    selection.selectPage()

    expect(Array.from(selection.selectedIds.value).sort()).toEqual([1, 2, 3, 4])
  })

  it('反选本页只影响本页', () => {
    const { selection } = setup([2, 3])
    // 1 是第 1 页选的，2 是本页已选，3 本页未选
    selection.toggle(1)
    selection.toggle(2)
    selection.invertPage()

    expect(Array.from(selection.selectedIds.value).sort()).toEqual([1, 3])
  })

  it('跨页全选全部替换为完整 id 集合', async () => {
    const { selection, allIdsSpy } = setup([1], [11, 12, 13])
    selection.toggle(99)
    const count = await selection.selectAllMatching()

    expect(allIdsSpy).toHaveBeenCalledTimes(1)
    expect(count).toBe(3)
    expect(Array.from(selection.selectedIds.value).sort()).toEqual([11, 12, 13])
  })

  it('全选结果为空时给出提示', async () => {
    const { selection, onNotify } = setup([1], [])
    await selection.selectAllMatching()
    expect(onNotify).toHaveBeenCalledWith('当前筛选下没有可选的提示词', 'info')
  })

  it('接口失败时提示且不清空已有勾选', async () => {
    const selectedIds = ref(new Set<number>([5]))
    const onNotify = vi.fn()
    const selection = usePromptSelection({
      selectedIds,
      pageIds: () => [1],
      allIds: async () => {
        throw new Error('网络断了')
      },
      onNotify,
    })

    expect(await selection.selectAllMatching()).toBe(0)
    expect(onNotify).toHaveBeenCalledWith('全选失败：网络断了', 'error')
    expect(Array.from(selectedIds.value)).toEqual([5])
    expect(selection.selectedCount.value).toBe(1)
  })
})
