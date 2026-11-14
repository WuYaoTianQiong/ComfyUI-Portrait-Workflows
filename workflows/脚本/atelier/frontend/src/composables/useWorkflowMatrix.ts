import { computed, ref, watch } from 'vue'

import type { WorkflowRow } from '../api/workflows'
import type { WorkflowParams } from './useWorkflowCaps'
import { workflowDisplayName } from './recipeModel'

/**
 * 「同一提示词 × 多工作流」横评的计划层。
 *
 * 横评的难点不是多选，而是**条件可比**：同一个「比例 × 画质档」在不同工作流下
 * 出的尺寸并不相同（倍率档 vs 目标 MP 档），有的工作流根本没有这一档。
 * 这里把每个工作流各自求解成一行真实参数，并把被改写的条件显式报出来，
 * 而不是静默用一套参数提交、让用户拿不可比的图下结论。
 *
 * 纯函数 `buildMatrixPlan` 不碰 DOM / 网络，尺寸一律读后端 `size_preview`
 * （唯一真源，见 useWorkflowCaps），前端不再自己算像素。
 */

export type MatrixAlign = 'native' | 'first' | 'ref'

/** 与合成台 `MAX_BATCH_RECIPES` 同口径，不新造上限。 */
export const MATRIX_MAX_TOTAL = 100
/** 超过这个张数就提示分批：连续压测会把 GGUF 反量化的 ComfyUI 压崩。 */
export const MATRIX_SOFT_LIMIT = 12
/** 对齐后仍超过这个偏差就认为「没对齐」，不能当同条件横评。 */
export const MATRIX_ALIGN_TOLERANCE = 0.02
/** 横评基准尺寸：2026-11-12 手工横评用的就是这一档。 */
export const MATRIX_REF_SIZE: readonly [number, number] = [1024, 1536]

const STORE_KEY = 'pb.promptMatrix'

export interface MatrixRow {
  path: string
  name: string
  shortName: string
  /** 该行实际使用的出图比例（逐流覆盖后的值） */
  ratio: string
  /** 实际提交的档位（可能已回退） */
  tier: string
  /** 请求档位不可用、被换成了别的档 */
  tierFallback: boolean
  /** 用户请求的档位（回退解释用） */
  requestedTier: string
  /** 该工作流实际拥有的档位列表（回退解释用） */
  tiers: string[]
  /** 档位机制：scale 倍率 / megapixels 目标MP（回退解释用） */
  qualityMode: string
  width: number
  height: number
  pixels: number
  /** 相对对齐目标的像素量偏差；native 模式恒为 0 */
  deviation: number
  negativeEffective: boolean
  /** 该工作流能否参与文本横评 */
  supported: boolean
  /** 不可参与的原因（supported=false 时有值） */
  reason: string
}

export interface MatrixWarning {
  kind: 'warn' | 'info' | 'ok'
  text: string
}

export type MatrixCellStatus = 'idle' | 'queued' | 'running' | 'done' | 'error'

/**
 * 格子里的成图。
 *
 * 两种来源共用一个形状：任务快照只给 filename/subfolder/type（试跑没有载体，
 * 图不挂在任何提示词下），画廊回流给完整 HistoryItem（带 id，可收藏）。
 * 有 id 才允许写操作，没 id 也能看大图与定位。
 */
export interface MatrixImage {
  id?: number
  filename: string
  subfolder?: string | null
  img_type?: string | null
  is_favorite?: boolean
}

/** 一格 = 一个工作流 × 一个种子 = 一个 job（一流一 job，图片归属才不会错标）。 */
export interface MatrixCell {
  key: string
  path: string
  col: number
  seed: number
  tier: string
  width: number
  height: number
  status: MatrixCellStatus
  jobId: number | null
  error: string
  image: MatrixImage | null
}

export function cellKey(path: string, col: number): string {
  return `${path}#${col}`
}

/** 由计划铺出待提交的格子；种子在铺格时定死，提交与展示才是同一个值。 */
export function buildCells(plan: MatrixPlan, baseSeed: number, lock: boolean): MatrixCell[] {
  const cells: MatrixCell[] = []
  for (const row of plan.usable) {
    for (let col = 0; col < plan.count; col += 1) {
      cells.push({
        key: cellKey(row.path, col),
        path: row.path,
        col,
        seed: seedForCell(baseSeed, col, lock),
        tier: row.tier,
        width: row.width,
        height: row.height,
        status: 'idle',
        jobId: null,
        error: '',
        image: null,
      })
    }
  }
  return cells
}

export interface MatrixFlowOverride {
  ratio?: string
  tier?: string
}

export interface MatrixPlanInput {
  workflows: readonly WorkflowRow[]
  paths: readonly string[]
  ratio: string
  tier: string
  /** 逐流覆盖：试跑可以给每个工作流单独一套比例/档位；缺省沿用全局 ratio/tier。 */
  overrides?: Record<string, MatrixFlowOverride>
  align: MatrixAlign
  count: number
}

export interface MatrixPlan {
  rows: MatrixRow[]
  /** 能真正提交的行 */
  usable: MatrixRow[]
  count: number
  total: number
  overLimit: boolean
  targetSize: [number, number] | null
  warnings: MatrixWarning[]
  negativeEffective: number
}

interface StoredMatrix {
  enabled: boolean
  paths: string[]
  align: MatrixAlign
}

function readStored(key = STORE_KEY): Partial<StoredMatrix> {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as Partial<StoredMatrix>) : {}
  } catch {
    return {}
  }
}

/** 档位字符串 → 倍率数值，用于挑「最接近」的档。 */
export function tierScale(tier: string): number {
  const n = Number.parseFloat(tier)
  return Number.isFinite(n) && n > 0 ? n : 1
}

/** 该工作流允许的档位：显式 quality_tiers 优先，否则用后端预演里出现过的档。 */
export function availableTiers(wf: WorkflowRow): string[] {
  const declared = wf.params?.quality_tiers
  if (declared && declared.length) return [...declared]
  return Object.keys(wf.size_preview ?? {})
}

/** 请求档位不可用时回退：先用工作流默认档，再按倍率最接近挑一个。 */
export function resolveTier(wf: WorkflowRow, tier: string): { tier: string; fallback: boolean } {
  const tiers = availableTiers(wf)
  if (!tiers.length || tiers.includes(tier)) return { tier, fallback: false }
  const preferred = wf.params?.default_quality
  if (preferred && tiers.includes(preferred)) return { tier: preferred, fallback: true }
  const want = tierScale(tier)
  const closest = tiers
    .slice()
    .sort((a, b) => Math.abs(tierScale(a) - want) - Math.abs(tierScale(b) - want))[0]
  return { tier: closest ?? tier, fallback: true }
}

/** 读后端预演尺寸；`final_*` 是沿输出路径放大后的真实成品尺寸。 */
export function previewSize(
  wf: WorkflowRow,
  tier: string,
  ratio: string,
): [number, number] | null {
  const entry = wf.size_preview?.[tier]?.[ratio]
  if (!entry) return null
  const w = entry.final_width ?? entry.width
  const h = entry.final_height ?? entry.height
  if (!w || !h) return null
  return [w, h]
}

/** 在允许档位里挑像素量最接近目标的一档（对数距离，避免大档天然占优）。 */
export function nearestTier(
  wf: WorkflowRow,
  ratio: string,
  target: readonly [number, number],
): { tier: string; size: [number, number] } | null {
  const targetPixels = target[0] * target[1]
  if (!targetPixels) return null
  let best: { tier: string; size: [number, number]; distance: number } | null = null
  for (const tier of availableTiers(wf)) {
    const size = previewSize(wf, tier, ratio)
    if (!size) continue
    const distance = Math.abs(Math.log((size[0] * size[1]) / targetPixels))
    if (!best || distance < best.distance) best = { tier, size, distance }
  }
  return best ? { tier: best.tier, size: best.size } : null
}

/**
 * 该工作流能不能参与「纯文本提示词」横评。
 *
 * 只看 `caps.prompt` 不够：编辑 / 换衣 / 参考类同样注入提示词（指令），
 * 但它们有 LoadImage 输入槽，不喂图就跑不出东西。横评是文生图对比，
 * 必须同时要求「注入提示词」且「没有图片输入槽」。
 */
export function matrixSupport(wf: WorkflowRow): { supported: boolean; reason: string } {
  const slots = wf.image_slots ?? 0
  if (slots > 0) {
    return { supported: false, reason: `需要 ${slots} 张输入图（编辑 / 参考 / 超分类）` }
  }
  if (wf.caps && !wf.caps.prompt) {
    return { supported: false, reason: '不注入提示词（视频 / 反推类）' }
  }
  return { supported: true, reason: '' }
}

function alignTarget(
  align: MatrixAlign,
  rows: readonly WorkflowRow[],
  ratioOf: (wf: WorkflowRow) => string,
  tierOf: (wf: WorkflowRow) => string,
): [number, number] | null {
  if (align === 'ref') return [MATRIX_REF_SIZE[0], MATRIX_REF_SIZE[1]]
  if (align === 'first') {
    const first = rows[0]
    if (!first) return null
    return previewSize(first, resolveTier(first, tierOf(first)).tier, ratioOf(first))
  }
  return null
}

/** 逐行取比例：独立覆盖优先，其次全局值，最后退回该工作流原生比例。 */
function ratioOfRow(wf: WorkflowRow, input: MatrixPlanInput): string {
  return input.overrides?.[wf.path]?.ratio || input.ratio || wf.params?.default_ratio || ''
}

/** 逐行取档位：独立覆盖优先，否则沿用全局档位。 */
function tierOfRow(wf: WorkflowRow, input: MatrixPlanInput): string {
  return input.overrides?.[wf.path]?.tier || input.tier
}

/** 把「选中的工作流 + 目标条件」求解成逐行真实参数与公平性提示。 */
export function buildMatrixPlan(input: MatrixPlanInput): MatrixPlan {
  const count = Math.max(1, Math.min(4, Math.trunc(input.count) || 1))
  const picked = input.paths
    .map((path) => input.workflows.find((wf) => wf.path === path))
    .filter((wf): wf is WorkflowRow => Boolean(wf))
  const ratioOf = (wf: WorkflowRow) => ratioOfRow(wf, input)
  const tierOf = (wf: WorkflowRow) => tierOfRow(wf, input)
  // 各流比例不同时，「同尺寸对齐」已无统一口径：自动退回各自原生档，并显式提示。
  const mixedRatio = new Set(picked.map(ratioOf)).size > 1
  const align: MatrixAlign = mixedRatio && input.align !== 'native' ? 'native' : input.align
  const target = alignTarget(align, picked, ratioOf, tierOf)

  const rows: MatrixRow[] = picked.map((wf) => {
    const support = matrixSupport(wf)
    const ratio = ratioOf(wf)
    const requestedTier = tierOf(wf)
    const resolved = resolveTier(wf, requestedTier)
    let tier = resolved.tier
    let fallback = resolved.fallback
    let size = previewSize(wf, tier, ratio)
    if (target) {
      const near = nearestTier(wf, ratio, target)
      if (near) {
        tier = near.tier
        size = near.size
        fallback = tier !== requestedTier
      }
    }
    const width = size?.[0] ?? 0
    const height = size?.[1] ?? 0
    const pixels = width * height
    const deviation = target && pixels ? pixels / (target[0] * target[1]) - 1 : 0
    const noSize = !size
    return {
      path: wf.path,
      name: wf.name,
      // 与 WorkflowPicker 的展示名一致：去扩展名 + 下划线换空格，
      // 否则选择器里叫「MOSS 文生图」、矩阵里叫「MOSS_文生图」，看起来像两个流。
      shortName: workflowDisplayName(wf.name).replace(/_/g, ' '),
      ratio,
      tier,
      tierFallback: fallback,
      requestedTier,
      tiers: availableTiers(wf),
      qualityMode: wf.params?.quality_mode ?? 'scale',
      width,
      height,
      pixels,
      deviation,
      negativeEffective: wf.caps?.negative_effective === true,
      supported: support.supported && !noSize,
      reason: support.reason || (noSize ? `没有「${ratio} × ${tier}」的预演尺寸` : ''),
    }
  })

  const usable = rows.filter((r) => r.supported)
  const total = usable.length * count
  const warnings: MatrixWarning[] = []

  const dropped = rows.filter((r) => !r.supported)
  if (dropped.length) {
    warnings.push({
      kind: 'warn',
      text: `${dropped.map((r) => `${r.shortName}（${r.reason}）`).join('；')} 不参与本次横评。`,
    })
  }

  if (mixedRatio && input.align !== 'native') {
    warnings.push({
      kind: 'warn',
      text: '各流比例不同，尺寸对齐已自动切回「各自原生档」；要比同条件请把各流比例设成同一个。',
    })
  }

  const fallbacks = usable.filter((r) => r.tierFallback)
  if (fallbacks.length) {
    warnings.push({
      kind: 'warn',
      text: `${fallbacks
        .map((r) => `${r.shortName} 不支持 ${r.requestedTier}，改用 ${r.tier}（${r.width}×${r.height}）`)
        .join('；')}。横评条件已被改写。`,
    })
  }

  if (align === 'native' && usable.length > 1) {
    const sizes = Array.from(new Set(usable.map((r) => `${r.width}×${r.height}`)))
    if (sizes.length > 1) {
      const condition = mixedRatio ? '' : `同一「${input.ratio} × ${input.tier}」下`
      warnings.push({
        kind: 'warn',
        text: `${condition}各流原生尺寸不同：${sizes.join(' / ')}。要严格同条件，把尺寸对齐切到「对齐到 ${MATRIX_REF_SIZE[0]}×${MATRIX_REF_SIZE[1]}」。`,
      })
    }
  }

  if (align !== 'native' && usable.length) {
    const off = usable.filter((r) => Math.abs(r.deviation) > MATRIX_ALIGN_TOLERANCE)
    if (off.length) {
      warnings.push({
        kind: 'warn',
        text: `已按各流机制选最接近档，仍有偏差：${off
          .map((r) => `${r.shortName} ${r.deviation > 0 ? '+' : ''}${Math.round(r.deviation * 100)}%`)
          .join('、')}。倍率档与目标 MP 档无法精确对齐。`,
      })
    } else {
      warnings.push({ kind: 'ok', text: '各流已对齐到同一目标像素量，横评条件一致。' })
    }
  }

  const negativeEffective = usable.filter((r) => r.negativeEffective).length
  if (usable.length && negativeEffective === 0) {
    warnings.push({
      kind: 'info',
      text: `负向提示词 0 / ${usable.length} 生效（结构有输入但 CFG=1 也算不生效），不要用它解释这批图的差异。`,
    })
  }

  if (total > MATRIX_SOFT_LIMIT) {
    warnings.push({
      kind: 'info',
      text: `共 ${total} 张，建议分批提交：连续压测会把 GGUF 反量化的 ComfyUI 压崩。`,
    })
  }

  return {
    rows,
    usable,
    count,
    total,
    overLimit: total > MATRIX_MAX_TOTAL,
    targetSize: target,
    warnings,
    negativeEffective,
  }
}

/** 锁定同种子时列方向 +1；解锁则每格独立随机（只能比风格，不能比细节）。 */
export function seedForCell(baseSeed: number, col: number, lock: boolean): number {
  if (lock) return Math.max(0, Math.trunc(baseSeed) + col)
  return Math.floor(Math.random() * 2 ** 31)
}

/**
 * 横评的界面状态：开关、选中集合、对齐方式。
 *
 * 选中集合**独立于全局默认工作流**（`useSettings().workflowPath`）：
 * 横评挑了 5 个流不该把别处的单跑默认也改掉。
 */
export function useWorkflowMatrix(storeKey = STORE_KEY) {
  const stored = readStored(storeKey)
  const enabled = ref(stored.enabled === true)
  const paths = ref<string[]>(Array.isArray(stored.paths) ? stored.paths : [])
  const align = ref<MatrixAlign>(
    stored.align === 'first' || stored.align === 'ref' ? stored.align : 'native',
  )

  watch([enabled, paths, align], () => {
    try {
      localStorage.setItem(
        storeKey,
        JSON.stringify({ enabled: enabled.value, paths: paths.value, align: align.value }),
      )
    } catch {
      /* 隐私模式下忽略 */
    }
  })

  /** 第一次开横评时，用当前单跑工作流打底，避免开了开关却一个流都没选。 */
  function seedFrom(path: string) {
    if (!paths.value.length && path) paths.value = [path]
  }

  function togglePath(path: string) {
    paths.value = paths.value.includes(path)
      ? paths.value.filter((p) => p !== path)
      : [...paths.value, path]
  }

  function setPaths(next: readonly string[]) {
    paths.value = [...next]
  }

  function movePath(from: number, to: number) {
    if (from === to || from < 0 || to < 0) return
    const list = paths.value.slice()
    if (from >= list.length || to >= list.length) return
    const [item] = list.splice(from, 1)
    list.splice(to, 0, item)
    paths.value = list
  }

  return { enabled, paths, align, seedFrom, togglePath, setPaths, movePath }
}

/** 供组件用：把响应式输入包成计划。 */
export function useMatrixPlan(
  workflows: () => readonly WorkflowRow[],
  paths: () => readonly string[],
  ratio: () => string,
  tier: () => string,
  align: () => MatrixAlign,
  count: () => number,
) {
  return computed(() =>
    buildMatrixPlan({
      workflows: workflows(),
      paths: paths(),
      ratio: ratio(),
      tier: tier(),
      align: align(),
      count: count(),
    }),
  )
}

export type { WorkflowParams }
