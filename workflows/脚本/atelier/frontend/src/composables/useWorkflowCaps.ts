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
  /** 结构上有没有负向输入（不代表真的生效）。 */
  negative: boolean
  /** 负向条件是否真的参与采样：来自文本节点且 cfg>1。 */
  negative_effective: boolean
  /** 真实负向路径上的最大 CFG；null = 没有文本负向路径。 */
  negative_cfg: number | null
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

const RATIO_VALUES: Record<string, number> = Object.fromEntries(
  CANONICAL_RATIOS.map((r) => {
    const [a, b] = r.split(':').map(Number)
    return [r, a / b]
  }),
)

function closestRatio(width: number, height: number): string {
  if (!width || !height) return '1:1'
  const value = width / height
  return CANONICAL_RATIOS.reduce<string>((best, r) => {
    const score = Math.abs(Math.log(value / RATIO_VALUES[r]))
    const bestScore = Math.abs(Math.log(value / RATIO_VALUES[best]))
    return score < bestScore ? r : best
  }, '1:1')
}

function ratioValue(ratio: string): number {
  return RATIO_VALUES[ratio] ?? 1
}

function roundTo(value: number, multiple: number): number {
  return Math.max(multiple, Math.round(value / multiple) * multiple)
}

function scaleLabel(scale: number): string {
  const text = Number.isInteger(scale) ? scale.toFixed(1) : String(scale)
  return `${text}×`
}

function computeSize(
  ratio: string,
  megapixels: number,
  multiple: number,
  unit = 1_000_000,
): [number, number] {
  const r = ratioValue(ratio)
  const width = Math.sqrt(Math.max(0.01, megapixels) * unit * r)
  return [roundTo(width, multiple), roundTo(width / r, multiple)]
}

const LATENT_TYPES = new Set([
  'EmptyLatentImage',
  'EmptySD3LatentImage',
  'EmptyFlux2LatentImage',
])

function normalizeRatioText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const m = value.match(/(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)/)
  if (!m) return null
  const got = Number(m[1]) / Number(m[2])
  return CANONICAL_RATIOS.find((r) => Math.abs(RATIO_VALUES[r] - got) < 1e-6) ?? null
}

function parsePresetSize(value: unknown): { width: number; height: number; ratio: string } | null {
  if (typeof value !== 'string') return null
  const m = value.match(/(\d+)\s*[x×*]\s*(\d+)/i)
  if (!m) return null
  const width = Number(m[1])
  const height = Number(m[2])
  if (!width || !height) return null
  return { width, height, ratio: normalizeRatioText(value) ?? closestRatio(width, height) }
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

/** 探测失败时的默认值：宁可保持旧行为，也不要把功能藏掉。 */
const DEFAULT_CAPS: WorkflowCaps = {
  prompt: true,
  negative: true,
  negative_effective: true,
  negative_cfg: null,
  quality: true,
  orientation: true,
}

const TEXT_ENCODE_NODES: Record<string, string | null> = {
  CLIPTextEncode: null,
  TextEncodeQwenImage21: 'negative_prompt',
  TextEncodeQwenImageEdit: null,
  TextEncodeQwenImageEditPlus: null,
}

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

function asNumber(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v)
  return null
}

/** 带 negative 槽的引导节点；与后端 `_GUIDANCE_NODES` 一致。 */
const GUIDANCE_NODES = new Set(['KSampler', 'KSamplerAdvanced', 'CFGGuider'])

/**
 * 负向连线是否最终来自文本编码节点。
 *
 * `ConditioningZeroOut` 会切断判断；其他条件节点沿条件输入继续回溯。
 * 只用于 API 格式 —— UI 格式读不到连线，调用方会退回乐观判定。
 */
function negativeHasText(
  apiById: Map<string, ApiNode>,
  ref: unknown,
  seen = new Set<string>(),
): boolean {
  if (!Array.isArray(ref) || ref.length !== 2) return false
  const id = String(ref[0])
  if (seen.has(id)) return false
  const nextSeen = new Set(seen)
  nextSeen.add(id)
  const node = apiById.get(id)
  if (!node) return false
  const cls = node.class_type ?? ''
  if (cls === 'ConditioningZeroOut') return false
  if (cls in TEXT_ENCODE_NODES) return true
  const inputs = node.inputs ?? {}
  for (const [key, val] of Object.entries(inputs)) {
    if (['model', 'clip', 'vae', 'positive', 'control_net', 'image'].includes(key)) continue
    if (negativeHasText(apiById, val, nextSeen)) return true
  }
  return false
}

/** 与后端 `_detect_negative_effectiveness` 对齐。 */
function detectNegativeEffectiveness(apiById: Map<string, ApiNode>): {
  effective: boolean
  cfg: number | null
} {
  const cfgs: number[] = []
  let unknown = false
  for (const node of apiById.values()) {
    if (!GUIDANCE_NODES.has(node.class_type ?? '')) continue
    const inputs = node.inputs ?? {}
    if (!negativeHasText(apiById, inputs.negative)) continue
    const cfg = asNumber(inputs.cfg)
    if (cfg === null) unknown = true
    else cfgs.push(cfg)
  }
  if (unknown) return { effective: true, cfg: cfgs.length ? Math.max(...cfgs) : null }
  if (!cfgs.length) return { effective: false, cfg: null }
  const best = Math.max(...cfgs)
  return { effective: best > 1, cfg: best }
}

/**
 * latent → 输出路径上启用的 LatentUpscaleBy 倍率乘积。
 * UI 格式读不到连线，返回 1（磁盘工作流以后端返回的 params 为准）。
 */
function detectOutputScale(apiById: Map<string, ApiNode>): number {
  let latentId: string | null = null
  for (const [id, node] of apiById) {
    if (LATENT_TYPES.has(node.class_type ?? '')) {
      latentId = id
      break
    }
  }
  if (!latentId) return 1

  let scale = 1
  const seen = new Set<string>()
  const stack = [latentId]
  while (stack.length) {
    const nid = stack.pop() as string
    if (seen.has(nid)) continue
    seen.add(nid)
    for (const [cid, node] of apiById) {
      const inputs = node.inputs ?? {}
      const linked = Object.values(inputs).some(
        (v) => Array.isArray(v) && v.length === 2 && String(v[0]) === nid,
      )
      if (!linked) continue
      if (node.class_type === 'LatentUpscaleBy') {
        const s = inputs.scale_by
        if (typeof s === 'number' && Number.isFinite(s)) scale *= s
      }
      stack.push(cid)
    }
  }
  return Math.round(scale * 10000) / 10000
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
    negative_effective: false,
    negative_cfg: null,
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
  if (isUiFormat) {
    // UI 格式没有连线信息：按结构乐观判定，不误报"负向不生效"。
    caps.negative_effective = caps.negative
  } else {
    const negative = detectNegativeEffectiveness(apiById)
    caps.negative_effective = negative.effective
    caps.negative_cfg = negative.cfg
  }

  const hasImageInput = nodes.some((n) => n.class_type?.startsWith('LoadImage'))

  for (const node of nodes) {
    if (node.class_type === 'SeedVR2VideoUpscaler') caps.quality = true
    if (!LATENT_TYPES.has(node.class_type ?? '')) continue
    // 图生图/编辑工作流的尺寸由输入图决定
    if (hasImageInput) continue

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
      caps.orientation = true
      continue
    }

    for (const key of ['width', 'height']) {
      const ref = inputs[key]
      if (!Array.isArray(ref) || typeof ref[0] !== 'string') continue
      const src = apiById.get(ref[0])
      if (!src) continue
      // 任何空 latent 都能按比例退回字面量宽高
      caps.quality = true
      caps.orientation = true
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

  const params: WorkflowParams = {
    quality_mode: 'none',
    orientation_mode: 'none',
    aspect_ratios: [],
    default_ratio: '',
    multiple: 16,
    mp_unit: 'mp',
    post_scale: 1,
  }
  const hasSeedvr = nodes.some((n) => n.class_type === 'SeedVR2VideoUpscaler')
  if (hasSeedvr) params.quality_mode = 'seedvr'
  if (!isUiFormat) params.post_scale = detectOutputScale(apiById)

  const latent = nodes.find((n) => LATENT_TYPES.has(n.class_type ?? ''))
  if (!latent) return params

  if (isUiFormat) {
    // 读不到 widgets_values：按"有潜空间节点"乐观判定，实际不可用时后端静默降级
    if (!hasSeedvr) params.quality_mode = 'scale'
    params.orientation_mode = 'swap'
    params.aspect_ratios = [...CANONICAL_RATIOS]
    params.default_ratio = '2:3'
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
      params.base_megapixels = Math.round((w * h) / 10_000) / 100
    }
    params.orientation_mode = 'swap'
    params.aspect_ratios = [...CANONICAL_RATIOS]
    params.default_ratio = closestRatio(w, h)
    return params
  }

  for (const key of ['width', 'height']) {
    const ref = inputs[key]
    if (!Array.isArray(ref) || typeof ref[0] !== 'string') continue
    const src = apiById.get(ref[0])
    if (!src) continue
    const srcInputs = src.inputs ?? {}
    const rawMultiple = asInt(srcInputs.multiple)
    const ratioText = srcInputs.aspect_ratio ?? srcInputs.resolution ?? srcInputs.size
    const ratio = normalizeRatioText(ratioText)
    const mp = srcInputs.megapixels
    if (ratio && typeof mp === 'number' && Number.isFinite(mp)) {
      const multiple = rawMultiple ?? 8  // ResolutionSelector 的默认 multiple 是 8
      params.orientation_mode = 'knob'
      params.quality_mode = hasSeedvr ? params.quality_mode : 'megapixels'
      params.base_megapixels = Math.round(mp * 1000) / 1000
      params.mp_unit = 'mip'
      params.default_ratio = ratio
      params.multiple = multiple
      const [bw, bh] = computeSize(ratio, mp, multiple, 1024 * 1024)
      params.base_width = bw
      params.base_height = bh
      params.aspect_ratios = [...CANONICAL_RATIOS]
      return params
    }

    const preset = parsePresetSize(srcInputs.preset)
    if (preset) {
      params.orientation_mode = 'knob'
      params.quality_mode = hasSeedvr ? params.quality_mode : 'scale'
      params.base_width = preset.width
      params.base_height = preset.height
      params.base_megapixels = Math.round((preset.width * preset.height) / 10_000) / 100
      params.default_ratio = preset.ratio
      params.aspect_ratios = [...CANONICAL_RATIOS]
      return params
    }

    if (!hasSeedvr && typeof mp === 'number' && Number.isFinite(mp)) {
      params.quality_mode = 'megapixels'
      params.orientation_mode = 'knob'
      params.base_megapixels = Math.round(mp * 1000) / 1000
      params.mp_unit = 'mip'
      params.default_ratio = '1:1'
      params.multiple = rawMultiple ?? 16
      params.aspect_ratios = [...CANONICAL_RATIOS]
      return params
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
  ratio = '',
): QualityOption[] {
  const mode: QualityMode =
    params?.quality_mode ?? (caps?.quality ? 'scale' : 'none')
  if (mode === 'none') return []

  const allowed = params?.quality_tiers?.length
    ? new Set(params.quality_tiers)
    : null
  const tiers = allowed
    ? QUALITY_SCALES.filter((tier) => allowed.has(tier.value))
    : QUALITY_SCALES

  if (mode === 'seedvr') {
    return tiers.map(({ value }) => ({
      value,
      label: `${SEEDVR_SIZES[value][0]}×${SEEDVR_SIZES[value][1]}`,
    }))
  }

  const effectiveRatio =
    ratio && RATIO_VALUES[ratio] ? ratio : params?.default_ratio || ''
  const multiple = params?.multiple ?? 16
  const baseMp = params?.base_megapixels ?? null
  const baseW = params?.base_width ?? null
  const baseH = params?.base_height ?? null
  const defaultRatio = params?.default_ratio || ''
  const unit = params?.mp_unit === 'mip' ? 1024 * 1024 : 1_000_000
  const postScale = params?.post_scale ?? 1
  const seen = new Set<string>()
  const finalSize = (w: number, h: number): [number, number] => [
    roundTo(w * postScale, 8),
    roundTo(h * postScale, 8),
  ]

  if (mode === 'megapixels') {
    const base = baseMp
    return tiers.flatMap(({ value, scale }) => {
      if (!base) return [{ value, label: scaleLabel(scale) }]
      const mp = base * scale * scale
      const actualMp = (mp * unit) / 1_000_000
      const isNative = scale === 1 && (!defaultRatio || effectiveRatio === defaultRatio)
      const prefix = isNative ? '原生 1.0×' : scaleLabel(scale)
      let label = `${prefix} · ${Math.round(actualMp * 100) / 100}MP`
      if (effectiveRatio) {
        const [w, h] = computeSize(effectiveRatio, mp, multiple, unit)
        label += ` · ${w}×${h}`
        if (postScale !== 1) {
          const [fw, fh] = finalSize(w, h)
          label += ` → 成品 ${fw}×${fh}`
        }
      }
      if (seen.has(label)) return []
      seen.add(label)
      return [{ value, label }]
    })
  }

  // scale：基准比例 + 1.0× 用工作流原生尺寸，其余按比例/像素重算
  const exactBaseMp = baseW && baseH ? (baseW * baseH) / 1_000_000 : baseMp
  return tiers.flatMap(({ value, scale }) => {
    const mp = exactBaseMp ? exactBaseMp * scale * scale : null
    const isNative = scale === 1 && (!defaultRatio || effectiveRatio === defaultRatio)
    let w: number | null = null
    let h: number | null = null
    if (effectiveRatio && mp) {
      if (isNative && baseW && baseH) {
        w = baseW
        h = baseH
      } else {
        ;[w, h] = computeSize(effectiveRatio, mp, multiple, unit)
      }
    }
    const prefix = isNative ? '原生 1.0×' : scaleLabel(scale)
    let label = w && h
      ? `${prefix} · ${Math.round((mp ?? 0) * 100) / 100}MP · ${w}×${h}`
      : prefix
    if (w && h && postScale !== 1) {
      const [fw, fh] = finalSize(w, h)
      label += ` → 成品 ${fw}×${fh}`
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
 * 档位也只在这里生成一次，`WorkflowParams.vue` 接收现成的 `qualityOptions`。
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
    qualityOptionsFor(params.value, caps.value, aspectRatio?.value ?? ''),
  )

  return { selected, caps, params, qualityOptions, aspectRatios, defaultRatio }
}
