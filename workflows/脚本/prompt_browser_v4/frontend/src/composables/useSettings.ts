import { ref, watch } from 'vue'

/**
 * 出图设置（工作流 / 画质 / 方向），持久化到 localStorage。
 *
 * 旧前端把这些塞进 UiState 的十几个 key 里，且和画廊筛选混在一起；
 * 这里单独一份，键名带 `pb.` 前缀，语义清晰。
 */
export type Orientation = 'portrait' | 'landscape'

const KEY_PREFIX = 'pb.'

function read<T extends string>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(KEY_PREFIX + key)
    return (raw as T) || fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(KEY_PREFIX + key, value)
  } catch {
    /* 隐私模式下 localStorage 可能不可用，忽略即可 */
  }
}

/** 这些页面共用同一份设置，模块级单例避免各页面各存一份。 */
const workflowPath = ref(read('workflowPath', ''))
const quality = ref(read('quality', '4K'))
const orientation = ref<Orientation>(read('orientation', 'portrait') as Orientation)

watch(workflowPath, (v) => write('workflowPath', v))
watch(quality, (v) => write('quality', v))
watch(orientation, (v) => write('orientation', v))

export const QUALITY_OPTIONS = ['2K', '4K', '6K', '8K', '12K'] as const

export function useSettings() {
  return { workflowPath, quality, orientation }
}
