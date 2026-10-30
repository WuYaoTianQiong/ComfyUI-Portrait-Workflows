import { computed, watch } from 'vue'
import type { Ref } from 'vue'
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

export interface WorkflowValidation {
  valid: boolean
  error?: string
  name?: string
}

/**
 * 校验当前选中的工作流文件。
 *
 * 后端只检查格式（API 格式或 UI 格式），不做节点类型检查 —— 换脸页另有
 * 专门的节点映射探测。这里提前拦的是"文件损坏/格式不对"这类低级错误，
 * 免得提交后才报错。
 */
export function useWorkflowValidation(path: Ref<string>) {
  return useQuery<WorkflowValidation>({
    queryKey: computed(() => ['validate-workflow', path.value]),
    queryFn: () => apiGet('/api/validate_workflow', { path: path.value }),
    enabled: computed(() => !!path.value),
    staleTime: 30_000,
  })
}