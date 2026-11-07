/**
 * 参考图库「操作记忆」持久化（2026-11-05）。
 *
 * 背景（决策变更）：阶段 3 的 M3 决策是「三槽草稿不做 localStorage / IndexedDB
 * 持久化」，理由是用户当时确认草稿都是测试数据。**2026-11-05 用户要求记忆操作，
 * 取代 M3 不持久化**：刷新页面后三槽、画风、工作流、种子、画质档、比例与最后页签
 * 都必须恢复。
 *
 * 键名沿用全站既有习惯（`pb.` 前缀 + snake_case + 版本后缀）：
 * - `pb.reference_studio_v1`：一个 JSON 对象，字段见 {@link ReferenceStudioSettings}；
 * - `pb.reference_tab_v1`：最后一次访问的参考图库页签（纯字符串，读时再校验）。
 *
 * 失败策略：
 * - 读全包 try/catch：隐私模式下**访问 localStorage 本身**也可能抛 SecurityError；
 * - 写失败静默，不影响交互（本次会话仍按内存值工作）；
 * - 写入 300ms 防抖：三槽 toggle / 尺寸档连点只落一份盘；
 * - 数据做最小校验：非法 JSON、非对象、任何字段类型不对 → 整体丢弃并回落默认，
 *   绝不把脏数据带进页面。
 *
 * 注意：本模块**不**导入业务 composable（只用 `import type`），避免
 * `useReferenceRecipe` → `useReferenceRecipeDraft` → 本模块 的运行时循环依赖。
 */

import type { ReferenceLibraryId } from '../api/reference'
import {
  clonePersonBVariants,
  cloneRecipeTextFragments,
  createEmptyRecipeTextFragments,
  isRecipeSlotMode,
} from './recipeTextFragments'
import type {
  RecipePersonBVariant,
  RecipeSlotMode,
  RecipeTextFragments,
} from './recipeTextFragments'
import type { RecipeStyle } from './useReferenceRecipe'

/** 合成台参数 + 三槽选择的持久化键（带版本后缀）。 */
export const REFERENCE_STUDIO_STORAGE_KEY = 'pb.reference_studio_v1'
/** 最后访问页签的持久化键（与合成台参数分开，切页签时即时写、无需防抖）。 */
export const REFERENCE_TAB_STORAGE_KEY = 'pb.reference_tab_v1'
/** 写盘防抖间隔：避免每次 toggle 都写 localStorage。 */
export const REFERENCE_STUDIO_WRITE_DEBOUNCE_MS = 300
/**
 * 默认基础种子。
 *
 * 与 `useReferenceRecipe.DEFAULT_RECIPE_SEED` 保持同一数值（100000）。为避免
 * 运行时循环依赖，这里单独声明，并由单测锁定两者一致。
 */
export const DEFAULT_REFERENCE_STUDIO_BASE_SEED = 100000

/** 三槽键（与配方草稿保持一致）。 */
export type ReferenceStudioSlotKey = 'portrait' | 'costume' | 'pose'

/** 已选条目的最小持久化形状：只存恢复与展示必需的信息。 */
export interface StoredReferenceSlotEntry {
  /** 库条目 id；恢复时按它回查库数据。本地上传图为 `upload:<path>`。 */
  id: string
  /** 条目所属库；同一 id 在不同库可能重复，必须一起匹配。 */
  library: ReferenceLibraryId
  /** 展示名；库数据匹配失败时不会造卡片，但保留字段便于排障与降级展示。 */
  name: string
  /** 缩略图地址；同上。 */
  thumbnail: string
  /** 仅姿势槽：加入时是白模还是深度图。 */
  useDepth?: boolean
  /**
   * 本地上传图的绝对路径（`data_dir/uploads/...`）。
   *
   * 有该字段时**不走库匹配**：直接按它重建一张「上传图」卡片。
   * 文件被删时提交会 400（后端校验存在性），与库条目被删同口径。
   */
  path?: string
}

/**
 * 第 4 槽（发型库背面图 / 上传单图 + 文字补充）的持久化形状。
 *
 * `text` 只在有图时生效（后端「图为主 + 文本补充」口径）；`source=empty` 时
 * 其余字段一律为空串，避免把残留 id 当成已选。
 */
export interface StoredReferenceExtraSlot {
  source: 'empty' | 'library' | 'upload'
  library: 'hair' | ''
  id: string
  path: string
  name: string
  text: string
}

/** 空第 4 槽；新建草稿 / 清空草稿 / 旧快照缺字段都用它。 */
export function createEmptyExtraSlot(): StoredReferenceExtraSlot {
  return {
    source: 'empty',
    library: '',
    id: '',
    path: '',
    name: '',
    text: '',
  }
}

/** `pb.reference_studio_v1` 的完整结构。 */
export interface ReferenceStudioSettings {
  portrait: StoredReferenceSlotEntry[]
  costume: StoredReferenceSlotEntry[]
  pose: StoredReferenceSlotEntry[]
  /** 第 4 槽；旧快照缺字段按空处理。 */
  extra: StoredReferenceExtraSlot
  /** 画风预设；后端只认 none / realistic。 */
  style: RecipeStyle
  /** 工作流文件名 / 库内路径；空串表示沿用后端默认工作流。 */
  workflow: string
  /** 基础种子（第 i 组 = baseSeed + i）。 */
  baseSeed: number
  /** 已选画质档（按工作流 caps 过滤后的值）。 */
  qualities: string[]
  /** 已选输出比例（按工作流 caps 过滤后的值）。 */
  ratios: string[]
  /**
   * 内部元数据：用户是否已经配置过尺寸档。
   *
   * 用于区分「首次进入，沿用工作流默认档」与「用户主动清空了所有档位」：
   * 前者不覆盖 `useWorkflowCaps` 的 reconcile 结果，后者必须持久化为空数组。
   */
  sizesConfigured: boolean
  /**
   * 八类文本补充碎片（2026-11-06 新增）。
   *
   * 只存 `{type, content}` 全文：体积预估 8 类 × 2 条 × 783 字 ≈ 12KB，可接受；
   * 从旧快照读回时缺字段按空表处理（不整体丢弃其余设置）。
   */
  textFragments: RecipeTextFragments
  /** 用户手填的负向提示词；最终负向 = 后端自动抽取 + 这里的内容。 */
  negativePrompt: string
  /** 双人姿势的人物 B 文字设定；空串 = 不启用 B 文字。 */
  personBText: string
  /**
   * v1.5：人物 B 的文字变体列表（B 专属碎片 + 自由文字）。
   *
   * 旧快照没有该字段 → 空数组；草稿层会把旧 `personBText` 迁移成第一条变体。
   */
  personBVariants: RecipePersonBVariant[]
  /**
   * 三槽模式（P2 替代态，方案 §4.4）。
   *
   * `null` 表示旧快照没有该字段：调用方按
   * 「有图 → image；无图 + 对应碎片非空 → text；否则 empty」推导。
   */
  portraitMode: RecipeSlotMode | null
  costumeMode: RecipeSlotMode | null
  poseMode: RecipeSlotMode | null
  /**
   * 跨源补充开关（P4）。旧快照没有该字段按 false；
   * 只在对应槽为 image 模式时有意义。
   */
  portraitSupplement: boolean
  costumeSupplement: boolean
  poseSupplement: boolean
  /** 最近一次「同源整套随机」的来源；仅用于展示，不参与提交。 */
  recipeSourceId: number | null
  recipeSourceName: string
}

/** 合法库标识；校验时用于收窄字符串。 */
const LIBRARY_IDS: ReadonlySet<string> = new Set<ReferenceLibraryId>([
  'pose',
  'costume',
  'costume-anime',
  'portrait',
  'hair',
])

/** 隐私模式下访问 `globalThis.localStorage` 可能直接抛错，统一吞掉。 */
function getStorage(): Storage | null {
  try {
    if (typeof globalThis.localStorage === 'undefined') return null
    return globalThis.localStorage
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** 字符串数组校验：任何非字符串项都视为脏数据。 */
function parseStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  if (!value.every((item): item is string => typeof item === 'string')) return null
  return [...value]
}

/** 单条已选记录校验；失败返回 null，由调用方整体丢弃。 */
function parseSlotEntry(value: unknown): StoredReferenceSlotEntry | null {
  if (!isRecord(value)) return null
  const { id, library, name, thumbnail, useDepth, path } = value
  if (typeof id !== 'string' || id.length === 0) return null
  if (typeof library !== 'string' || !LIBRARY_IDS.has(library)) return null
  if (typeof name !== 'string' || typeof thumbnail !== 'string') return null
  if (useDepth !== undefined && typeof useDepth !== 'boolean') return null
  if (path !== undefined && (typeof path !== 'string' || path.length === 0)) return null

  const entry: StoredReferenceSlotEntry = {
    id,
    library: library as ReferenceLibraryId,
    name,
    thumbnail,
  }
  if (typeof useDepth === 'boolean') entry.useDepth = useDepth
  if (typeof path === 'string') entry.path = path
  return entry
}

/** 槽位数组校验：任一条目非法即整体失败。 */
function parseSlotEntries(value: unknown): StoredReferenceSlotEntry[] | null {
  if (!Array.isArray(value)) return null
  const entries: StoredReferenceSlotEntry[] = []
  for (const item of value) {
    const entry = parseSlotEntry(item)
    if (!entry) return null
    entries.push(entry)
  }
  return entries
}

/**
 * 第 4 槽校验：缺字段 / 脏数据一律回落空槽，不丢整份快照。
 *
 * 只有 `library`（hair + id）与 `upload`（path）两种有效来源；任一必填项
 * 为空即视为未选，避免刷新后出现「有名字但没有图」的幽灵槽位。
 */
function parseExtraSlot(value: unknown): StoredReferenceExtraSlot {
  const empty = createEmptyExtraSlot()
  if (!isRecord(value)) return empty
  const source = value.source
  if (source !== 'library' && source !== 'upload') return empty
  const library = value.library === 'hair' ? 'hair' : ''
  const id = typeof value.id === 'string' ? value.id : ''
  const path = typeof value.path === 'string' ? value.path : ''
  if (source === 'library' && (!id || library !== 'hair')) return empty
  if (source === 'upload' && !path) return empty
  return {
    source,
    library,
    id: source === 'library' ? id : '',
    path: source === 'upload' ? path : '',
    name: typeof value.name === 'string' ? value.name : '',
    text: typeof value.text === 'string' ? value.text : '',
  }
}

/** 画风校验；后端只认这两项。 */
function parseStyle(value: unknown): RecipeStyle | null {
  return value === 'none' || value === 'realistic' ? value : null
}

/**
 * 槽位模式校验：合法值原样保留；缺字段 / 非法值一律返回 null。
 *
 * 返回 null 不丢弃整份快照：旧数据没有 mode 字段，调用方按条目数与碎片推导。
 */
function parseSlotMode(value: unknown): RecipeSlotMode | null {
  return isRecipeSlotMode(value) ? value : null
}

/** P4 开关容错：只认显式 true；缺字段 / 脏数据按 false，不丢整份快照。 */
function parseSupplementFlag(value: unknown): boolean {
  return value === true
}

/** 种子校验：非负有限数，向下取整（与 `setBaseSeed` 口径一致）。 */
function parseBaseSeed(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return null
  return Math.trunc(value)
}

/**
 * 完整对象校验。
 *
 * 任何字段缺失 / 类型不对都返回 null（整体丢弃）。`sizesConfigured` 可缺省，
 * 缺省视为 false，兼容早期没有该元数据的写入。
 */
export function parseReferenceStudioSettings(
  value: unknown,
): ReferenceStudioSettings | null {
  if (!isRecord(value)) return null

  const portrait = parseSlotEntries(value.portrait)
  const costume = parseSlotEntries(value.costume)
  const pose = parseSlotEntries(value.pose)
  const style = parseStyle(value.style)
  const qualities = parseStringArray(value.qualities)
  const ratios = parseStringArray(value.ratios)
  const baseSeed = parseBaseSeed(value.baseSeed)
  const workflow = typeof value.workflow === 'string' ? value.workflow : null

  if (
    !portrait ||
    !costume ||
    !pose ||
    !style ||
    !qualities ||
    !ratios ||
    baseSeed === null ||
    workflow === null
  ) {
    return null
  }

  if (value.sizesConfigured !== undefined && typeof value.sizesConfigured !== 'boolean') {
    return null
  }

  // 2026-11-06 扩展字段：**容错读回**，缺字段 / 结构不符按空处理，
  // 不因为新增的可选字段把整份旧快照（三槽 / 画风 / 种子）一起丢掉。
  const textFragments = cloneRecipeTextFragments(value.textFragments)
  const negativePrompt =
    typeof value.negativePrompt === 'string' ? value.negativePrompt : ''
  const personBText =
    typeof value.personBText === 'string' ? value.personBText : ''
  // v1.5 扩展字段：容错读回；旧快照缺字段 → 空数组（由草稿层迁移旧文本）。
  const personBVariants = clonePersonBVariants(value.personBVariants)

  return {
    portrait,
    costume,
    pose,
    extra: parseExtraSlot(value.extra),
    style,
    workflow,
    baseSeed,
    qualities,
    ratios,
    sizesConfigured: value.sizesConfigured === true,
    textFragments,
    negativePrompt,
    personBText,
    personBVariants,
    // P2 扩展字段：同样容错读回，缺字段 = null（由调用方推导）。
    portraitMode: parseSlotMode(value.portraitMode),
    costumeMode: parseSlotMode(value.costumeMode),
    poseMode: parseSlotMode(value.poseMode),
    // P4 扩展字段：缺字段 / 脏数据 = false。
    portraitSupplement: parseSupplementFlag(value.portraitSupplement),
    costumeSupplement: parseSupplementFlag(value.costumeSupplement),
    poseSupplement: parseSupplementFlag(value.poseSupplement),
    // 随机整套来源：可选展示字段，缺字段 / 脏数据按空处理。
    recipeSourceId:
      typeof value.recipeSourceId === 'number' && Number.isFinite(value.recipeSourceId)
        ? Math.trunc(value.recipeSourceId)
        : null,
    recipeSourceName:
      typeof value.recipeSourceName === 'string' ? value.recipeSourceName : '',
  }
}

/** 默认值；与无存储时的现有页面行为保持逐字一致。 */
export function createDefaultReferenceStudioSettings(): ReferenceStudioSettings {
  return {
    portrait: [],
    costume: [],
    pose: [],
    extra: createEmptyExtraSlot(),
    style: 'realistic',
    workflow: '',
    baseSeed: DEFAULT_REFERENCE_STUDIO_BASE_SEED,
    qualities: [],
    ratios: [],
    sizesConfigured: false,
    textFragments: createEmptyRecipeTextFragments(),
    negativePrompt: '',
    personBText: '',
    personBVariants: [],
    // 默认没有模式记录：旧数据同样走「有图 / 有文本」推导。
    portraitMode: null,
    costumeMode: null,
    poseMode: null,
    // P4：跨源补充默认关闭，必须在 image 模式下显式打开。
    portraitSupplement: false,
    costumeSupplement: false,
    poseSupplement: false,
    recipeSourceId: null,
    recipeSourceName: '',
  }
}

/**
 * 读取合成台设置。
 *
 * 返回 `null` 表示「没有可用记录」：调用方据此保留页面原有的默认行为
 * （工作流由后端 default 决定、尺寸由 caps reconcile 决定）。
 */
export function readReferenceStudioSettings(): ReferenceStudioSettings | null {
  try {
    const raw = getStorage()?.getItem(REFERENCE_STUDIO_STORAGE_KEY)
    if (!raw) return null
    return parseReferenceStudioSettings(JSON.parse(raw) as unknown)
  } catch {
    // JSON 非法 / 隐私模式 / 配额异常：一律回落默认。
    return null
  }
}

/** 待写补丁与防抖定时器（模块级单例：三槽与合成台参数共用一份合并缓冲）。 */
let pendingPatch: Partial<ReferenceStudioSettings> | null = null
let writeTimer: ReturnType<typeof setTimeout> | null = null

/**
 * 立即落盘待写补丁。
 *
 * 以「磁盘上现有值（或默认值） + 本次补丁」合并后整体写入，保证三槽与
 * 合成台参数互不覆盖。写前再校验一次，永不把脏数据写进 localStorage。
 * 值未变化时不写盘（连点 toggle 不会产生无意义的写）。
 */
export function flushReferenceStudioSettings(): void {
  if (writeTimer !== null) {
    clearTimeout(writeTimer)
    writeTimer = null
  }
  const patch = pendingPatch
  pendingPatch = null
  if (!patch) return

  try {
    const base = readReferenceStudioSettings() ?? createDefaultReferenceStudioSettings()
    const validated = parseReferenceStudioSettings({ ...base, ...patch })
    if (!validated) return

    const storage = getStorage()
    if (!storage) return

    const serialized = JSON.stringify(validated)
    if (storage.getItem(REFERENCE_STUDIO_STORAGE_KEY) === serialized) return
    storage.setItem(REFERENCE_STUDIO_STORAGE_KEY, serialized)
  } catch {
    /* 隐私模式 / 配额不足：静默降级，本次会话仍按内存值工作 */
  }
}

/**
 * 合并写入合成台设置（300ms 防抖）。
 *
 * 只传需要变更的字段；多次调用会在缓冲里合并，最终只写一次盘。
 */
export function writeReferenceStudioSettings(
  patch: Partial<ReferenceStudioSettings>,
): void {
  pendingPatch = { ...(pendingPatch ?? {}), ...patch }
  if (writeTimer !== null) clearTimeout(writeTimer)
  writeTimer = setTimeout(() => {
    writeTimer = null
    flushReferenceStudioSettings()
  }, REFERENCE_STUDIO_WRITE_DEBOUNCE_MS)
}

/** 读取最后访问的页签原文；缺失 / 非字符串 / 空串返回 null。 */
export function readLastReferenceTab(): string | null {
  try {
    const raw = getStorage()?.getItem(REFERENCE_TAB_STORAGE_KEY)
    return typeof raw === 'string' && raw.length > 0 ? raw : null
  } catch {
    return null
  }
}

/** 写入最后访问的页签；失败静默。 */
export function writeLastReferenceTab(tab: string): void {
  try {
    getStorage()?.setItem(REFERENCE_TAB_STORAGE_KEY, tab)
  } catch {
    /* 隐私模式 / 配额不足：忽略 */
  }
}