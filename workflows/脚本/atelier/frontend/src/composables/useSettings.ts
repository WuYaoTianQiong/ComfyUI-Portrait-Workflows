import { ref, watch } from 'vue'

/**
 * 出图设置（工作流 / 方向），持久化到 localStorage。
 *
 * 画质不在这里：它按工作流分别记忆，见 `useWorkflowQuality`。
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
const upscaleWorkflowPath = ref<string>(read('upscaleWorkflowPath', ''))
const orientation = ref<Orientation>(read('orientation', 'portrait') as Orientation)

/**
 * 删除出图记录时是否连磁盘原图一起删。
 *
 * 破坏性选项，默认关闭；但用户一旦勾选就记住（画廊批量删除与灯箱单条删除
 * 共用这一份），下次打开确认框仍是勾选态，不用每次重新勾。
 */
// 显式写 <string>：否则 T 会被推断成字面量 '0'，和 '1' 的比较会被 TS 判成无意义
const deleteFiles = ref<boolean>(read<string>('deleteFiles', '0') === '1')

/**
 * 出图归档子目录（相对 ComfyUI output）。空字符串 = 旧的平铺行为。
 * 支持 {date}/{month}/{year}/{workflow}/{job_id}/{quality}/{orientation} 变量，
 * 由后端展开并做安全校验。
 */
const outputSubfolder = ref<string>(read('outputSubfolder', ''))

watch(workflowPath, (v) => write('workflowPath', v))
watch(composerWorkflowPath, (v) => write('composerWorkflowPath', v))
watch(faceswapWorkflowPath, (v) => write('faceswapWorkflowPath', v))
watch(upscaleWorkflowPath, (v) => write('upscaleWorkflowPath', v))
watch(orientation, (v) => write('orientation', v))
watch(deleteFiles, (v) => write('deleteFiles', v ? '1' : '0'))
watch(outputSubfolder, (v) => write('outputSubfolder', v))

export function useSettings() {
  return {
    workflowPath,
    composerWorkflowPath,
    faceswapWorkflowPath,
    upscaleWorkflowPath,
    orientation,
    deleteFiles,
    outputSubfolder,
  }
}
