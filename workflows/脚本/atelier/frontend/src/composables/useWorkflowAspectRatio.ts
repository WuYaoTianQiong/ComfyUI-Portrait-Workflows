import { computed, ref, watch } from 'vue'
import type { Ref, WritableComputedRef } from 'vue'

/**
 * 出图比例按工作流分别记忆。
 *
 * 空字符串表示"用工作流默认比例"，由 `WorkflowParams` 在拿到 ratios 后补上；
 * 这样新建工作流或切换工作流时不会继承上一个工作流的比例。
 */

const KEY_PREFIX = 'pb.aspectRatio:'
const cache = new Map<string, Ref<string>>()

function readRatio(path: string): string {
  if (!path) return ''
  try {
    return localStorage.getItem(KEY_PREFIX + path) || ''
  } catch {
    return ''
  }
}

function ratioRefFor(path: string): Ref<string> {
  const cached = cache.get(path)
  if (cached) return cached
  const ratio = ref(readRatio(path))
  if (path) {
    watch(ratio, (value) => {
      try {
        if (value) localStorage.setItem(KEY_PREFIX + path, value)
        else localStorage.removeItem(KEY_PREFIX + path)
      } catch {
        /* 隐私模式下忽略 */
      }
    })
  }
  cache.set(path, ratio)
  return ratio
}

export function useWorkflowAspectRatio(workflowPath: Ref<string>): WritableComputedRef<string> {
  return computed({
    get: () => ratioRefFor(workflowPath.value).value,
    set: (value: string) => {
      ratioRefFor(workflowPath.value).value = value
    },
  })
}
