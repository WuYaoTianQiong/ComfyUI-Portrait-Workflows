import { computed, ref, type Ref } from 'vue'

/**
 * 提示词多选：切换、追加式全选本页、反选本页、跨页全选全部、清空。
 *
 * `selectedIds` 由 `usePromptWorkspace` 持有（会话内可恢复），本组合式只做集合运算，
 * 页面不再各写一遍实现。旧写法有两个坑：
 * - 「全选本页」直接替换整个集合，在第 2 页点一下就把第 1 页的勾选悄悄冲掉；
 * - 没有反选 / 跨页全选，只能逐页点。
 *
 * 勾选跨页保留：筛选条件变了也不自动清空（与旧行为一致），要清空点「取消」。
 */
export interface PromptSelectionOptions {
  /** 由 workspace 持有的选中集合，直接原地替换引用以触发更新。 */
  selectedIds: Ref<Set<number>>
  /** 当前页可见的 id（全选本页 / 反选本页的范围）。 */
  pageIds: () => number[]
  /** 当前筛选下的全部 id（跨页全选）；由调用方决定走哪个接口。 */
  allIds: () => Promise<number[]>
  /** 失败或全选结果为空时的提示；`kind` 让调用方决定用 info 还是 error。 */
  onNotify?: (message: string, kind: 'info' | 'error') => void
}

export function usePromptSelection(options: PromptSelectionOptions) {
  const selectingAll = ref(false)
  const selectedCount = computed(() => options.selectedIds.value.size)
  const selectedArray = computed(() => Array.from(options.selectedIds.value))

  function write(next: Set<number>) {
    options.selectedIds.value = next
  }

  function toggle(id: number) {
    const next = new Set(options.selectedIds.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    write(next)
  }

  /** 追加式全选本页：保留其他页已勾选的条目。 */
  function selectPage() {
    const next = new Set(options.selectedIds.value)
    for (const id of options.pageIds()) next.add(id)
    write(next)
  }

  /** 反选本页：本页已选的取消、未选的勾上；其他页不受影响。 */
  function invertPage() {
    const next = new Set(options.selectedIds.value)
    for (const id of options.pageIds()) {
      if (next.has(id)) next.delete(id)
      else next.add(id)
    }
    write(next)
  }

  async function selectAllMatching() {
    if (selectingAll.value) return 0
    selectingAll.value = true
    try {
      const ids = await options.allIds()
      write(new Set(ids))
      if (!ids.length) options.onNotify?.('当前筛选下没有可选的提示词', 'info')
      return ids.length
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      options.onNotify?.(`全选失败：${message}`, 'error')
      return 0
    } finally {
      selectingAll.value = false
    }
  }

  function clear() {
    write(new Set())
  }

  return {
    selectedIds: options.selectedIds,
    selectedCount,
    selectedArray,
    selectingAll,
    toggle,
    selectPage,
    invertPage,
    selectAllMatching,
    clear,
  }
}
