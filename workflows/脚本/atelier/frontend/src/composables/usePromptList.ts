import { computed } from 'vue'
import type { Ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { listPrompts } from '../api/prompts'

export interface PromptListFilters {
  page: Ref<number>
  pageSize: Ref<number>
  search: Ref<string>
  categoryId: Ref<number | null>
  tagIds: Ref<number[]>
  tagMatch: Ref<'all' | 'any'>
  fragmentType: Ref<string>
  fragmentMatch: Ref<'has' | 'only'>
  sort: Ref<string>
  order: Ref<'asc' | 'desc'>
}

/**
 * 提示词列表查询：筛选参数、queryKey 与响应派生集中在这里。
 *
 * 列表、定位、批量替换必须传同一份筛选参数，否则“看到的”和“替换的”不是一批。
 * 后端没有碎片索引表，碎片筛选会走一次全表解析（300+ 条，毫秒级）。
 */
export function usePromptList(filters: PromptListFilters) {
  function fragmentParams() {
    return {
      fragment_types: filters.fragmentType.value,
      fragment_match: filters.fragmentMatch.value,
    }
  }

  const listKey = computed(() => [
    'prompts',
    filters.page.value,
    filters.pageSize.value,
    filters.search.value.trim(),
    filters.categoryId.value,
    filters.tagIds.value.slice().sort((a, b) => a - b).join(','),
    filters.tagMatch.value,
    filters.fragmentType.value,
    filters.fragmentMatch.value,
    filters.sort.value,
    filters.order.value,
  ])

  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: listKey,
    queryFn: () =>
      listPrompts({
        page: filters.page.value,
        page_size: filters.pageSize.value,
        search: filters.search.value.trim(),
        category_id: filters.categoryId.value ?? undefined,
        tag_ids: filters.tagIds.value.join(','),
        tag_match: filters.tagMatch.value,
        ...fragmentParams(),
        sort: filters.sort.value,
        order: filters.order.value,
      }),
    placeholderData: (prev) => prev,
  })

  const list = computed(() => data.value?.prompts ?? [])
  const total = computed(() => data.value?.total ?? 0)
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / filters.pageSize.value)))

  return {
    listKey,
    list,
    total,
    totalPages,
    isFetching,
    listError: isError,
    listErr: error,
    refetchList: refetch,
  }
}
