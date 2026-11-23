/**
 * `/api/runs/text` 请求体的唯一口径：UI 值 → snake_case 请求体。
 *
 * 「画廊改参重跑」和「提示词页临时试跑」打的是同一个端点，字段口径（空画质回落、
 * 不挂提示词落 0）若各写一份就会悄悄分叉，因此只留这一份纯转换。
 * 提交流程与 job 队列状态归各调用方自己的 useGenerate 管，本层不 import 它，
 * 也不读不写任何 localStorage。
 */
export interface RunTextInput {
  prompt: string
  negativePrompt?: string
  workflowPath: string
  /** 工作流不支持画质档时调用方已回落 '1.0x'，这里不再判断 caps。 */
  quality?: string
  /** 工作流不支持方向时调用方已回落 'keep'。 */
  orientation?: string
  aspectRatio?: string
  /** null = 每张随机 */
  seed?: number | null
  /** 挂回哪个提示词；0 / null / undefined 一律落成 0。 */
  sourcePromptId?: number | null
  /** 自定义工作流 JSON（临时试跑支持），没有就 null。 */
  workflowContent?: string | null
}

export interface RunTextRequest {
  prompt: string
  negative_prompt: string
  workflow_path: string
  workflow_content: string | null
  quality: string
  orientation: string
  aspect_ratio: string
  seed: number | null
  source_prompt_id: number
}

/** 纯函数：UI 值 → 后端请求体。prompt/negative 去首尾空白；quality 空值回落 '1.0x'；orientation 空值回落 'keep'；aspect_ratio 空值回落 ''；seed 保留 0 与 null 的区别。 */
export function buildRunTextRequest(input: RunTextInput): RunTextRequest {
  return {
    prompt: input.prompt.trim(),
    negative_prompt: (input.negativePrompt ?? '').trim(),
    workflow_path: input.workflowPath,
    workflow_content: input.workflowContent ?? null,
    quality: input.quality || '1.0x',
    orientation: input.orientation || 'keep',
    aspect_ratio: input.aspectRatio || '',
    seed: input.seed ?? null,
    // 未关联与不关联都落 0：后端只认「0 = 不挂提示词」这一种写法
    source_prompt_id: input.sourcePromptId ?? 0,
  }
}