import { apiGet } from '../api/client'
import { CANONICAL_RATIOS } from './useWorkflowCaps'
import { normalizeQualityKey } from './useWorkflowQuality'
import type { HistoryItem, ImageDetail, PromptDetail } from '../api/types'

/**
 * 「以这张图为模板重跑」的初值装配。
 *
 * 从一张已出图记录里把可复用的参数摊开：提示词 / 负向 / 工作流 / 画幅比例 /
 * 画质档位 / 种子。重跑走 `/api/runs/text`，只带 `source_prompt_id` 让新图仍能挂回
 * 原提示词；**不写回提示词库** —— 这是"看效果"，不是编辑提示词。
 *
 * 读不到 `/detail` 或原提示词正文都不算失败：退化成已拿到的部分，让用户在面板里补。
 */
export interface RerunInitial {
  prompt: string
  negative: string
  workflowPath: string
  ratio: string
  tier: string
  seed: number | null
  /** 固定为 1：重跑默认先跑一张，张数由用户在面板里改 */
  count: number
  /** 挂回原提示词；0 表示不挂 */
  sourcePromptId: number
}

function textOf(value: unknown): string {
  if (typeof value === 'string') return value
  return typeof value === 'number' ? String(value) : ''
}

function paramsOf(item: HistoryItem): Record<string, unknown> {
  return (item.prompt_params ?? {}) as Record<string, unknown>
}

/** 出图时记录的正向；老记录没留正文时退回编译快照里的实际注入文本。 */
function snapshotPrompt(item: HistoryItem): string {
  const params = paramsOf(item)
  const direct = textOf(params.prompt).trim()
  if (direct) return direct
  const compiled = params.compiled
  if (compiled && typeof compiled === 'object') {
    return textOf((compiled as Record<string, unknown>).positive).trim()
  }
  return ''
}

function snapshotNegative(item: HistoryItem): string {
  const params = paramsOf(item)
  const direct = textOf(params.negative_prompt).trim()
  if (direct) return direct
  const compiled = params.compiled
  if (compiled && typeof compiled === 'object') {
    return textOf((compiled as Record<string, unknown>).negative).trim()
  }
  return ''
}

function snapshotSeed(item: HistoryItem): number | null {
  const raw = paramsOf(item).seed
  if (raw === null || raw === undefined || raw === '') return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

/** 从原图宽高反推最接近的通用比例：让「换个分辨率」不用手算。 */
function deriveRatio(item: HistoryItem): string {
  const w = item.width ?? 0
  const h = item.height ?? 0
  if (!w || !h) return ''
  const target = w / h
  let best = ''
  let bestDiff = Number.POSITIVE_INFINITY
  for (const ratio of CANONICAL_RATIOS) {
    const [a, b] = ratio.split(':').map(Number)
    if (!a || !b) continue
    const diff = Math.abs(Math.log(a / b / target))
    if (diff < bestDiff) {
      best = ratio
      bestDiff = diff
    }
  }
  return best
}

/** 读图片记录 + /detail + 必要时读原提示词正文；任何一步失败都退化为已拿到的部分，不抛错。 */
export async function loadRerunInitial(item: HistoryItem): Promise<RerunInitial> {
  const params = paramsOf(item)
  let prompt = snapshotPrompt(item)
  let negative = snapshotNegative(item)
  let workflowPath = ''
  let tier = normalizeQualityKey(textOf(params.quality))
  let ratio = deriveRatio(item)
  let seed = snapshotSeed(item)

  try {
    const data = await apiGet<ImageDetail>(`/api/images/${item.id}/detail`)
    const run = data?.run
    if (run?.workflow_path) workflowPath = run.workflow_path
    if (run?.quality) tier = normalizeQualityKey(run.quality)
    if (run?.aspect_ratio) ratio = run.aspect_ratio
    // seed 为 0 是合法值；给了但非有限数（NaN）一律按「没有种子」处理，不回落到快照
    const runSeed = run?.seed
    if (runSeed !== null && runSeed !== undefined) {
      seed = Number.isFinite(runSeed) ? runSeed : null
    }
  } catch {
    // 拿不到运行信息也能重跑：参数快照里的提示词 / 比例已经够用
  }

  // 老记录可能只留了 prompt_id、没有正文：补一份库里的当前版本，别让用户对着空框发呆
  if (!prompt && item.prompt_id) {
    try {
      const lib = await apiGet<PromptDetail>(`/api/prompts/${item.prompt_id}`)
      prompt = textOf(lib.prompt).trim()
      if (!negative) negative = textOf(lib.negative_prompt).trim()
    } catch {
      /* 库里的提示词也读不到：让用户自己填 */
    }
  }

  return {
    prompt,
    negative,
    workflowPath,
    ratio,
    tier,
    seed,
    count: 1,
    sourcePromptId: item.prompt_id ?? 0,
  }
}