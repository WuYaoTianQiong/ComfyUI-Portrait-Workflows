import { computed } from 'vue'
import type { Ref } from 'vue'

import type { WorkflowRow } from './useWorkflows'
import {
  DEFAULT_CAPS,
  qualityOptionsFor,
  type QualityOption,
  type WorkflowCaps,
  type WorkflowParams,
} from '../utils/workflowCaps'

/**
 * 当前工作流的能力与真实档位。
 *
 * 提示词页 / 组合器 / 补跑面板 / 试跑面板 / 画廊重跑都从这里取，
 * 避免每个页面各写一遍"找 selected → 取 caps → 生成档位"。
 */
export function useWorkflowCaps(
  workflowPath: Ref<string>,
  allWorkflows: Ref<WorkflowRow[]>,
) {
  const selected = computed(() =>
    allWorkflows.value.find((w) => w.path === workflowPath.value),
  )
  const caps = computed<WorkflowCaps>(() => selected.value?.caps ?? DEFAULT_CAPS)
  const params = computed<WorkflowParams | undefined>(() => selected.value?.params)
  const qualityOptions = computed<QualityOption[]>(() =>
    qualityOptionsFor(params.value, caps.value),
  )

  return { selected, caps, params, qualityOptions }
}
