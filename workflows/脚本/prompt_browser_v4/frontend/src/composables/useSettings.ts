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

/**
 * 工作流按页独立：换脸要的是「双 LoadImage 的换脸工作流」，和文生图工作流
 * 不是同一个集合，共用一份会把另一页的出图工作流改掉。
 *
 * `workflowPath` 保留原键名，是提示词页的出图工作流（画廊重跑也只读它，
 * 画廊没有选择器）；组合器、换脸各自一份。
 */
// 显式标注类型：ref(read(...)) 会被推断成字面量类型（Ref<''>），后面赋别的字符串就报错
const workflowPath = ref<string>(read('workflowPath', ''))
const composerWorkflowPath = ref<string>(read('composerWorkflowPath', ''))
const faceswapWorkflowPath = ref<string>(read('faceswapWorkflowPath', ''))
const quality = ref<string>(read('quality', '4K'))
const orientation = ref<Orientation>(read('orientation', 'portrait') as Orientation)

watch(workflowPath, (v) => write('workflowPath', v))
watch(composerWorkflowPath, (v) => write('composerWorkflowPath', v))
watch(faceswapWorkflowPath, (v) => write('faceswapWorkflowPath', v))
watch(quality, (v) => write('quality', v))
watch(orientation, (v) => write('orientation', v))

export function useSettings() {
  return { workflowPath, composerWorkflowPath, faceswapWorkflowPath, quality, orientation }
}
