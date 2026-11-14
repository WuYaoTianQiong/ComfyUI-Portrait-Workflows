import { computed } from 'vue'
import type { WritableComputedRef } from 'vue'

import { useWorkflowAspectRatio } from './useWorkflowAspectRatio'
import { useWorkflowQuality } from './useWorkflowQuality'
import type { MatrixFlowOverride } from './useWorkflowMatrix'

/**
 * 横评的逐流参数读写句柄。
 *
 * 比例 / 画质沿用「按工作流记忆」的同一份存储（`pb.aspectRatio:<path>`、
 * `pb.quality:<path>`）：逐流参数行负责写，计划层通过 `overrides(paths)` 读。
 * 两边按路径缓存同一组 ref，改一行只影响那一个工作流。
 */
export function useMatrixFlowParams() {
  const cache = new Map<
    string,
    { ratio: WritableComputedRef<string>; tier: WritableComputedRef<string> }
  >()

  function flowParamsFor(path: string) {
    let hit = cache.get(path)
    if (!hit) {
      const pathRef = computed(() => path)
      hit = { ratio: useWorkflowAspectRatio(pathRef), tier: useWorkflowQuality(pathRef) }
      cache.set(path, hit)
    }
    return hit
  }

  /** 给 buildMatrixPlan 的逐流覆盖；未勾选任何流时返回空表。 */
  function overrides(paths: readonly string[]): Record<string, MatrixFlowOverride> {
    const out: Record<string, MatrixFlowOverride> = {}
    for (const path of paths) {
      const refs = flowParamsFor(path)
      out[path] = { ratio: refs.ratio.value, tier: refs.tier.value }
    }
    return out
  }

  return { flowParamsFor, overrides }
}
