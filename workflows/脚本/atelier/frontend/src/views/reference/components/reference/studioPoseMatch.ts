/**
 * 同源整套随机的「配方姿态文字 → 姿势库 facet」匹配。
 *
 * 姿势文本在整套随机里默认不生效（姿势图锚定），但它仍然描述了配方想要的
 * 站/坐/跪/卧。用这段文字去匹配姿势库的 `分类`（facet），可以让随机抽到的
 * 姿势图与配方语义一致，避免「配方说坐、图是站」。
 *
 * 纯函数：不依赖 Vue / 网络；匹配不到或全是双人姿势时回退到安全池。
 */

/** 姿势库条目里本函数需要的字段（避免绑定完整 API 类型）。 */
export interface PoseMatchCandidate {
  id: string
  /** 姿势库的 `分类` / facet，例如 站姿、坐姿、跪立、趴卧、前倾。 */
  分类?: string
}

/**
 * 从配方姿态文字提取希望匹配的 facet 片段。
 *
 * 返回单字/短语 token，按「跪 → 坐 → 卧 → 站 → 前倾 → 特殊」的优先级；
 * 例如「跪坐」同时返回 跪 与 坐。
 */
export function desiredPoseFacets(poseText: string): string[] {
  const text = (poseText || '').trim()
  if (!text) return []
  const facets: string[] = []
  const add = (token: string): void => {
    if (!facets.includes(token)) facets.push(token)
  }
  if (/跪/.test(text)) add('跪')
  if (/坐/.test(text)) add('坐')
  if (/卧|躺|趴|俯卧|侧卧|仰卧/.test(text)) add('卧')
  if (/站|立姿|行走|走路|迈步|步伐/.test(text)) add('站')
  if (/前倾|俯身|轻靠|倚靠|搭扶|靠墙|侧靠/.test(text)) add('前倾')
  if (/蹲/.test(text)) add('特殊')
  return facets
}

/**
 * 从安全姿势池里按配方文字挑一张；匹配不到时回退到全部安全单人姿势。
 *
 * `pool` 由调用方按安全模式过滤；这里只额外排除 `pair*` 双人姿势。
 */
export function pickMatchedPose<T extends PoseMatchCandidate>(
  pool: readonly T[],
  poseText: string,
  random: () => number = Math.random,
): T | undefined {
  const safe = pool.filter((item) => !item.id.startsWith('pair'))
  if (safe.length === 0) return undefined
  const facets = desiredPoseFacets(poseText)
  // 按 facet 优先级逐个找：跪坐优先跪，其次坐；某一类没有匹配才看下一类。
  for (const facet of facets) {
    const matched = safe.filter((item) => (item.分类 || '').includes(facet))
    if (matched.length > 0) {
      return matched[Math.min(matched.length - 1, Math.floor(random() * matched.length))]
    }
  }
  return safe[Math.min(safe.length - 1, Math.floor(random() * safe.length))]
}

/** 原子库的 pose_facet → 姿势库分类 token。 */
export function poseFacetToken(facet: string): string {
  return (
    {
      stand: '站',
      walk: '站',
      sit: '坐',
      lean: '前倾',
      kneel: '跪',
    } as Record<string, string>
  )[facet] || ''
}

/**
 * 按原子库返回的 pose_facet 选姿势（优先于文本解析）。
 * 匹配不到时回退到全部安全单人姿势。
 */
export function pickPoseForFacet<T extends PoseMatchCandidate>(
  pool: readonly T[],
  facet: string,
  random: () => number = Math.random,
): T | undefined {
  const safe = pool.filter((item) => !item.id.startsWith('pair'))
  if (safe.length === 0) return undefined
  const token = poseFacetToken(facet)
  if (token) {
    const matched = safe.filter((item) => (item.分类 || '').includes(token))
    if (matched.length > 0) {
      return matched[Math.min(matched.length - 1, Math.floor(random() * matched.length))]
    }
  }
  return safe[Math.min(safe.length - 1, Math.floor(random() * safe.length))]
}
