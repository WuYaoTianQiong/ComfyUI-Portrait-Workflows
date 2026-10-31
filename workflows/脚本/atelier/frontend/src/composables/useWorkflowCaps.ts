import { computed } from 'vue'
import type { Ref } from 'vue'

import type { WorkflowRow } from './useWorkflows'

/**
 * 工作流「能注入什么」与「档位怎么算」的唯一实现。
 *
 * 原来这两件事分在 `utils/workflowCaps.ts`（探测 + 档位）和本文件（选中项 + 组合），
 * 两个模块名字几乎一样、都对外暴露，调用方分不清该用哪个，`WorkflowParams.vue`
 * 还自己又算了一遍档位。现在合成一个文件：**对外只有 `useWorkflowCaps` 与类型**，
 * 探测与档位计算都是模块私有（`命名规范.md` §8.2 / §9）。
 *
 * 规则与后端 `services/workflow_parser.detect_workflow_caps` 对齐：
 * 只标记真正会被 inject_prompt 改到的项，避免展示无效旋钮。
 *
 * 后端 `/api/workflows` 已经对磁盘工作流给出 caps；自定义工作流只存在
 * localStorage，后端看不到，只能在这里按同样的节点规则本地算一份。
 */

export interface WorkflowCaps {
  prompt: boolean
  negative: boolean
  quality: boolean
  orientation: boolean
}

type QualityMode = 'seedvr' | 'scale' | 'megapixels' | 'none'
type OrientationMode = 'swap' | 'knob' | 'none'

/**
 * 画质 / 方向参数的作用方式（与后端 `detect_workflow_params` 对齐）。
 *
 * 有了它，前端才能算出"这个工作流按 2K/4K/6K 实际会出多少像素"，
 * 而不是给所有工作流都摆同一排 2K..12K 的死档位。
 */
export interface WorkflowParams {
  quality_mode: QualityMode
  base_width?: number | null
  base_height?: number | null
  base_megapixels?: number | null
  orientation_mode: OrientationMode
}

export interface QualityOption {
  /** 提交给后端的值；与 injection 的倍率表保持一致 */
  value: string
  /** 展示给用户的文案，尽量写真实尺寸 / MP */
  label: string
}

const QUALITY_SCALES = [
  { value: '2K', scale: 0.75 },
  { value: '4K', scale: 1.0 },
  { value: '6K', scale: 1.25 },
  { value: '8K', scale: 1.5 },
  { value: '12K', scale: 2.0 },
] as const

/** 与后端 `seedvr_quality_map` 一致：超分档位直接对应真实输出分辨率。 */
const SEEDVR_SIZES: Record<string, [number, number]> = {
  '2K': [2160, 3840],
  '4K': [2560, 4096],
  '6K': [3200, 5120],
  '8K': [3840, 6400],
  '12K': [5120, 8192],
}

/** 与后端 `inject_prompt` 的 clamp(256, 4096) 一致。 */
function clampAxis(value: number): number {
  return Math.max(256, Math.min(4096, Math.round(value)))
}

/** 探测失败时的默认值：宁可保持旧行为，也不要把功能藏掉。 */
const DEFAULT_CAPS: WorkflowCaps = {
  prompt: true,
  negative: true,
  quality: true,
  orientation: true,
}

const TEXT_ENCODE_NODES: Record<string, string | null> = {
  CLIPTextEncode: null,
  TextEncodeQwenImage21: 'negative_prompt',
  TextEncodeQwenImageEdit: null,
  TextEncodeQwenImageEditPlus: null,
}

const ORIENTATION_KNOBS = ['aspect_ratio', 'resolution', 'preset', 'size']

type ApiNode = { class_type?: string; inputs?: Record<string, unknown> }

/** 把 API 格式 / UI 格式统一成"节点列表"，只取探测需要的字段。 */
function listNodes(raw: unknown): ApiNode[] {
  if (!raw || typeof raw !== 'object') return []
  const obj = raw as Record<string, unknown>
  if (Array.isArray(obj.nodes)) {
    return (obj.nodes as Array<Record<string, unknown>>).map((n) => ({
      class_type: typeof n.type === 'string' ? n.type : '',
      // UI 格式的 inputs 是数组，widget 值在 widgets_values，无法可靠还原；
      // 能力探测只依赖节点类型，这里不假装能读到具体输入。
      inputs: {},
    }))
  }
  return Object.values(obj).filter(
    (n): n is ApiNode => !!n && typeof n === 'object' && 'class_type' in (n as object),
  )
}

function asInt(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return Math.trunc(v)
  if (typeof v === 'string' && /^\d+$/.test(v.trim())) return Number(v)
  return null
}

/**
 * 从工作流文件内容探测能力（自定义工作流走这条）。
 *
 * 磁盘工作流用后端返回的 caps，这里只服务"内容只在本地"的那一份。
 */
export function detectCapsFromContent(content: string): WorkflowCaps {
  let raw: unknown
  try {
    raw = JSON.parse(content)
  } catch {
    return DEFAULT_CAPS
  }
  const nodes = listNodes(raw)
  if (!nodes.length) return DEFAULT_CAPS

  const isUiFormat = Array.isArray((raw as Record<string, unknown>).nodes)
  const apiById = new Map<string, ApiNode>()
  if (!isUiFormat) {
    for (const [id, node] of Object.entries(raw as Record<string, ApiNode>)) {
      if (node && typeof node === 'object') apiById.set(id, node)
    }
  }

  const caps: WorkflowCaps = {
    prompt: false,
    negative: false,
    quality: false,
    orientation: false,
  }

  const textNodes = nodes.filter(
    (n) => n.class_type && TEXT_ENCODE_NODES[n.class_type] !== undefined,
  )
  caps.prompt = textNodes.length > 0
  if (textNodes.length) {
    const first = textNodes[0].class_type ?? ''
    caps.negative = TEXT_ENCODE_NODES[first] !== null || textNodes.length >= 2
  }

  for (const node of nodes) {
    if (node.class_type === 'SeedVR2VideoUpscaler') caps.quality = true
    if (node.class_type !== 'EmptyLatentImage') continue

    if (isUiFormat) {
      // 无法读 widgets_values 的映射，按"有潜空间节点"乐观判定；
      // 真正不可用的组合交给后端注入时静默降级。
      caps.quality = true
      caps.orientation = true
      continue
    }

    const inputs = node.inputs ?? {}
    const w = asInt(inputs.width)
    const h = asInt(inputs.height)
    if (w !== null && h !== null) {
      caps.quality = true
      caps.orientation = w !== h
      continue
    }

    for (const key of ['width', 'height']) {
      const ref = inputs[key]
      if (!Array.isArray(ref) || typeof ref[0] !== 'string') continue
      const src = apiById.get(ref[0])
      if (!src) continue
      const srcInputs = src.inputs ?? {}
      if (ORIENTATION_KNOBS.some((k) => typeof srcInputs[k] === 'string')) {
        caps.orientation = true
      }
      const mp = srcInputs.megapixels
      if (typeof mp === 'number' && Number.isFinite(mp)) caps.quality = true
      break
    }
  }
  return caps
}

/** 自定义工作流的参数描述；规则与后端一致，UI 格式只能乐观判定。 */
export function detectParamsFromContent(content: string): WorkflowParams {
  let raw: unknown
  try {
    raw = JSON.parse(content)
  } catch {
    return { quality_mode: 'none', orientation_mode: 'none' }
  }
  const nodes = listNodes(raw)
  if (!nodes.length) return { quality_mode: 'none', orientation_mode: 'none' }

  const isUiFormat = Array.isArray((raw as Record<string, unknown>).nodes)
  const apiById = new Map<string, ApiNode>()
  if (!isUiFormat) {
    for (const [id, node] of Object.entries(raw as Record<string, ApiNode>)) {
      if (node && typeof node === 'object') apiById.set(id, node)
    }
  }

  const params: WorkflowParams = { quality_mode: 'none', orientation_mode: 'none' }
  const hasSeedvr = nodes.some((n) => n.class_type === 'SeedVR2VideoUpscaler')
  if (hasSeedvr) params.quality_mode = 'seedvr'

  const latent = nodes.find((n) => n.class_type === 'EmptyLatentImage')
  if (!latent) return params

  if (isUiFormat) {
    // 读不到 widgets_values：按"有潜空间节点"乐观判定，实际不可用时后端静默降级
    if (!hasSeedvr) params.quality_mode = 'scale'
    params.orientation_mode = 'swap'
    return params
  }

  const inputs = latent.inputs ?? {}
  const w = asInt(inputs.width)
  const h = asInt(inputs.height)
  if (w !== null && h !== null) {
    if (!hasSeedvr) {
      params.quality_mode = 'scale'
      params.base_width = w
      params.base_height = h
    }
    params.orientation_mode = w !== h ? 'swap' : 'none'
    return params
  }

  for (const key of ['width', 'height']) {
    const ref = inputs[key]
    if (!Array.isArray(ref) || typeof ref[0] !== 'string') continue
    const src = apiById.get(ref[0])
    if (!src) continue
    const srcInputs = src.inputs ?? {}
    if (ORIENTATION_KNOBS.some((k) => typeof srcInputs[k] === 'string')) {
      params.orientation_mode = 'knob'
    }
    const mp = srcInputs.megapixels
    if (!hasSeedvr && typeof mp === 'number' && Number.isFinite(mp)) {
      params.quality_mode = 'megapixels'
      params.base_megapixels = Math.round(mp * 1000) / 1000
    }
    break
  }
  return params
}

/**
 * 按工作流生成真实档位：
 * - seedvr → 真实输出分辨率
 * - scale → 基准尺寸 × 倍率（与后端同样 clamp）
 * - megapixels → 按面积倍率换算的 MP
 * - none → 空数组（不显示画质控件）
 *
 * 相同结果只保留一档，避免"8K 和 12K 被 clamp 成同一个尺寸"这类死选项。
 */
function qualityOptionsFor(
  params?: WorkflowParams,
  caps?: WorkflowCaps,
): QualityOption[] {
  const mode: QualityMode =
    params?.quality_mode ?? (caps?.quality ? 'scale' : 'none')
  if (mode === 'none') return []

  if (mode === 'seedvr') {
    return QUALITY_SCALES.map(({ value }) => ({
      value,
      label: `${value} · ${SEEDVR_SIZES[value][0]}×${SEEDVR_SIZES[value][1]}`,
    }))
  }

  const seen = new Set<string>()
  if (mode === 'megapixels') {
    const base = params?.base_megapixels
    return QUALITY_SCALES.flatMap(({ value, scale }) => {
      if (!base) return [{ value, label: value }]
      const mp = Math.round(base * scale * scale * 1000) / 1000
      const label = `${mp}MP`
      if (seen.has(label)) return []
      seen.add(label)
      return [{ value, label }]
    })
  }

  // scale：基准尺寸 × 倍率
  const w = params?.base_width
  const h = params?.base_height
  if (!w || !h) return QUALITY_SCALES.map(({ value }) => ({ value, label: value }))
  return QUALITY_SCALES.flatMap(({ value, scale }) => {
    const label = `${clampAxis(w * scale)}×${clampAxis(h * scale)}`
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
 * 档位也只在这里生成一次，`WorkflowParams.vue` 接收现成的 `qualityOptions`。
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
