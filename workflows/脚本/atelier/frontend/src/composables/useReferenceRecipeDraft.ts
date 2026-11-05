/**
 * 参考图库「角色配方」三槽位选择状态（阶段 2.1 / 后续合成台共用）。
 *
 * 口径（施工手册 M3）：
 * - 只做人像 / 服装 / 姿势**三个槽位**的内存选择，计数 n/3；
 * - **不做 IndexedDB / localStorage 持久化** —— 阶段 3 明确不迁配方草稿，
 *   用户已确认旧草稿全是测试数据；
 * - 模块级单例：姿势库、服装库、人像库、合成台、顶部配方槽共用同一份状态，
 *   避免每个页面各存一份导致「库里提示已选、合成台却是空的」。
 *
 * 姿势槽额外记录 `useDepth`（白模 / 深度图）。这是 React `recipe.pose.useDepth`
 * 的等价物：同一个姿势可以在两种模式下分别加入，已选判定与移除都必须带上模式，
 * 否则「白模已选 → 切深度图再点」会被误判为取消。
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

const portrait = ref<PortraitItem | null>(null)
const costume = ref<CostumeItem | null>(null)
const pose = ref<PoseSlotSelection | null>(null)

/** 已选槽位数量（0–3）。 */
const count = computed(
  () => (portrait.value ? 1 : 0) + (costume.value ? 1 : 0) + (pose.value ? 1 : 0),
)

/** 顶部 / 侧栏展示用的 `n/3`。 */
const countLabel = computed(() => `${count.value}/${RECIPE_SLOT_TOTAL}`)

/** 三槽是否已选满（合成台提交前置条件）。 */
const isComplete = computed(() => count.value === RECIPE_SLOT_TOTAL)

/** 人像槽：直接覆盖（单槽单选）。 */
function setPortrait(item: PortraitItem | null): void {
  portrait.value = item
}

/** 人像槽：点同一条取消，否则替换。 */
function togglePortrait(item: PortraitItem): boolean {
  const already = portrait.value?.id === item.id
  portrait.value = already ? null : item
  return !already
}

function removePortrait(): void {
  portrait.value = null
}

/** 服装槽：直接覆盖。 */
function setCostume(item: CostumeItem | null): void {
  costume.value = item
}

function toggleCostume(item: CostumeItem): boolean {
  const already = costume.value?.id === item.id
  costume.value = already ? null : item
  return !already
}

function removeCostume(): void {
  costume.value = null
}

/**
 * 姿势槽：直接覆盖（带模式）。
 *
 * 允许同一 id 以不同模式存在（后写覆盖），与 React `setPose` 语义一致。
 */
function setPose(item: PoseItem | null, useDepth = false): void {
  pose.value = item ? { item, useDepth } : null
}

/**
 * 姿势槽：加入 / 移除。
 *
 * 只有「同 id 且同模式」才算已选，点击才移除；否则视为替换。
 * 返回 true 表示本次是「加入 / 替换」，false 表示「移除」。
 */
function togglePose(item: PoseItem, useDepth = false): boolean {
  const current = pose.value
  const remove = current?.item.id === item.id && current.useDepth === useDepth
  pose.value = remove ? null : { item, useDepth }
  return !remove
}

function removePose(): void {
  pose.value = null
}

/** 清空三槽（切换配方 / 新建时用）。 */
function clearDraft(): void {
  portrait.value = null
  costume.value = null
  pose.value = null
}

/**
 * 人像槽已选判定。
 *
 * 不传 id 时返回「是否已选人像」，便于调用方做空判断。
 */
function isPortraitSelected(id?: string): boolean {
  if (!portrait.value) return false
  return id === undefined ? true : portrait.value.id === id
}

function isCostumeSelected(id?: string): boolean {
  if (!costume.value) return false
  return id === undefined ? true : costume.value.id === id
}

/**
 * 姿势槽已选判定。
 *
 * - 只传 id：卡片口径 —— React 卡片只看 id（`recipe.pose?.id === item.id`），
 *   已选态不区分白模 / 深度图；
 * - 同时传 `useDepth`：灯箱口径 —— 只有 id 与模式都一致才算「已在配方中」。
 */
function isPoseSelected(id: string, useDepth?: boolean): boolean {
  const current = pose.value
  if (!current || current.item.id !== id) return false
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
    isComplete,
    total: RECIPE_SLOT_TOTAL,
    setPortrait,
    togglePortrait,
    removePortrait,
    setCostume,
    toggleCostume,
    removeCostume,
    setPose,
    togglePose,
    removePose,
    clearDraft,
    isPortraitSelected,
    isCostumeSelected,
    isPoseSelected,
  }
}