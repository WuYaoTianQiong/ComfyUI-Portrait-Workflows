/**
 * 合成台三库随机池（模块级单例）。
 *
 * `useReferenceLibrary` 的每个 `useReference*` 都是独立实例；合成台需要在
 * 「随机捏人」时拿到三库全量条目。放在模块级可以让切页签回来时不重复拉取
 * 4 个库（约 3700 条、20 个分页请求），也保证同一时刻只跑一批请求。
 *
 * 只做数据装载，不做筛选：安全模式过滤由 `ReferenceStudioTab` 的随机逻辑负责。
 */

import {
  useReferenceCostumes,
  useReferencePortraits,
  useReferencePoses,
} from '../../../../composables/useReferenceLibrary'

const poses = useReferencePoses()
const costumes = useReferenceCostumes()
const portraits = useReferencePortraits()

/** 是否已成功装载过：切页签回来不重复拉 4 个库（约 20 个分页请求）。 */
let loaded = false

/** 三库并行加载（内部各自捕获错误，不会产生未处理 rejection）。 */
async function loadAll(): Promise<void> {
  if (loaded) return
  await Promise.all([poses.load(), costumes.load(), portraits.load()])
  // 任一库失败时保留「未装载」，下次进入合成台 / 点随机时还能重试。
  loaded = !poses.error.value && !costumes.error.value && !portraits.error.value
}

export function useStudioLibraries() {
  return { poses, costumes, portraits, loadAll }
}