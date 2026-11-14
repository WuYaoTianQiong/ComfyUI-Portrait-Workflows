import { computed } from 'vue'
import type { Ref } from 'vue'

import type { WorkflowRow } from './useWorkflows'
import { normalizeQualityKey } from './useWorkflowQuality'

/**
 * 工作流「能注入什么」与「档位怎么显示」。
 *
 * 能力探测、档位过滤、尺寸计算全部以后端 `/api/workflows`（磁盘）与
 * `/api/workflows/inspect`（自定义内容）为准；本文件只把后端的
 * `size_preview` 格式化成界面文案，不再解析节点、也不再算像素。
 */

export interface WorkflowCaps {
  prompt: boolean
  /** 结构上有没有负向输入（不代表真的生效）。 */
  negative: boolean
  /** 负向条件是否真的参与采样：来自文本节点且 cfg>1。 */
  negative_effective: boolean
  /** 真实负向路径上的最大 CFG；null = 没有文本负向路径。 */
  negative_cfg: number | null
  quality: boolean
  orientation: boolean
  /** 工作流是否真的产出图片；旧响应可能没有该字段，按 true 处理。 */
  image_output?: boolean
}

export type QualityMode = 'seedvr' | 'scale' | 'megapixels' | 'none'
export type OrientationMode = 'swap' | 'knob' | 'none'

export interface WorkflowParams {
  quality_mode: QualityMode
  base_width?: number | null
  base_height?: number | null
  base_megapixels?: number | null
  /** megapixels 的单位：字面量/preset 是 1e6，ResolutionSelector 是 1024²。 */
  mp_unit?: 'mp' | 'mip'
  /** latent 之后沿输出路径的放大倍率（如 ZIT 的 1.7×）；没有则为 1。 */
  post_scale?: number
  orientation_mode: OrientationMode
  aspect_ratios?: string[]
  default_ratio?: string
  multiple?: number
  /** 工作流允许的档位；缺省时全部可用。 */
  quality_tiers?: string[]
  /** 首次使用该工作流时的档位。 */
  default_quality?: string
}

/** 后端预演的单档单比例尺寸；`*` 表示与比例无关（SeedVR / 像素档）。 */
export interface SizePreviewEntry {
  width?: number
  height?: number
  final_width?: number
  final_height?: number
  megapixels?: number
  scale?: number
  native?: boolean
}

export type SizePreview = Record<string, Record<string, SizePreviewEntry>>

export interface QualityOption {
  /** 提交给后端的值；与 injection 的倍率表保持一致 */
  value: string
  /** 展示给用户的文案，尽量写真实尺寸 / MP */
  label: string
}

/** 项目统一比例，与后端 CANONICAL_RATIOS 一致（21:9 的竖版是 9:21）。 */
export const CANONICAL_RATIOS = [
  '1:1', '2:3', '3:2', '3:4', '4:3', '9:16', '16:9', '21:9', '9:21',
] as const

const QUALITY_SCALES = [
  // 2026-11-08：新增 0.25x / 0.5x 低画质档，供快速验证与低配出图。
  { value: '0.25x', scale: 0.25 },
  { value: '0.5x', scale: 0.5 },
  { value: '0.75x', scale: 0.75 },
  { value: '1.0x', scale: 1.0 },
  { value: '1.25x', scale: 1.25 },
  { value: '1.5x', scale: 1.5 },
  { value: '2.0x', scale: 2.0 },
] as const

/** 探测失败时的默认值：宁可保持旧行为，也不要把功能藏掉。 */
const DEFAULT_CAPS: WorkflowCaps = {
  prompt: true,
  negative: true,
  negative_effective: true,
  negative_cfg: null,
  quality: true,
  orientation: true,
}

function scaleLabel(scale: number): string {
  const text = Number.isInteger(scale) ? scale.toFixed(1) : String(scale)
  return `${text}×`
}

function entryFor(
  preview: SizePreview | undefined,
  tier: string,
  ratio: string,
  defaultRatio: string,
): SizePreviewEntry | undefined {
  const byTier = preview?.[tier]
  if (!byTier) return undefined
  return byTier[ratio] ?? (defaultRatio ? byTier[defaultRatio] : undefined) ?? byTier['*']
}

/**
 * 按后端预演结果生成档位文案：
 * - seedvr → 真实输出分辨率
 * - scale / megapixels → 首程尺寸 +（有后置放大时）成品尺寸
 * - 缺 size_preview（探测尚未返回）→ 只写倍率，等后端结果到了再补像素
 *
 * 相同结果只保留一档，避免"8K 和 12K 被 clamp 成同一个尺寸"这类死选项。
 */
function qualityOptionsFor(
  params?: WorkflowParams,
  caps?: WorkflowCaps,
  ratio = '',
  preview?: SizePreview,
): QualityOption[] {
  const mode: QualityMode =
    params?.quality_mode ?? (caps?.quality ? 'scale' : 'none')
  if (mode === 'none') return []

  const allowed = params?.quality_tiers?.length
    ? new Set(params.quality_tiers.map(normalizeQualityKey))
    : null
  const tiers = allowed
    ? QUALITY_SCALES.filter((tier) => allowed.has(tier.value))
    : QUALITY_SCALES

  if (mode === 'seedvr') {
    return tiers.map(({ value }) => {
      const size = preview?.[value]?.['*']
      return {
        value,
        label: size?.width && size?.height ? `${size.width}×${size.height}` : value,
      }
    })
  }

  const effectiveRatio =
    ratio && (CANONICAL_RATIOS as readonly string[]).includes(ratio)
      ? ratio
      : params?.default_ratio || ''
  const defaultRatio = params?.default_ratio || ''
  const seen = new Set<string>()

  return tiers.flatMap(({ value, scale }) => {
    const size = entryFor(preview, value, effectiveRatio, defaultRatio)
    const actualScale = size?.scale ?? scale
    // 预演还没回来时按旧口径推断"原生"：1.0× 且当前就是默认比例
    const native =
      size?.native ??
      (actualScale === 1 && (!defaultRatio || effectiveRatio === defaultRatio))
    const prefix = native ? '原生 1.0×' : scaleLabel(actualScale)
    let label = prefix

    if (size?.width && size?.height) {
      const mp = size.megapixels ?? (size.width * size.height) / 1_000_000
      label += ` · ${Math.round(mp * 100) / 100}MP · ${size.width}×${size.height}`
      if (
        size.final_width &&
        size.final_height &&
        (size.final_width !== size.width || size.final_height !== size.height)
      ) {
        label += ` → 成品 ${size.final_width}×${size.final_height}`
      }
    } else if (size?.megapixels != null) {
      label += ` · ${Math.round(size.megapixels * 100) / 100}MP`
    }

    if (seen.has(label)) return []
    seen.add(label)
    return [{ value, label }]
  })
}

/**
 * 当前工作流的能力与真实档位。
 *
 * 提示词页 / 组合器 / 补跑面板 / 试跑面板 / 画廊重跑都从这里取，
 * 避免每个页面各写一遍"找 selected → 取 caps → 生成档位"。
 */
export function useWorkflowCaps(
  workflowPath: Ref<string>,
  allWorkflows: Ref<WorkflowRow[]>,
  aspectRatio?: Ref<string>,
) {
  const selected = computed(() =>
    allWorkflows.value.find((w) => w.path === workflowPath.value),
  )
  const caps = computed<WorkflowCaps>(() => selected.value?.caps ?? DEFAULT_CAPS)
  const params = computed<WorkflowParams | undefined>(() => selected.value?.params)
  const aspectRatios = computed<string[]>(() => {
    if (!caps.value.orientation) return []
    return params.value?.aspect_ratios?.length ? params.value.aspect_ratios : []
  })
  const defaultRatio = computed(() => params.value?.default_ratio ?? '')
  const qualityOptions = computed<QualityOption[]>(() =>
    qualityOptionsFor(
      params.value,
      caps.value,
      aspectRatio?.value ?? '',
      selected.value?.size_preview,
    ),
  )

  return { selected, caps, params, qualityOptions, aspectRatios, defaultRatio }
}
