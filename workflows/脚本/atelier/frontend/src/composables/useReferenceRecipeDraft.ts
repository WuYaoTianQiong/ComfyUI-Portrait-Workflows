/**
 * 参考图库「角色配方」三槽位选择状态（阶段 2.1 / 合成台共用）。
 *
 * 口径（阶段 3 多选升级）：
 * - 每个槽位是**数组**，允许同一槽位加入多张参考图；空槽也允许提交，
 *   批量时由前端按组合逐组提交（后端每个请求仍是单值槽位）。
 * - **2026-11-05 用户要求记忆操作，取代 M3 不持久化**：阶段 3 曾因「草稿都是
 *   测试数据」决定不做 localStorage / IndexedDB，该决策已被用户本次需求推翻。
 *   三槽只持久化 `id + library + name + thumbnail (+ useDepth)`，与合成台其他
 *   参数共用 `pb.reference_studio_v1`（见 `useReferenceStudioSettings`）。
 * - 恢复必须**按 id + library 匹配库数据**，且只在库加载完成后 hydrate；
 *   匹配不到的条目直接丢弃（可能已被删除），绝不凭空造卡片。
 * - 模块级单例：姿势库、服装库、人像库、合成台、顶部配方槽共用同一份状态，
 *   避免每个页面各存一份导致「库里提示已选、合成台却是空的」。
 *
 * 计数口径：
 * - `count` / `countLabel` 仍表示**非空槽位数**（n/3），供首页与骨架期契约
 *   `reference-home-recipe-count` 继续使用；
 * - `totalSelected` 表示三槽选中的条目总数（多选后的真实数量）；
 * - `portraitCount` / `costumeCount` / `poseCount` 为各槽条目数。
 *
 * 姿势槽额外记录 `useDepth`（白模 / 深度图）。同一个姿势 id 在两种模式下
 * 分别有意义：同 id 同模式再点 = 移除，同 id 换模式 = 更新该条目的模式，
 * 避免「白模已选 → 切深度图再点」被误判为取消。
 */

import { computed, ref, watch } from 'vue'

import type { CostumeItem, PoseItem, PortraitItem } from '../api/reference'
import {
  MAX_PERSON_B_VARIANTS,
  RECIPE_SLOT_KEYS,
  clonePersonBVariants,
  cloneRecipeTextFragments,
  cloneSupplementFlags,
  createEmptyPersonBVariant,
  createEmptyRecipeTextFragments,
  createEmptySlotModes,
  createEmptySupplementFlags,
  deriveSlotModes,
} from './recipeTextFragments'
import type {
  RecipePersonBImage,
  RecipePersonBVariant,
  RecipeSlotKey,
  RecipeSlotMode,
  RecipeSlotModes,
  RecipeSupplementFlags,
  RecipeTextFragments,
} from './recipeTextFragments'
import {
  createEmptyCostumeSlot,
  createEmptyExtraSlot,
  readReferenceStudioSettings,
  writeReferenceStudioSettings,
} from './useReferenceStudioSettings'
import type { ReferenceStudioSettings } from './useReferenceStudioSettings'
import type {
  StoredReferenceCostumeSlot,
  StoredReferenceExtraSlot,
  StoredReferenceSlotEntry,
} from './useReferenceStudioSettings'

/** 姿势槽位的值：条目 + 加入时的图片模式。 */
export interface PoseSlotSelection {
  item: PoseItem
  /** true = 深度图，false = 素体白模 */
  useDepth: boolean
}

/** 槽位键（真源在 `recipeTextFragments`，这里重导出保持旧导入路径可用）。 */
export type { RecipeSlotKey }
export type { RecipeSlotMode, RecipeSlotModes }

/** 槽位总数（固定三槽）。 */
export const RECIPE_SLOT_TOTAL = 3

/** 本地上传图的 id 前缀：用绝对路径保证唯一，便于去重与移除。 */
export const UPLOAD_ID_PREFIX = 'upload:'

/** 上传参数（来自 `POST /api/reference/uploads`）。 */
export interface UploadSlotInput {
  path: string
  name: string
  width?: number
  height?: number
}

/** 从槽位条目里取本地上传图路径；库条目返回 null。 */
export function uploadPathOf(entry: unknown): string | null {
  if (!entry || typeof entry !== 'object') return null
  const value = (entry as { uploadPath?: unknown }).uploadPath
  return typeof value === 'string' && value.length > 0 ? value : null
}

/** 上传图 → 浏览器可访问地址（后端把 `data_dir/uploads` 挂到 `/uploads`）。 */
export function uploadUrlOf(path: string): string {
  const name = path.split(/[\\/]/).filter(Boolean).pop() ?? ''
  return name ? `/uploads/${encodeURIComponent(name)}` : ''
}

/** 带 `uploadPath` 的槽位条目（上传图伪装成库条目，参与既有组合逻辑）。 */
export type UploadableSlotItem<T> = T & { uploadPath?: string }

const portrait = ref<PortraitItem[]>([])
const costume = ref<CostumeItem[]>([])
const pose = ref<PoseSlotSelection[]>([])

/**
 * 第 4 槽（2026-11-07）：发型库背面图 / 上传单图 + 文字补充。
 *
 * 与前三槽的差异：
 * - 只保留 1 张，**不进入批量笛卡尔积**（一批共用同一张）；
 * - 不支持纯文字（没有图时文字不生效，后端也会 400）；
 * - 与三槽一样进 `pb.reference_studio_v1`，跨页签 / 刷新保留。
 */
const extra = ref<StoredReferenceExtraSlot>(createEmptyExtraSlot())

/** 第 4 槽是否已选图（`source=empty` 即未选）。 */
const extraFilled = computed(() => extra.value.source !== 'empty')

/**
 * V2-C 第 5 槽（人物B服装）：整批共享 1 张，不进入批量组合维度。
 *
 * 只在工作流声明 `extra_costume` 时渲染入口；与第 4 槽一样随
 * `pb.reference_studio_v1` 持久化。
 */
const extraCostume = ref<StoredReferenceCostumeSlot>(createEmptyCostumeSlot())
/** 人物B服装槽是否已选图。 */
const extraCostumeFilled = computed(() => extraCostume.value.source !== 'empty')

/**
 * 文本补充八类碎片（2026-11-06）。
 *
 * 与三槽不同，它不需要按 id 回查库数据：持久化里存的就是 `{type, content}` 全文，
 * 因此可以在库加载完成前先读回（见 `hydrateTextFragments`），刷新不丢文本。
 */
const textFragments = ref<RecipeTextFragments>(createEmptyRecipeTextFragments())
/** 用户手填的负向提示词；最终负向 = 后端自动抽取 + 这里的内容。 */
const negativePrompt = ref('')
/**
 * 双人姿势的人物 B 文字变体（v1.5）。
 *
 * 每条变体 = B 专属的三类人物碎片 + 自由文字；批量时与 A 人像按序号 1:1 配对。
 * `personBText` 仍保留为「当前变体的自由文字」兼容读写，旧调用方无需改动。
 */
const personBVariants = ref<RecipePersonBVariant[]>([])
/** 当前编辑 / 预览使用的变体下标；越界时回落到 0。 */
const activePersonBVariantIndex = ref(0)
/** 变体 id 计数器：仅本会话内唯一，避免用时间戳导致持久化不稳定。 */
let personBVariantSeq = 0

/** 当前激活变体；空列表时为 null。 */
const activePersonBVariant = computed<RecipePersonBVariant | null>(() => {
  const list = personBVariants.value
  if (!list.length) return null
  const index = Math.min(Math.max(activePersonBVariantIndex.value, 0), list.length - 1)
  return list[index] ?? null
})

/** 双人姿势的人物 B 自由文字；读写当前激活变体（旧 API 兼容）。 */
const personBText = computed<string>({
  get: () => activePersonBVariant.value?.freeText ?? '',
  set: (value: string) => {
    const variant = activePersonBVariant.value
    if (!variant) return
    const index = Math.min(
      Math.max(activePersonBVariantIndex.value, 0),
      personBVariants.value.length - 1,
    )
    personBVariants.value = personBVariants.value.map((item, position) =>
      position === index ? { ...item, freeText: value } : item,
    )
  },
})

/** 新建一个带唯一 id 的空变体。 */
function newPersonBVariant(): RecipePersonBVariant {
  personBVariantSeq += 1
  return createEmptyPersonBVariant(`b-${personBVariantSeq}`)
}

/** 确保至少有一条变体（双人姿势首次进入 / 旧数据迁移时使用）。 */
function ensurePersonBVariant(): RecipePersonBVariant {
  const current = activePersonBVariant.value
  if (current) return current
  const variant = newPersonBVariant()
  personBVariants.value = [variant]
  activePersonBVariantIndex.value = 0
  return variant
}

/** 新增变体并切到新变体；达到上限（或双人配对模式只允许 1 组）时返回 false。 */
function addPersonBVariant(): boolean {
  if (pairModeActive.value) return false
  if (personBVariants.value.length >= MAX_PERSON_B_VARIANTS) return false
  personBVariants.value = [...personBVariants.value, newPersonBVariant()]
  activePersonBVariantIndex.value = personBVariants.value.length - 1
  return true
}

/** 删除指定变体（缺省删当前）；删空后自动补一条空变体，保证双人卡片可编辑。 */
function removePersonBVariant(index?: number): void {
  const target = index ?? activePersonBVariantIndex.value
  if (target < 0 || target >= personBVariants.value.length) return
  personBVariants.value = personBVariants.value.filter((_, position) => position !== target)
  if (!personBVariants.value.length) {
    personBVariants.value = [newPersonBVariant()]
  }
  activePersonBVariantIndex.value = Math.min(
    target,
    Math.max(0, personBVariants.value.length - 1),
  )
}

/** 切换当前编辑的变体。 */
function setActivePersonBVariant(index: number): void {
  if (index < 0 || index >= personBVariants.value.length) return
  activePersonBVariantIndex.value = index
}

/**
 * 三槽模式（P2 替代态，方案 §4.4）。
 *
 * - `image`：提交该槽参考图（碎片存在时作为补充）；
 * - `text`：不提交图，只提交该槽对应类碎片；
 * - `empty`：不提交任何内容。
 *
 * 真源在这里（与 `pb.reference_studio_v1` 的 portraitMode / costumeMode / poseMode 对应）。
 */
const slotModes = ref<RecipeSlotModes>(createEmptySlotModes())

/**
 * 跨源补充开关（P4）：`image` 模式下是否把对应槽文本追加为「此外需体现」。
 *
 * 默认全关；只在 image 模式有意义。切换到 text / empty 时由 `setSlotMode` 归零，
 * 避免「切回图片后静默继续补充」。
 */
const supplementFlags = ref<RecipeSupplementFlags>(createEmptySupplementFlags())

/** 最近一次「同源整套随机」的来源；仅展示 / 防止连续重复，不参与提交。 */
const recipeSourceId = ref<number | null>(null)
const recipeSourceName = ref('')

/**
 * 最近一次非空姿势的 id。
 *
 * 姿势槽切文本替代后 items 可能被清空，此时仍要能判断「上次选的是不是双人姿势」，
 * 因此单独记住最近一次有效选择（`pair*` 前缀 = 双人）。
 */
const lastPoseId = ref('')

/**
 * 文本补充是否已从磁盘恢复过。
 *
 * 同一会话只恢复一次：合成台每次进入都会 setup，若每次都从 localStorage 读回，
 * 会把「刚改、还在 300ms 写盘防抖窗口里」的编辑覆盖成旧值。
 * `clearDraft()` 会重置它（测试与显式清空草稿都依赖这个语义）。
 */
let textFragmentsRestoredFromStorage = false
/** 模式表是否已按快照恢复过（避免重复 hydrate 覆盖会话内的手动切换）。 */

/** 各槽条目数。 */
const portraitCount = computed(() => portrait.value.length)
const costumeCount = computed(() => costume.value.length)
const poseCount = computed(() => pose.value.length)

/** 三槽选中的条目总数（多选后的真实数量）。 */
const totalSelected = computed(
  () => portraitCount.value + costumeCount.value + poseCount.value,
)

/** 当前姿势里是否有双人构图（上游 pair* 或 pose-studio-lite composition=pair）。 */
const hasPairPose = computed(() =>
  pose.value.some(
    (entry) =>
      entry.item.composition === 'pair' || entry.item.id.startsWith('pair'),
  ),
)

/** 双人姿势首次出现（含从磁盘恢复）时自动补一条空变体，保证 B 卡片可编辑。 */
watch(
  hasPairPose,
  (pair) => {
    if (pair && !personBVariants.value.length) ensurePersonBVariant()
  },
  { immediate: true },
)

/**
 * 双人配对模式（V2-C，2026-11-08）：任一已选姿势 `composition=pair` 时默认生效。
 *
 * 生效时三槽各最多 1 张、B 变体 1 组、不做跨槽笛卡尔积；「批量展开」显式打开后
 * 恢复原来的多选语义。纯前端约束，后端仍是单值提交。
 */
const pairBatchExpanded = ref(false)
/** 双人配对模式是否生效（双人姿势 + 未打开批量展开）。 */
const pairModeActive = computed(
  () => hasPairPose.value && !pairBatchExpanded.value,
)
/** 进入配对模式时自动收敛的提示；页面转 toast 后清空。 */
const pairLimitNotice = ref('')

/** 配对模式下每槽只留首张、B 变体只留首组；返回是否发生收敛。 */
function limitPairSelections(): boolean {
  let changed = false
  if (portrait.value.length > 1) {
    portrait.value = portrait.value.slice(0, 1)
    changed = true
  }
  if (costume.value.length > 1) {
    costume.value = costume.value.slice(0, 1)
    changed = true
  }
  if (pose.value.length > 1) {
    // 先选单图姿势再选双人姿势时，不能按顺序留下首张（否则双人姿势被丢、
    // B 编辑器随之消失）；优先保留双人构图，其余槽仍留首张。
    const pairEntry = pose.value.find(
      (entry) =>
        entry.item.composition === 'pair' || entry.item.id.startsWith('pair'),
    )
    pose.value = pairEntry ? [pairEntry] : pose.value.slice(0, 1)
    changed = true
  }
  if (personBVariants.value.length > 1) {
    personBVariants.value = personBVariants.value.slice(0, 1)
    activePersonBVariantIndex.value = 0
    changed = true
  }
  return changed
}

/** 进入配对模式（含从磁盘恢复出多选）时自动收敛到首张，只提示一次。 */
watch(pairModeActive, (active) => {
  if (!active) return
  if (limitPairSelections()) {
    pairLimitNotice.value = '已进入双人配对模式，每个图片槽只保留 1 张'
  }
})

/** 切换「批量展开」；关闭时立即收敛，避免同一 tick 内开关不触发 watcher。 */
function setPairBatchExpanded(expanded: boolean): void {
  if (pairBatchExpanded.value === expanded) return
  pairBatchExpanded.value = expanded
  if (!expanded && limitPairSelections()) {
    pairLimitNotice.value = '已进入双人配对模式，每个图片槽只保留 1 张'
  }
  writeReferenceStudioSettings({ pairBatchExpanded: expanded })
}

/** 非空槽位数量（0–3）；数组里有内容即视为该槽已选。 */
const count = computed(
  () =>
    (portraitCount.value > 0 ? 1 : 0) +
    (costumeCount.value > 0 ? 1 : 0) +
    (poseCount.value > 0 ? 1 : 0),
)

/** 顶部 / 侧栏展示用的 `n/3`。 */
const countLabel = computed(() => `${count.value}/${RECIPE_SLOT_TOTAL}`)

/** 三槽是否都已选（至少各一张）。 */
const isComplete = computed(() => count.value === RECIPE_SLOT_TOTAL)

// ---------------------------------------------------------------------------
// 人像槽
// ---------------------------------------------------------------------------

/** 人像槽：追加一张；同 id 已存在时不重复加入。配对模式下替换为单张。 */
function addPortrait(item: PortraitItem): void {
  if (pairModeActive.value) {
    if (portrait.value.length === 1 && portrait.value[0].id === item.id) return
    portrait.value = [item]
    return
  }
  if (portrait.value.some((entry) => entry.id === item.id)) return
  portrait.value = [...portrait.value, item]
}

/** 人像槽：整体替换为单张（随机捏人 / 旧调用方语义）；传 null 清空。 */
function setPortrait(item: PortraitItem | null): void {
  portrait.value = item ? [item] : []
}

/** 人像槽：点已选取消，否则追加。返回 true 表示本次是「加入」。配对模式下单选。 */
function togglePortrait(item: PortraitItem): boolean {
  const already = portrait.value.some((entry) => entry.id === item.id)
  if (pairModeActive.value) {
    portrait.value = already ? [] : [item]
    return !already
  }
  portrait.value = already
    ? portrait.value.filter((entry) => entry.id !== item.id)
    : [...portrait.value, item]
  return !already
}

/** 人像槽：传 id 移除单条，不传 id 清空整个槽位。 */
function removePortrait(id?: string): void {
  if (!id) {
    portrait.value = []
    return
  }
  portrait.value = portrait.value.filter((entry) => entry.id !== id)
}

// ---------------------------------------------------------------------------
// 服装槽
// ---------------------------------------------------------------------------

/** 服装槽：追加一张；同 id 已存在时不重复加入。配对模式下替换为单张。 */
function addCostume(item: CostumeItem): void {
  if (pairModeActive.value) {
    if (costume.value.length === 1 && costume.value[0].id === item.id) return
    costume.value = [item]
    return
  }
  if (costume.value.some((entry) => entry.id === item.id)) return
  costume.value = [...costume.value, item]
}

/** 服装槽：整体替换为单张；传 null 清空。 */
function setCostume(item: CostumeItem | null): void {
  costume.value = item ? [item] : []
}

/** 服装槽：点已选取消，否则追加。配对模式下单选。 */
function toggleCostume(item: CostumeItem): boolean {
  const already = costume.value.some((entry) => entry.id === item.id)
  if (pairModeActive.value) {
    costume.value = already ? [] : [item]
    return !already
  }
  costume.value = already
    ? costume.value.filter((entry) => entry.id !== item.id)
    : [...costume.value, item]
  return !already
}

/** 服装槽：传 id 移除单条，不传 id 清空整个槽位。 */
function removeCostume(id?: string): void {
  if (!id) {
    costume.value = []
    return
  }
  costume.value = costume.value.filter((entry) => entry.id !== id)
}

// ---------------------------------------------------------------------------
// 姿势槽
// ---------------------------------------------------------------------------

/** 该姿势条目是否有深度变体；多来源里 PSL 没有深度图。 */
function poseSupportsDepth(item: PoseItem): boolean {
  return item.hasDepth !== false
}

/** 无深度条目强制回白模，避免槽位/灯箱去请求不存在的 depth 端点。 */
function normalizePoseDepth(item: PoseItem, useDepth: boolean): boolean {
  return Boolean(useDepth && poseSupportsDepth(item))
}

/** 姿势槽：追加；同 id 已存在时更新其模式（后写覆盖）。配对模式下替换为单张。 */
function addPose(item: PoseItem, useDepth = false): void {
  const normalized = normalizePoseDepth(item, useDepth)
  if (pairModeActive.value) {
    pose.value = [{ item, useDepth: normalized }]
    return
  }
  const index = pose.value.findIndex((entry) => entry.item.id === item.id)
  if (index < 0) {
    pose.value = [...pose.value, { item, useDepth: normalized }]
    return
  }
  const next = [...pose.value]
  next[index] = { item, useDepth: normalized }
  pose.value = next
}

/** 姿势槽：整体替换为单条（随机捏人 / 旧调用方语义）；传 null 清空。 */
function setPose(item: PoseItem | null, useDepth = false): void {
  pose.value = item
    ? [{ item, useDepth: normalizePoseDepth(item, useDepth) }]
    : []
}

/**
 * 姿势槽：加入 / 移除 / 换模式。
 *
 * 只有「同 id 且同模式」才算已选，点击才移除；同 id 换模式视为更新条目。
 * 返回 true 表示操作后该条目仍在槽位中（加入或换模式），false 表示移除。
 */
function togglePose(item: PoseItem, useDepth = false): boolean {
  const normalized = normalizePoseDepth(item, useDepth)
  if (pairModeActive.value) {
    const current = pose.value[0]
    if (current && current.item.id === item.id && current.useDepth === normalized) {
      pose.value = []
      return false
    }
    pose.value = [{ item, useDepth: normalized }]
    return true
  }
  const index = pose.value.findIndex((entry) => entry.item.id === item.id)
  if (index < 0) {
    pose.value = [...pose.value, { item, useDepth: normalized }]
    return true
  }
  if (pose.value[index].useDepth === normalized) {
    pose.value = pose.value.filter((_, i) => i !== index)
    return false
  }
  const next = [...pose.value]
  next[index] = { item, useDepth: normalized }
  pose.value = next
  return true
}

/** 姿势槽：传 id 移除单条，不传 id 清空整个槽位。 */
function removePose(id?: string): void {
  if (!id) {
    pose.value = []
    return
  }
  pose.value = pose.value.filter((entry) => entry.item.id !== id)
}

/** 把槽位内所有姿势统一改成白模 / 深度图（无深度条目保持白模）。 */
function setPoseMode(useDepth: boolean): void {
  pose.value = pose.value.map((entry) => ({
    ...entry,
    useDepth: normalizePoseDepth(entry.item, useDepth),
  }))
}

// ---------------------------------------------------------------------------
// 槽位模式（P2 替代态）
// ---------------------------------------------------------------------------

/**
 * 设置某一槽的模式（页面统一校验双人 / 素体冲突后再调用）。
 *
 * 只改模式，不动碎片与图片：`image` → `text` 保留图片作为「改回图片」的退路，
 * `text` → `image` 保留碎片作为补充。
 */
function setSlotMode(slot: RecipeSlotKey, mode: RecipeSlotMode): void {
  if (slotModes.value[slot] === mode) return
  slotModes.value = { ...slotModes.value, [slot]: mode }
  // 补充只在 image 模式有意义：离开 image 时归零，切回时不静默复活。
  if (mode !== 'image' && supplementFlags.value[slot]) {
    supplementFlags.value = { ...supplementFlags.value, [slot]: false }
  }
}

/**
 * 设置某一槽的跨源补充开关（P4）。
 *
 * 只允许在 image 模式打开；text / empty 下即使调用也按 false 处理。
 */
function setSlotSupplement(slot: RecipeSlotKey, enabled: boolean): void {
  const next = enabled && slotModes.value[slot] === 'image'
  if (supplementFlags.value[slot] === next) return
  supplementFlags.value = { ...supplementFlags.value, [slot]: next }
}

/** 记录 / 清空「同源整套随机」来源（仅展示与避免连续重复）。 */
function setRecipeSource(id: number | null, name = ''): void {
  recipeSourceId.value = id
  recipeSourceName.value = name
}

// ---------------------------------------------------------------------------
// 本地上传图（三槽都支持；与库条目同一个数组，一起参与笛卡尔积）
// ---------------------------------------------------------------------------

/** 上传图 → 人像槽条目（只填展示与提交需要的字段）。 */
function portraitUploadItem(input: UploadSlotInput): UploadableSlotItem<PortraitItem> {
  const url = uploadUrlOf(input.path)
  return {
    id: `${UPLOAD_ID_PREFIX}${input.path}`,
    分区: '本地上传',
    发长: '',
    发型名称: input.name,
    标题: input.name,
    宽: input.width ?? 0,
    高: input.height ?? 0,
    字节数: 0,
    精选: false,
    热门: false,
    缩略图: url,
    原图: url,
    检索: '',
    uploadPath: input.path,
  }
}

/** 上传图 → 服装槽条目；`library` 固定现实库（上传图不属于外链库）。 */
function costumeUploadItem(input: UploadSlotInput): UploadableSlotItem<CostumeItem> {
  const url = uploadUrlOf(input.path)
  return {
    id: `${UPLOAD_ID_PREFIX}${input.path}`,
    分类: '本地上传',
    服装名称: input.name,
    标签: [],
    关键词: '',
    缩略图: url,
    预览图: url,
    原图: url,
    检索: '',
    library: 'costume',
    uploadPath: input.path,
  }
}

/** 上传图 → 姿势槽条目（上传图没有深度图变体，`useDepth` 恒为 false）。 */
function poseUploadSelection(input: UploadSlotInput): PoseSlotSelection {
  const url = uploadUrlOf(input.path)
  const item: UploadableSlotItem<PoseItem> = {
    id: `${UPLOAD_ID_PREFIX}${input.path}`,
    体系: '本地上传',
    姿势编号: input.name,
    分类: '本地上传',
    姿势名称: input.name,
    角度: '',
    缩略图: url,
    原图: url,
    检索: '',
    nsfw: false,
    uploadPath: input.path,
  }
  return { item, useDepth: false }
}

/** 人像槽：加入一张本地图；同路径不重复。配对模式下替换为单张。 */
function addPortraitUpload(input: UploadSlotInput): void {
  const id = `${UPLOAD_ID_PREFIX}${input.path}`
  if (pairModeActive.value) {
    if (portrait.value.length === 1 && portrait.value[0].id === id) return
    portrait.value = [portraitUploadItem(input)]
    return
  }
  if (portrait.value.some((entry) => entry.id === id)) return
  portrait.value = [...portrait.value, portraitUploadItem(input)]
}

/** 服装槽：加入一张本地图；同路径不重复。配对模式下替换为单张。 */
function addCostumeUpload(input: UploadSlotInput): void {
  const id = `${UPLOAD_ID_PREFIX}${input.path}`
  if (pairModeActive.value) {
    if (costume.value.length === 1 && costume.value[0].id === id) return
    costume.value = [costumeUploadItem(input)]
    return
  }
  if (costume.value.some((entry) => entry.id === id)) return
  costume.value = [...costume.value, costumeUploadItem(input)]
}

/** 姿势槽：加入一张本地图；同路径不重复。配对模式下替换为单张。 */
function addPoseUpload(input: UploadSlotInput): void {
  const id = `${UPLOAD_ID_PREFIX}${input.path}`
  if (pairModeActive.value) {
    if (pose.value.length === 1 && pose.value[0].item.id === id) return
    pose.value = [poseUploadSelection(input)]
    return
  }
  if (pose.value.some((entry) => entry.item.id === id)) return
  pose.value = [...pose.value, poseUploadSelection(input)]
}

// ---------------------------------------------------------------------------
// 第 4 槽（extra，单图 + 可选文字补充）
// ---------------------------------------------------------------------------

/** 第 4 槽：加入一张上传图（后传覆盖前传，与「只提交 1 张」一致）。 */
function setExtraUpload(path: string, name: string): void {
  extra.value = {
    source: 'upload',
    library: '',
    id: '',
    path,
    name,
    text: extra.value.text,
  }
}

/** 第 4 槽：改为库条目（发型背面图 / v2-A 人物B人像参考）。 */
function setExtraLibrary(library: 'hair' | 'portrait', id: string, name: string): void {
  extra.value = {
    source: 'library',
    library,
    id,
    path: '',
    name,
    text: extra.value.text,
  }
}

/** 第 4 槽文字补充；只在有图时随提交发送。 */
function setExtraText(text: string): void {
  if (extra.value.text === text) return
  extra.value = { ...extra.value, text }
}

/** 清空第 4 槽（图片与文字一起清，避免残留文字被当成纯文字槽）。 */
function clearExtra(): void {
  extra.value = createEmptyExtraSlot()
}

// ---------------------------------------------------------------------------
// 第 5 槽（V2-C · 人物B服装，单图、整批共享）
// ---------------------------------------------------------------------------

/** 人物B服装：改为上传图（后传覆盖前传）。 */
function setExtraCostumeUpload(path: string, name: string): void {
  extraCostume.value = {
    source: 'upload',
    library: '',
    id: '',
    path,
    name,
  }
}

/** 人物B服装：改为服装库条目。 */
function setExtraCostumeLibrary(
  library: 'costume' | 'costume-anime',
  id: string,
  name: string,
): void {
  extraCostume.value = {
    source: 'library',
    library,
    id,
    path: '',
    name,
  }
}

/** 清空人物B服装槽。 */
function clearExtraCostume(): void {
  extraCostume.value = createEmptyCostumeSlot()
}

// ---------------------------------------------------------------------------
// 人物B变体绑图（2026-11-08）
// ---------------------------------------------------------------------------

/** 当前激活变体下标（越界回落到最后一个合法项）。 */
function activeVariantPosition(): number {
  const last = personBVariants.value.length - 1
  return Math.min(Math.max(activePersonBVariantIndex.value, 0), last)
}

/** 只替换激活变体的一张图，其余变体保持不变。 */
function updateActiveVariantImage(
  kind: 'identity' | 'costume',
  image: RecipePersonBImage,
): void {
  const position = activeVariantPosition()
  if (position < 0) return
  personBVariants.value = personBVariants.value.map((item, index) =>
    index === position ? { ...item, [kind]: image } : item,
  )
}

/** 变体的 B 身份图（人像库单图）；同时同步页面全局第 4 槽。 */
function setPersonBIdentityLibrary(id: string, name: string): void {
  ensurePersonBVariant()
  updateActiveVariantImage('identity', {
    source: 'library',
    library: 'portrait',
    id,
    path: '',
    name,
  })
  setExtraLibrary('portrait', id, name)
}

/** 变体的 B 身份图（本地上传）；同时同步页面全局第 4 槽。 */
function setPersonBIdentityUpload(path: string, name: string): void {
  ensurePersonBVariant()
  updateActiveVariantImage('identity', {
    source: 'upload',
    library: '',
    id: '',
    path,
    name,
  })
  setExtraUpload(path, name)
}

/** 清空变体的 B 身份图与页面全局第 4 槽。 */
function clearPersonBIdentity(): void {
  updateActiveVariantImage('identity', {
    source: 'empty',
    library: '',
    id: '',
    path: '',
    name: '',
  })
  clearExtra()
}

/** 变体的 B 服装图（库条目）；同时同步页面全局第 5 槽。 */
function setPersonBCostumeLibrary(
  library: 'costume' | 'costume-anime',
  id: string,
  name: string,
): void {
  ensurePersonBVariant()
  updateActiveVariantImage('costume', {
    source: 'library',
    library,
    id,
    path: '',
    name,
  })
  setExtraCostumeLibrary(library, id, name)
}

/** 变体的 B 服装图（本地上传）；同时同步页面全局第 5 槽。 */
function setPersonBCostumeUpload(path: string, name: string): void {
  ensurePersonBVariant()
  updateActiveVariantImage('costume', {
    source: 'upload',
    library: '',
    id: '',
    path,
    name,
  })
  setExtraCostumeUpload(path, name)
}

/** 清空变体的 B 服装图与页面全局第 5 槽。 */
function clearPersonBCostume(): void {
  updateActiveVariantImage('costume', {
    source: 'empty',
    library: '',
    id: '',
    path: '',
    name: '',
  })
  clearExtraCostume()
}

/**
 * 把激活变体绑定的两张图投影回全局第 4/5 槽。
 *
 * 页面只在「人物B工作流」下调用；切变体后第 4 槽展示、预览与槽位计数都跟着走。
 */
function syncPersonBImagesFromVariant(): void {
  const variant = activePersonBVariant.value
  if (!variant) return

  const identity = variant.identity
  if (identity.source === 'library' && (identity.library === 'portrait' || identity.library === 'hair')) {
    if (
      extra.value.source !== 'library' ||
      extra.value.library !== identity.library ||
      extra.value.id !== identity.id
    ) {
      setExtraLibrary(identity.library, identity.id, identity.name)
    }
  } else if (identity.source === 'upload' && identity.path) {
    if (extra.value.source !== 'upload' || extra.value.path !== identity.path) {
      setExtraUpload(identity.path, identity.name)
    }
  } else if (extra.value.source !== 'empty') {
    clearExtra()
  }

  const costume = variant.costume
  if (
    costume.source === 'library' &&
    (costume.library === 'costume' || costume.library === 'costume-anime')
  ) {
    if (
      extraCostume.value.source !== 'library' ||
      extraCostume.value.library !== costume.library ||
      extraCostume.value.id !== costume.id
    ) {
      setExtraCostumeLibrary(costume.library, costume.id, costume.name)
    }
  } else if (costume.source === 'upload' && costume.path) {
    if (extraCostume.value.source !== 'upload' || extraCostume.value.path !== costume.path) {
      setExtraCostumeUpload(costume.path, costume.name)
    }
  } else if (extraCostume.value.source !== 'empty') {
    clearExtraCostume()
  }
}

// ---------------------------------------------------------------------------
// 通用
// ---------------------------------------------------------------------------

/** 清空三槽（切换配方 / 新建时用）。 */
function clearDraft(): void {
  portrait.value = []
  costume.value = []
  pose.value = []
  extra.value = createEmptyExtraSlot()
  extraCostume.value = createEmptyCostumeSlot()
  // 文本补充与负向同属草稿；清空后允许下次重新从磁盘恢复（测试与显式清空共用）。
  textFragments.value = createEmptyRecipeTextFragments()
  negativePrompt.value = ''
  personBVariants.value = []
  activePersonBVariantIndex.value = 0
  pairBatchExpanded.value = false
  // 模式与「上次姿势」同属草稿：清空后回到「三槽都是空」的推导起点。
  slotModes.value = createEmptySlotModes()
  supplementFlags.value = createEmptySupplementFlags()
  recipeSourceId.value = null
  recipeSourceName.value = ''
  lastPoseId.value = ''
  textFragmentsRestoredFromStorage = false
}

// ---------------------------------------------------------------------------
// 持久化（2026-11-05 用户要求记忆操作，取代 M3 不持久化）
// ---------------------------------------------------------------------------

/** hydrate 需要的三库全量数据；必须等三个库都加载成功后才能调用。 */
export interface ReferenceDraftLibraries {
  portrait: readonly PortraitItem[]
  costume: readonly CostumeItem[]
  pose: readonly PoseItem[]
}

/** 人像条目 → 最小持久化记录；本地上传图额外记 `path`，恢复时不查库。 */
function storedPortrait(item: PortraitItem): StoredReferenceSlotEntry {
  const entry: StoredReferenceSlotEntry = {
    id: item.id,
    library: item.library ?? 'portrait',
    name: item.发型名称 || item.标题,
    thumbnail: item.缩略图,
  }
  const uploaded = uploadPathOf(item)
  if (uploaded) entry.path = uploaded
  return entry
}

/** 服装条目 → 最小持久化记录；现实库与外链库靠 `library` 区分。 */
function storedCostume(item: CostumeItem): StoredReferenceSlotEntry {
  const entry: StoredReferenceSlotEntry = {
    id: item.id,
    library: item.library ?? 'costume',
    name: item.服装名称,
    thumbnail: item.缩略图,
  }
  const uploaded = uploadPathOf(item)
  if (uploaded) entry.path = uploaded
  return entry
}

/** 姿势槽记录 → 最小持久化记录（带上白模 / 深度图模式）。 */
function storedPose(entry: PoseSlotSelection): StoredReferenceSlotEntry {
  const stored: StoredReferenceSlotEntry = {
    id: entry.item.id,
    library: entry.item.library ?? 'pose',
    name: entry.item.姿势名称,
    thumbnail: entry.item.缩略图,
    useDepth: entry.useDepth,
  }
  const uploaded = uploadPathOf(entry.item)
  if (uploaded) stored.path = uploaded
  return stored
}

/**
 * 把当前三槽写入 `pb.reference_studio_v1`（300ms 防抖，与合成台参数合并）。
 *
 * 只存恢复所需的最小字段；完整条目在 hydrate 时从库数据按 id 回查，
 * 避免把整份库快照写进 localStorage。
 */
function persist(): void {
  writeReferenceStudioSettings({
    portrait: portrait.value.map(storedPortrait),
    costume: costume.value.map(storedCostume),
    pose: pose.value.map(storedPose),
    // 第 4 槽存最小来源信息 + 全文；恢复不依赖发型库是否已加载。
    extra: { ...extra.value },
    // V2-C 第 5 槽（人物B服装）同样只存来源。
    extraCostume: { ...extraCostume.value },
    // 文本补充存全文（不是只存 id）：恢复时不依赖库数据，也不会因为碎片池改名而丢内容。
    textFragments: cloneRecipeTextFragments(textFragments.value),
    negativePrompt: negativePrompt.value,
    // 旧字段兼容：当前变体的自由文字；完整变体存 `personBVariants`。
    personBText: personBText.value,
    personBVariants: clonePersonBVariants(personBVariants.value),
    personBVariantIndex: activePersonBVariantIndex.value,
    pairBatchExpanded: pairBatchExpanded.value,
    // P2：三槽模式单独持久化（旧数据没有这三个字段时由 hydrate 推导）。
    portraitMode: slotModes.value.portrait,
    costumeMode: slotModes.value.costume,
    poseMode: slotModes.value.pose,
    // P4：跨源补充开关；只在 image 模式有意义。
    portraitSupplement: supplementFlags.value.portrait,
    costumeSupplement: supplementFlags.value.costume,
    poseSupplement: supplementFlags.value.pose,
    recipeSourceId: recipeSourceId.value,
    recipeSourceName: recipeSourceName.value,
  })
}

/** 复合键：同一 id 可能同时存在于现实服装库与外链二次元库。 */
function slotKey(library: string, id: string): string {
  return `${library}\u0000${id}`
}

/**
 * 从持久化记录恢复三槽（**按 id + library 匹配库数据**）。
 *
 * - 必须在三个库加载完成后调用；调用方应在任一库加载失败时跳过，避免把
 *   「暂时没数据」误判成「条目已删除」进而覆盖存储；
 * - 匹配不到的 id 直接丢弃，绝不凭空造卡片；
 * - 恢复顺序保持存储顺序，去重后写入单例。
 *
 * 返回 true 表示读到了有效存储（无论是否匹配到条目）。
 */
function hydrate(libraries: ReferenceDraftLibraries): boolean {
  const stored = readReferenceStudioSettings()
  if (!stored) return false
  // 配对模式偏好必须先于三槽恢复：否则恢复出多选时会被误收敛成首张。
  pairBatchExpanded.value = stored.pairBatchExpanded

  const portraitByKey = new Map<string, PortraitItem>()
  for (const item of libraries.portrait) {
    portraitByKey.set(slotKey(item.library ?? 'portrait', item.id), item)
  }
  const costumeByKey = new Map<string, CostumeItem>()
  for (const item of libraries.costume) {
    costumeByKey.set(slotKey(item.library ?? 'costume', item.id), item)
  }
  const poseByKey = new Map<string, PoseItem>()
  for (const item of libraries.pose) {
    poseByKey.set(slotKey(item.library ?? 'pose', item.id), item)
  }

  const seenPortrait = new Set<string>()
  const nextPortrait: PortraitItem[] = []
  for (const entry of stored.portrait) {
    // 本地上传图不查库：文件路径即可重建卡片（文件被删时提交会 400）
    if (entry.path) {
      if (seenPortrait.has(entry.id)) continue
      seenPortrait.add(entry.id)
      nextPortrait.push(portraitUploadItem({ path: entry.path, name: entry.name }))
      continue
    }
    if (entry.library !== 'portrait' || seenPortrait.has(entry.id)) continue
    const item = portraitByKey.get(slotKey('portrait', entry.id))
    if (!item) continue
    seenPortrait.add(entry.id)
    nextPortrait.push(item)
  }

  const seenCostume = new Set<string>()
  const nextCostume: CostumeItem[] = []
  for (const entry of stored.costume) {
    if (entry.path) {
      const key = slotKey('upload', entry.id)
      if (seenCostume.has(key)) continue
      seenCostume.add(key)
      nextCostume.push(costumeUploadItem({ path: entry.path, name: entry.name }))
      continue
    }
    if (entry.library !== 'costume' && entry.library !== 'costume-anime') continue
    const key = slotKey(entry.library, entry.id)
    if (seenCostume.has(key)) continue
    const item = costumeByKey.get(key)
    if (!item) continue
    seenCostume.add(key)
    nextCostume.push(item)
  }

  const seenPose = new Set<string>()
  const nextPose: PoseSlotSelection[] = []
  for (const entry of stored.pose) {
    if (entry.path) {
      if (seenPose.has(entry.id)) continue
      seenPose.add(entry.id)
      nextPose.push(poseUploadSelection({ path: entry.path, name: entry.name }))
      continue
    }
    if (entry.library !== 'pose' || seenPose.has(entry.id)) continue
    const item = poseByKey.get(slotKey('pose', entry.id))
    if (!item) continue
    seenPose.add(entry.id)
    nextPose.push({ item, useDepth: entry.useDepth === true })
  }

  portrait.value = nextPortrait
  costume.value = nextCostume
  pose.value = nextPose
  if (nextPose[0]) lastPoseId.value = nextPose[0].item.id
  // 文本补充与三槽无关：这里一并恢复，保持「同一份快照一次性写进内存」的语义。
  restoreTextFragmentsFromSettings(stored)
  // 模式必须在三槽与碎片都恢复后应用：旧快照缺 mode 时按内容推导。
  applyStoredSlotModes(stored, true)
  return true
}

/**
 * 应用快照里的三槽模式。
 *
 * - `inferMissing = true`：三槽已恢复，缺 mode 的槽按「有图 / 有文本」推导；
 * - `inferMissing = false`：三槽尚未恢复（只恢复了文本），只应用显式字段，
 *   避免用空 items 把 image 误推导成 empty。
 */
function applyStoredSlotModes(
  stored: Pick<ReferenceStudioSettings, 'portraitMode' | 'costumeMode' | 'poseMode'>,
  inferMissing: boolean,
): void {
  if (!inferMissing) {
    const next = { ...slotModes.value }
    if (stored.portraitMode) next.portrait = stored.portraitMode
    if (stored.costumeMode) next.costume = stored.costumeMode
    if (stored.poseMode) next.pose = stored.poseMode
    slotModes.value = next
    normalizeSupplementFlags()
    return
  }

  const derived = deriveSlotModes(
    {
      portrait: portrait.value.length,
      costume: costume.value.length,
      pose: pose.value.length,
    },
    textFragments.value,
  )
  slotModes.value = {
    portrait: stored.portraitMode ?? derived.portrait,
    costume: stored.costumeMode ?? derived.costume,
    pose: stored.poseMode ?? derived.pose,
  }
  normalizeSupplementFlags()
}

/** 补充只在 image 模式成立：恢复 / 推导出 text / empty 时把残留开关归零。 */
function normalizeSupplementFlags(): void {
  const next = { ...supplementFlags.value }
  let changed = false
  for (const slot of RECIPE_SLOT_KEYS) {
    if (slotModes.value[slot] !== 'image' && next[slot]) {
      next[slot] = false
      changed = true
    }
  }
  if (changed) supplementFlags.value = next
}

/**
 * 旧快照的单张 B 身份 / B 服装迁移到第一条变体（2026-11-08）。
 *
 * 只在变体本身还没有绑图时迁移，绝不覆盖新格式数据；发型库的 extra 不迁移
 * （第 4 槽在发型工作流下是背面发型图，不属于 B 身份）。
 */
function migratePersonBVariantImages(
  variants: RecipePersonBVariant[],
  extraSlot: StoredReferenceExtraSlot,
  costumeSlot: StoredReferenceCostumeSlot,
): RecipePersonBVariant[] {
  const identityFromSlot: RecipePersonBImage | null =
    extraSlot.source === 'library' && extraSlot.library === 'portrait'
      ? {
          source: 'library',
          library: 'portrait',
          id: extraSlot.id,
          path: '',
          name: extraSlot.name,
        }
      : null
  const costumeFromSlot: RecipePersonBImage | null =
    costumeSlot.source === 'empty'
      ? null
      : {
          source: costumeSlot.source,
          library: costumeSlot.library,
          id: costumeSlot.id,
          path: costumeSlot.path,
          name: costumeSlot.name,
        }
  if (!identityFromSlot && !costumeFromSlot) return variants

  const list = variants.length ? variants : [createEmptyPersonBVariant('b-1')]
  const first = list[0]!
  const identity =
    first.identity.source === 'empty' && identityFromSlot ? identityFromSlot : first.identity
  const costume =
    first.costume.source === 'empty' && costumeFromSlot ? costumeFromSlot : first.costume
  if (identity === first.identity && costume === first.costume) return list
  return [{ ...first, identity, costume }, ...list.slice(1)]
}

/**
 * 把快照里的文本补充 / 负向写进内存。
 *
 * 同一会话只写一次（见 `textFragmentsRestoredFromStorage`）：页面可能多次挂载，
 * 重复从磁盘恢复会把尚未落盘的最新编辑覆盖成旧值。
 */
function restoreTextFragmentsFromSettings(
  stored: Pick<
    ReferenceStudioSettings,
    | 'extra'
    | 'extraCostume'
    | 'textFragments'
    | 'negativePrompt'
    | 'personBText'
    | 'personBVariants'
    | 'personBVariantIndex'
    | 'portraitSupplement'
    | 'costumeSupplement'
    | 'poseSupplement'
    | 'recipeSourceId'
    | 'recipeSourceName'
  >,
): void {
  if (textFragmentsRestoredFromStorage) return
  extra.value = { ...stored.extra }
  extraCostume.value = { ...stored.extraCostume }
  textFragments.value = cloneRecipeTextFragments(stored.textFragments)
  negativePrompt.value = stored.negativePrompt
  // v1.5：优先恢复变体列表；旧快照只有 personBText 时迁移成第一条变体。
  const restoredVariants = clonePersonBVariants(stored.personBVariants)
  if (restoredVariants.length) {
    personBVariants.value = restoredVariants
    // 恢复后把计数器抬到已有 `b-N` 的最大值，避免新增变体与旧 id 撞键。
    personBVariantSeq = restoredVariants.reduce((max, variant) => {
      const matched = /^b-(\d+)$/.exec(variant.id)
      return Math.max(max, matched ? Number(matched[1]) : 0)
    }, personBVariantSeq)
  } else if (stored.personBText.trim()) {
    personBVariants.value = [
      { ...createEmptyPersonBVariant('b-1'), freeText: stored.personBText },
    ]
  } else {
    personBVariants.value = []
  }
  // 2026-11-08：旧单张 B 身份/服装 → 第一条变体的绑定图（已是新格式则不动）。
  personBVariants.value = migratePersonBVariantImages(
    personBVariants.value,
    stored.extra,
    stored.extraCostume,
  )
  // 记住用户最后编辑的变体；越界时回落到最后一组。
  activePersonBVariantIndex.value = Math.min(
    stored.personBVariantIndex,
    Math.max(0, personBVariants.value.length - 1),
  )
  supplementFlags.value = cloneSupplementFlags({
    portrait: stored.portraitSupplement,
    costume: stored.costumeSupplement,
    pose: stored.poseSupplement,
  })
  recipeSourceId.value = stored.recipeSourceId
  recipeSourceName.value = stored.recipeSourceName
  textFragmentsRestoredFromStorage = true
}

/**
 * 只恢复文本补充 / 负向（不依赖三库加载）。
 *
 * 三槽必须按 id 回查库数据，只能等库加载成功；文本补充存的是全文，
 * 因此页面可以在挂载时先调用本函数，避免「库暂时失败 → 刷新后文本也没了」。
 *
 * 返回 true 表示读到了有效快照（无论文本是否为空）。
 */
function hydrateTextFragments(): boolean {
  const stored = readReferenceStudioSettings()
  if (!stored) return false
  // 配对模式偏好同样不依赖三库，先恢复以避免旧快照的多选被误收敛。
  pairBatchExpanded.value = stored.pairBatchExpanded
  restoreTextFragmentsFromSettings(stored)
  // 显式模式字段可以立即恢复（不依赖库数据）；缺字段的槽等三槽 hydrate 后再推导。
  applyStoredSlotModes(stored, false)
  return true
}

/**
 * 三槽变化自动落盘：**按槽位粒度**写入。
 *
 * 为什么不是整体写：三个库页签各自独立整页导航，未 hydrate 的页面里另外两个槽
 * 只是空数组（不是用户清空）。若整体覆盖，用户在服装页选一张就会把之前存的
 * 姿势 / 人像一并抹掉。分槽写只更新真正变化的槽，其余槽保留磁盘上的值。
 *
 * 放在模块级而不是某个组件里：选图发生在姿势 / 服装 / 人像页签，若只由合成台
 * 监听，用户「在库页选完图 → 刷新」会丢数据。单例语义保持不变。
 */
function persistPortrait(): void {
  writeReferenceStudioSettings({ portrait: portrait.value.map(storedPortrait) })
}
function persistCostume(): void {
  writeReferenceStudioSettings({ costume: costume.value.map(storedCostume) })
}
function persistPose(): void {
  writeReferenceStudioSettings({ pose: pose.value.map(storedPose) })
}

/**
 * 选图自动进入 image 模式（P2）。
 *
 * 用户在库页选图时不会经过合成台的模式开关，若不自动提升，`empty` 槽会变成
 * 「有图但模式为空」——槽位卡能显示图墙，提交体却不发图片字段。
 *
 * 只处理 `empty → image`：`text` 是用户显式选择的替代态，不因残留图片被改回；
 * 清空图片也不自动降级（模式由用户 / 校验决定）。
 */
watch(
  [portrait, costume, pose],
  () => {
    const next = { ...slotModes.value }
    let changed = false
    if (portrait.value.length > 0 && next.portrait === 'empty') {
      next.portrait = 'image'
      changed = true
    }
    if (costume.value.length > 0 && next.costume === 'empty') {
      next.costume = 'image'
      changed = true
    }
    if (pose.value.length > 0 && next.pose === 'empty') {
      next.pose = 'image'
      changed = true
    }
    if (changed) slotModes.value = next
  },
  { deep: true, flush: 'sync' },
)

watch(portrait, persistPortrait, { deep: true, flush: 'sync' })
watch(costume, persistCostume, { deep: true, flush: 'sync' })
watch(
  pose,
  () => {
    // 清空姿势不清 lastPoseId：切换文本替代后仍要能识别「上次是双人姿势」。
    const id = pose.value[0]?.item.id
    if (id) lastPoseId.value = id
    persistPose()
  },
  { deep: true, flush: 'sync' },
)

/**
 * 三槽模式单独落盘。
 *
 * 与三槽分槽写同理：只更新模式字段，不覆盖磁盘上的三槽 / 文本 / 其它设置。
 */
watch(
  slotModes,
  () => {
    writeReferenceStudioSettings({
      portraitMode: slotModes.value.portrait,
      costumeMode: slotModes.value.costume,
      poseMode: slotModes.value.pose,
    })
  },
  { deep: true, flush: 'sync' },
)

/** P4：补充开关单独落盘，不覆盖模式 / 三槽 / 文本。 */
watch(
  supplementFlags,
  () => {
    writeReferenceStudioSettings({
      portraitSupplement: supplementFlags.value.portrait,
      costumeSupplement: supplementFlags.value.costume,
      poseSupplement: supplementFlags.value.pose,
    })
  },
  { deep: true, flush: 'sync' },
)

/** 随机整套来源只做展示 / 去重，单独落盘。 */
watch(
  [recipeSourceId, recipeSourceName],
  () => {
    writeReferenceStudioSettings({
      recipeSourceId: recipeSourceId.value,
      recipeSourceName: recipeSourceName.value,
    })
  },
  { flush: 'sync' },
)

/**
 * 文本补充 / 负向单独落盘。
 *
 * 与三槽分槽写同理：只更新自己那份字段，绝不覆盖磁盘上的三槽选择。
 * 拷贝一份再写，避免把响应式 Proxy 带进待写补丁。
 */
watch(
  textFragments,
  () => {
    writeReferenceStudioSettings({
      textFragments: cloneRecipeTextFragments(textFragments.value),
    })
  },
  { deep: true, flush: 'sync' },
)
watch(
  negativePrompt,
  () => {
    writeReferenceStudioSettings({ negativePrompt: negativePrompt.value })
  },
  { flush: 'sync' },
)
watch(
  personBVariants,
  () => {
    writeReferenceStudioSettings({
      personBVariants: clonePersonBVariants(personBVariants.value),
      // 旧字段同步为当前变体自由文字，保证旧读取方仍能拿到文本。
      personBText: personBText.value,
      personBVariantIndex: activePersonBVariantIndex.value,
    })
  },
  { deep: true, flush: 'sync' },
)
watch(
  activePersonBVariantIndex,
  () => {
    // 切换变体只影响「哪条是新旧字段的镜像」，不改变变体内容本身。
    writeReferenceStudioSettings({
      personBText: personBText.value,
      personBVariantIndex: activePersonBVariantIndex.value,
    })
  },
  { flush: 'sync' },
)

/** 第 4 槽单独落盘：与三槽分槽写同理，不覆盖其它字段。 */
watch(
  extra,
  () => {
    writeReferenceStudioSettings({ extra: { ...extra.value } })
  },
  { deep: true, flush: 'sync' },
)

/**
 * 第 5 槽单独落盘（2026-11-08 补漏）。
 *
 * 此前只有 `persist()` 里带 `extraCostume`，但 `persist()` 没有调用方，
 * 导致 B 服装刷新后丢失；补上独立 watcher，与第 4 槽同口径。
 */
watch(
  extraCostume,
  () => {
    writeReferenceStudioSettings({ extraCostume: { ...extraCostume.value } })
  },
  { deep: true, flush: 'sync' },
)

/** 人像槽已选判定；不传 id 时返回「该槽是否非空」。 */
function isPortraitSelected(id?: string): boolean {
  if (id === undefined) return portrait.value.length > 0
  return portrait.value.some((entry) => entry.id === id)
}

/** 服装槽已选判定；不传 id 时返回「该槽是否非空」。 */
function isCostumeSelected(id?: string): boolean {
  if (id === undefined) return costume.value.length > 0
  return costume.value.some((entry) => entry.id === id)
}

/**
 * 姿势槽已选判定。
 *
 * - 只传 id：卡片口径 —— 已选态不区分白模 / 深度图；
 * - 同时传 `useDepth`：灯箱口径 —— 只有 id 与模式都一致才算「已在配方中」。
 */
function isPoseSelected(id: string, useDepth?: boolean): boolean {
  const current = pose.value.find((entry) => entry.item.id === id)
  if (!current) return false
  return useDepth === undefined ? true : current.useDepth === useDepth
}

/** 供三个库页面统一引用的 composable 视图。 */
export function useReferenceRecipeDraft() {
  return {
    portrait,
    costume,
    pose,
    // 第 4 槽（单图 + 文字补充；不进入批量笛卡尔积）
    extra,
    extraFilled,
    setExtraUpload,
    setExtraLibrary,
    setExtraText,
    clearExtra,
    // V2-C 第 5 槽（人物B服装，单图、整批共享）
    extraCostume,
    extraCostumeFilled,
    setExtraCostumeUpload,
    setExtraCostumeLibrary,
    clearExtraCostume,
    // 2026-11-08：B 变体绑定身份图/服装图（多选配对由此实现）
    setPersonBIdentityLibrary,
    setPersonBIdentityUpload,
    clearPersonBIdentity,
    setPersonBCostumeLibrary,
    setPersonBCostumeUpload,
    clearPersonBCostume,
    syncPersonBImagesFromVariant,
    // 文本补充（八类碎片）与负向提示词（2026-11-06）
    textFragments,
    negativePrompt,
    // 三槽模式（P2 替代态）与「上次姿势」（双人校验）
    slotModes,
    supplementFlags,
    recipeSourceId,
    recipeSourceName,
    lastPoseId,
    // v1.5：人物 B 文案变体（当前变体 + 增删 / 切换）
    personBVariants,
    activePersonBVariant,
    activePersonBVariantIndex,
    personBText,
    ensurePersonBVariant,
    addPersonBVariant,
    removePersonBVariant,
    setActivePersonBVariant,
    hasPairPose,
    // V2-C：双人配对模式（默认单图 / 单变体）与「批量展开」开关
    pairBatchExpanded,
    pairModeActive,
    pairLimitNotice,
    setPairBatchExpanded,
    setSlotMode,
    setSlotSupplement,
    setRecipeSource,
    count,
    countLabel,
    totalSelected,
    portraitCount,
    costumeCount,
    poseCount,
    isComplete,
    total: RECIPE_SLOT_TOTAL,
    addPortrait,
    setPortrait,
    togglePortrait,
    removePortrait,
    addCostume,
    setCostume,
    toggleCostume,
    removeCostume,
    addPose,
    setPose,
    togglePose,
    removePose,
    setPoseMode,
    // 本地上传图（三槽通用；与库条目共用一个数组，一起参与笛卡尔积）
    addPortraitUpload,
    addCostumeUpload,
    addPoseUpload,
    clearDraft,
    persist,
    hydrate,
    hydrateTextFragments,
    isPortraitSelected,
    isCostumeSelected,
    isPoseSelected,
  }
}