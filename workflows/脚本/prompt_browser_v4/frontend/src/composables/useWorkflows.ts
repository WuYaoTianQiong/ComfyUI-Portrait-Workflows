import { computed, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { apiGet } from '../api/client'
import { useSettings } from './useSettings'

interface WorkflowRow {
  path: string
  name: string
}

/**
 * 工作流列表（提示词页与组合器共用）。
 *
 * 首次拿到后端 `default` 时填充设置；之后以用户选择为准（localStorage 持久化），
 * 不会再被后端默认值覆盖 —— 否则每次刷新都跳回默认工作流。
 */
export function useWorkflows() {
  const { workflowPath } = useSettings()

  const { data } = useQuery<{ workflows: WorkflowRow[]; default: string }>({
    queryKey: ['workflows'],
    queryFn: () => apiGet('/api/workflows'),
    staleTime: 60_000,
  })

  watch(
    () => data.value?.default,
    (fallback) => {
      if (!workflowPath.value && fallback) workflowPath.value = fallback
    },
    { immediate: true },
  )

  return {
    workflows: computed<WorkflowRow[]>(() => data.value?.workflows ?? []),
  }
}
