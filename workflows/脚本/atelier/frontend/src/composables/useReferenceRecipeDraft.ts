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
  readReferenceStudioSettings,
  writeReferenceStudioSettings,
} from './useReferenceStudioSettings'
import type { StoredReferenceSlotEntry } from './useReferenceStudioSettings'

/** 姿势槽位的值：条目 + 加入时的图片模式。 */
export interface PoseSlotSelection {
  item: PoseItem
  /** true = 深度图，false = 素体白模 */
  useDepth: boolean
}

/** 槽位键。 */
export type RecipeSlotKey = 'portrait' | 'costume' | 'pose'

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

/** 各槽条目数。 */
const portraitCount = computed(() => portrait.value.length)
const costumeCount = computed(() => costume.value.length)
const poseCount = computed(() => pose.value.length)

/** 三槽选中的条目总数（多选后的真实数量）。 */
const totalSelected = computed(
  () => portraitCount.value + costumeCount.value + poseCount.value,
)

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

/** 人像槽：追加一张；同 id 已存在时不重复加入。 */
function addPortrait(item: PortraitItem): void {
  if (portrait.value.some((entry) => entry.id === item.id)) return
  portrait.value = [...portrait.value, item]
}

/** 人像槽：整体替换为单张（随机捏人 / 旧调用方语义）；传 null 清空。 */
function setPortrait(item: PortraitItem | null): void {
  portrait.value = item ? [item] : []
}

/** 人像槽：点已选取消，否则追加。返回 true 表示本次是「加入」。 */
function togglePortrait(item: PortraitItem): boolean {
  const already = portrait.value.some((entry) => entry.id === item.id)
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

/** 服装槽：追加一张；同 id 已存在时不重复加入。 */
function addCostume(item: CostumeItem): void {
  if (costume.value.some((entry) => entry.id === item.id)) return
  costume.value = [...costume.value, item]
}

/** 服装槽：整体替换为单张；传 null 清空。 */
function setCostume(item: CostumeItem | null): void {
  costume.value = item ? [item] : []
}

/** 服装槽：点已选取消，否则追加。 */
function toggleCostume(item: CostumeItem): boolean {
  const already = costume.value.some((entry) => entry.id === item.id)
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

/** 姿势槽：追加；同 id 已存在时更新其模式（后写覆盖）。 */
function addPose(item: PoseItem, useDepth = false): void {
  const index = pose.value.findIndex((entry) => entry.item.id === item.id)
  if (index < 0) {
    pose.value = [...pose.value, { item, useDepth }]
    return
  }
  const next = [...pose.value]
  next[index] = { item, useDepth }
  pose.value = next
}

/** 姿势槽：整体替换为单条（随机捏人 / 旧调用方语义）；传 null 清空。 */
function setPose(item: PoseItem | null, useDepth = false): void {
  pose.value = item ? [{ item, useDepth }] : []
}

/**
 * 姿势槽：加入 / 移除 / 换模式。
 *
 * 只有「同 id 且同模式」才算已选，点击才移除；同 id 换模式视为更新条目。
 * 返回 true 表示操作后该条目仍在槽位中（加入或换模式），false 表示移除。
 */
function togglePose(item: PoseItem, useDepth = false): boolean {
  const index = pose.value.findIndex((entry) => entry.item.id === item.id)
  if (index < 0) {
    pose.value = [...pose.value, { item, useDepth }]
    return true
  }
  if (pose.value[index].useDepth === useDepth) {
    pose.value = pose.value.filter((_, i) => i !== index)
    return false
  }
  const next = [...pose.value]
  next[index] = { item, useDepth }
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

/** 把槽位内所有姿势统一改成白模 / 深度图（合成台顶部分段切换）。 */
function setPoseMode(useDepth: boolean): void {
  pose.value = pose.value.map((entry) => ({ ...entry, useDepth }))
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

/** 人像槽：加入一张本地图；同路径不重复。 */
function addPortraitUpload(input: UploadSlotInput): void {
  const id = `${UPLOAD_ID_PREFIX}${input.path}`
  if (portrait.value.some((entry) => entry.id === id)) return
  portrait.value = [...portrait.value, portraitUploadItem(input)]
}

/** 服装槽：加入一张本地图；同路径不重复。 */
function addCostumeUpload(input: UploadSlotInput): void {
  const id = `${UPLOAD_ID_PREFIX}${input.path}`
  if (costume.value.some((entry) => entry.id === id)) return
  costume.value = [...costume.value, costumeUploadItem(input)]
}

/** 姿势槽：加入一张本地图；同路径不重复。 */
function addPoseUpload(input: UploadSlotInput): void {
  const id = `${UPLOAD_ID_PREFIX}${input.path}`
  if (pose.value.some((entry) => entry.item.id === id)) return
  pose.value = [...pose.value, poseUploadSelection(input)]
}

// ---------------------------------------------------------------------------
// 通用
// ---------------------------------------------------------------------------

/** 清空三槽（切换配方 / 新建时用）。 */
function clearDraft(): void {
  portrait.value = []
  costume.value = []
  pose.value = []
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

watch(portrait, persistPortrait, { deep: true, flush: 'sync' })
watch(costume, persistCostume, { deep: true, flush: 'sync' })
watch(pose, persistPose, { deep: true, flush: 'sync' })

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
    isPortraitSelected,
    isCostumeSelected,
    isPoseSelected,
  }
}