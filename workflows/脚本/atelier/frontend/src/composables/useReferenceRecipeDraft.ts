/**
 * 参考图库「角色配方」三槽位选择状态（阶段 2.1 / 合成台共用）。
 *
 * 口径（阶段 3 多选升级）：
 * - 每个槽位是**数组**，允许同一槽位加入多张参考图；空槽也允许提交，
 *   批量时由前端按组合逐组提交（后端每个请求仍是单值槽位）。
 * - 只做内存选择，**不做 IndexedDB / localStorage 持久化** —— 阶段 3 明确
 *   不迁配方草稿，用户已确认旧草稿全是测试数据。
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

import { computed, ref } from 'vue'

import type { CostumeItem, PoseItem, PortraitItem } from '../api/reference'

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
// 通用
// ---------------------------------------------------------------------------

/** 清空三槽（切换配方 / 新建时用）。 */
function clearDraft(): void {
  portrait.value = []
  costume.value = []
  pose.value = []
}

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
    clearDraft,
    isPortraitSelected,
    isCostumeSelected,
    isPoseSelected,
  }
}