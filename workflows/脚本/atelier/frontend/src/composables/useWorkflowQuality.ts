import { computed, ref, watch } from 'vue'
import type { Ref, WritableComputedRef } from 'vue'

/**
 * 画质按工作流各自记忆。
 *
 * 内部值是相对倍率 `0.75x…2.0x`：同一个档位在 Krea2（基准 1128×2008）
 * 和 Qwen（基准 832×1216）下实际尺寸不同。全局共用一份会让切换工作流时
 * 静默变小，所以这里按工作流路径分别存；首次使用默认 `1.0x`（原生尺寸）。
 */

const KEY_PREFIX = 'pb.quality:'
const DEFAULT_QUALITY = '1.0x'

/** 旧版本存的是 2K/4K/6K/8K/12K；读取时归一，避免旧选择失效。 */
const LEGACY_QUALITY: Record<string, string> = {
  '2K': '0.75x',
  '4K': '1.0x',
  '6K': '1.25x',
  '8K': '1.5x',
  '12K': '2.0x',
  high: '1.0x',
}

export function normalizeQualityKey(value: string | null | undefined): string {
  if (!value) return DEFAULT_QUALITY
  return LEGACY_QUALITY[value] ?? value
}

const cache = new Map<string, Ref<string>>()

function readQuality(path: string): string {
  if (!path) return DEFAULT_QUALITY
  try {
    return normalizeQualityKey(localStorage.getItem(KEY_PREFIX + path))
  } catch {
    return DEFAULT_QUALITY
  }
}

function qualityRefFor(path: string): Ref<string> {
  const cached = cache.get(path)
  if (cached) return cached
  const quality = ref(readQuality(path))
  if (path) {
    watch(quality, (value) => {
      try {
        localStorage.setItem(KEY_PREFIX + path, value)
      } catch {
        /* 隐私模式下 localStorage 不可用，忽略即可 */
      }
    })
  }
  cache.set(path, quality)
  return quality
}

/** 当前工作流的画质档位；读写共用同一份，多个组件挂同一路径时保持同步。 */
export function useWorkflowQuality(workflowPath: Ref<string>): WritableComputedRef<string> {
  return computed({
    get: () => qualityRefFor(workflowPath.value).value,
    set: (value: string) => {
      qualityRefFor(workflowPath.value).value = normalizeQualityKey(value)
    },
  })
}
