import { computed, ref } from 'vue'

/** 画廊多选状态：单条切换、全选本页、全选当前筛选（由调用方传入 id 列表）。 */
export function useGallerySelection(getPageIds: () => number[]) {
  const selected = ref<Set<number>>(new Set())
  const selectedCount = computed(() => selected.value.size)

  function toggle(id: number) {
    // Set 的增删不会自动触发 size 计算属性，替换引用才能让界面更新
    const next = new Set(selected.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    selected.value = next
  }

  function selectAll(ids: number[]) {
    selected.value = new Set(ids)
  }

  function selectPage() {
    selected.value = new Set(getPageIds())
  }

  function clear() {
    selected.value = new Set()
  }

  function has(id: number) {
    return selected.value.has(id)
  }

  return { selected, selectedCount, toggle, selectAll, selectPage, clear, has }
}
