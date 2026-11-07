/**
 * 参考图库加载 composable（阶段 1.2 数据层）。
 *
 * 覆盖四个库：`pose` / `costume` / `costume-anime` / `portrait`。
 * 服装库是两个物理库，必须并行拉取，并按「现实在前、二次元在后」合并；
 * 姿势库额外提供分组算法（分组键与角度顺序见 `buildPoseGroups`）。
 *
 * 边界：本文件只做数据装载与派生（items / groups / loading / error / retry），
 * 不持有安全模式、视图模式、选中项等展示状态 —— 那些属于视图层。
 */

import { computed, ref, shallowRef } from 'vue'
import type { Ref } from 'vue'

import {
  fetchAllReferenceItems,
  toCostumeItem,
  toHairItem,
  toPortraitItem,
  toPoseItem,
} from '@/api/reference'
import type {
  CostumeItem,
  HairItem,
  PoseGroup,
  PoseItem,
  PortraitItem,
} from '@/api/reference'

/** 组内角度展示顺序（与 React 版 `ANGLES` 一致）。 */
export const ANGLES = ['正面', '俯视', '仰视', '侧面', '斜侧'] as const

/** 体系（一级分类）优先顺序；不在表内的体系排在其后。 */
export const PREFERRED_POSE_LINE_ORDER = [
  '全身单人・标准系',
  '上半身单人',
  '全身单人・性感系',
  '双人缠绵',
] as const

/** 四库加载共用的响应式状态。 */
export interface LibraryState<T> {
  /** 已加载条目；整批替换，不做就地修改（配合 shallowRef 避免 4k 条深度代理） */
  items: Ref<T[]>
  loading: Ref<boolean>
  error: Ref<string | null>
  /** 首次加载 / 主动刷新 */
  load: () => Promise<void>
  /** 失败后重试；与 load 同一实现，单独命名便于模板绑定 */
  retry: () => Promise<void>
}

/** 姿势分组结果。`lines` 是排好序的体系列表，供药丸筛选使用。 */
export interface PoseGroups {
  items: PoseItem[]
  groups: PoseGroup[]
  lines: string[]
}

/** 体系排序权重：优先表内按序，表外统一 99（保持原始出现顺序靠后）。 */
function preferredLineRank(system: string): number {
  const index = PREFERRED_POSE_LINE_ORDER.indexOf(
    system as (typeof PREFERRED_POSE_LINE_ORDER)[number],
  )
  return index === -1 ? 99 : index
}

/**
 * 姿势条目分组（逐条平移 `gallery-web/src/api/gallery.ts` 的 `buildPoseGroups`）。
 *
 * - 分组键 `体系|姿势编号`；编号缺失时回退 `id`，避免空编号把所有条目挤成一组；
 * - 体系排序按 `PREFERRED_POSE_LINE_ORDER`，其余排后；
 * - 组内角度顺序固定 `正面/俯视/仰视/侧面/斜侧`，未列出的角度按原始顺序追加；
 * - 同组同角度只保留首个条目（与 React 版一致）。
 */
export function buildPoseGroups(items: PoseItem[]): PoseGroups {
  const rawLines = [...new Set(items.map((item) => item.体系))]
  const lines = rawLines.sort((a, b) => preferredLineRank(a) - preferredLineRank(b))

  const groupMap = new Map<string, PoseGroup>()
  const groups: PoseGroup[] = []

  for (const item of items) {
    const key = `${item.体系}|${item.姿势编号 || item.id}`
    let group = groupMap.get(key)
    if (!group) {
      group = {
        key,
        system: item.体系,
        number: item.姿势编号,
        name: item.姿势名称,
        category: item.分类,
        items: [],
        angles: {},
        order: [],
      }
      groupMap.set(key, group)
      groups.push(group)
    }
    group.items.push(item)
    if (item.角度 && !group.angles[item.角度]) {
      group.angles[item.角度] = item
    }
  }

  groups.sort(
    (a, b) =>
      lines.indexOf(a.system) - lines.indexOf(b.system) ||
      String(a.number).localeCompare(String(b.number)),
  )
  for (const group of groups) {
    group.order = ANGLES.map((angle) => group.angles[angle]).filter(Boolean)
    for (const item of group.items) {
      if (!group.order.includes(item)) group.order.push(item)
    }
  }

  return { items, groups, lines }
}

/**
 * 单库加载器。
 *
 * - 整批替换 `items`，失败时保留上一次成功的数据（刷新失败不闪空），只写 `error`；
 * - 同一时刻只允许一批请求在途：重复点「重试」复用同一个 Promise，不重复打后端。
 */
function createLibraryState<T>(loadItems: () => Promise<T[]>): LibraryState<T> {
  const items = shallowRef<T[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  let inflight: Promise<void> | null = null
  let loaded = false

  async function run(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      items.value = await loadItems()
      loaded = true
    } catch (cause) {
      // 数据层错误已带「加载参考库 X 第 N 页失败」前缀，这里原样透出给视图。
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      loading.value = false
    }
  }

  /** 首次挂载加载一次；已加载就直接复用，多个页签不会各拉一遍整库。 */
  function load(): Promise<void> {
    if (loaded) return Promise.resolve()
    if (inflight) return inflight
    inflight = run().finally(() => {
      inflight = null
    })
    return inflight
  }

  /** 用户主动刷新：强制重拉。 */
  function retry(): Promise<void> {
    loaded = false
    return load()
  }

  return { items, loading, error, load, retry }
}

/** 四页签共享的模块级库状态；key 固定为库名。 */
const libraryStores = new Map<string, LibraryState<unknown>>()

function sharedLibraryState<T>(
  key: string,
  loadItems: () => Promise<T[]>,
): LibraryState<T> {
  const existing = libraryStores.get(key) as LibraryState<T> | undefined
  if (existing) return existing
  const state = createLibraryState(loadItems)
  libraryStores.set(key, state as LibraryState<unknown>)
  return state
}

/** 测试或手动刷新时清空共享缓存；生产代码不需要调用。 */
export function resetReferenceLibraryState(): void {
  libraryStores.clear()
}

/** 姿势库：拉取 + 映射 + 分组。四页签共享同一份数据。 */
export function useReferencePoses(): PoseLibraryState {
  const state = sharedLibraryState('pose', () =>
    fetchAllReferenceItems('pose').then((dtos) => dtos.map(toPoseItem)),
  )
  const built = computed(() => buildPoseGroups(state.items.value))
  const groups = computed(() => built.value.groups)
  const lines = computed(() => built.value.lines)
  return { ...state, groups, lines }
}

/**
 * 服装库：`costume`（现实）与 `costume-anime`（二次元）并行拉取。
 *
 * 两个库各自分页并发 ≤6；合并顺序固定「现实在前、二次元在后」，
 * 与 React 版 `Promise.all([fetchAll('costume'), fetchAll('costume-anime')])` 一致。
 */
export function useReferenceCostumes(): CostumeLibraryState {
  return sharedLibraryState('costume', async () => {
    const [local, anime] = await Promise.all([
      fetchAllReferenceItems('costume'),
      fetchAllReferenceItems('costume-anime'),
    ])
    return [...local.map(toCostumeItem), ...anime.map(toCostumeItem)]
  })
}

/** 人像库。四页签共享同一份数据。 */
export function useReferencePortraits(): PortraitLibraryState {
  return sharedLibraryState('portrait', () =>
    fetchAllReferenceItems('portrait').then((dtos) => dtos.map(toPortraitItem)),
  )
}

/** 发型库（角色创作库全量包）。 */
export function useReferenceHairs(): HairLibraryState {
  return sharedLibraryState('hair', () =>
    fetchAllReferenceItems('hair').then((dtos) => dtos.map(toHairItem)),
  )
}

/** 供视图做类型标注的聚合类型（避免各页面重复声明）。 */
export type PoseLibraryState = LibraryState<PoseItem> & {
  groups: Ref<PoseGroup[]>
  lines: Ref<string[]>
}
export type CostumeLibraryState = LibraryState<CostumeItem>
export type PortraitLibraryState = LibraryState<PortraitItem>
export type HairLibraryState = LibraryState<HairItem>