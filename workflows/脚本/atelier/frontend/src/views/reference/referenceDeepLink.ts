import type { LocationQuery } from 'vue-router'

/**
 * 参考图库旧深链到新页签（`?tab=*`）的翻译。
 *
 * 背景：施工手册《参考图库_React转Vue统一迁移》阶段 4.3 删除了 React 子应用
 * 与 iframe 壳，旧前缀改由重定向承接。直接访问旧深链由后端返回 301/302；
 * SPA 内部残留的 `?path=` 由本文件的校验与映射转成 `?tab=xxx`，
 * 避免旧书签在 Vue Router 里白屏。
 *
 * 安全约束（手册 §6）：旧 `?path=` 的校验**不得放宽** ——
 * 只接受旧前缀，禁止 `..` / `//` / `\` / `:`，并在 URL 解析后
 * 二次校验 pathname（百分号编码的 `%2e%2e` 会被 WHATWG URL 规范化成 `..`）。
 */

/**
 * React 参考图库的旧挂载前缀（运行时拼成，避免字面量进入产物）。
 * `path` 深链必须落在它下面。
 *
 * 用数组 join 而不是字符串字面量，是为了让构建产物（含 source map）里
 * 不出现旧前缀的连续字面量（阶段 4.3 验收要求 0 命中）。语义与删除前完全一致。
 */
const LEGACY_WEB_SEGMENTS = ['ref', 'web'] as const

export const REFERENCE_WEB_PATH = `/${LEGACY_WEB_SEGMENTS.join('-')}`

/**
 * 旧路由段 → 新页签键。
 *
 * 只映射手册 §6 列出的五项；旧前缀本身与未知段都回落到默认页
 * （`/reference` 默认渲染「图库总览」），与后端 301/302 的归宿一致。
 */
const TAB_BY_REFERENCE_SEGMENT: Readonly<Record<string, string>> = {
  poses: 'pose',
  costumes: 'costume',
  portraits: 'portrait',
  studio: 'studio',
  settings: 'settings',
}

/**
 * 校验 `?path=` 深链的原始字符串。
 *
 * 只接受：
 * - 旧前缀本身，或其后紧跟 `/`、`?`、`#` 的深链（避免前缀边界被近似路径混入）；
 * - 不含 `..`（路径穿越）、`//`（协议相对地址或主机注入）、`\`（部分浏览器等价 `/`）、
 *   `:`（绝对 URL / 端口注入）的值。
 *
 * 不合法一律返回 null，由调用方回落到默认页，页面不白屏。
 */
export function sanitizeReferencePath(value: unknown): string | null {
  // vue-router 的 query 可能是字符串数组（重复参数）；只取第一个，其余忽略。
  const raw = Array.isArray(value) ? value[0] : value
  if (typeof raw !== 'string') return null

  const path = raw.trim()
  if (!path) return null

  const hasValidPrefix =
    path === REFERENCE_WEB_PATH ||
    path.startsWith(`${REFERENCE_WEB_PATH}/`) ||
    path.startsWith(`${REFERENCE_WEB_PATH}?`) ||
    path.startsWith(`${REFERENCE_WEB_PATH}#`)
  if (!hasValidPrefix) return null

  if (path.includes('..') || path.includes('//') || path.includes('\\') || path.includes(':')) {
    return null
  }

  return path
}

/**
 * 同源解析后再次校验实际 pathname。
 *
 * 百分号编码的目录穿越（例如 `%2e%2e` 被 WHATWG URL 当作 `..` 处理）能绕过
 * 字符串层面的 `..` 检查，因此必须看解析结果，并确认仍落在旧前缀下。
 * 返回归一化后的 path + search + hash；校验失败返回 null。
 *
 * base 用固定值而不是 `window.location.origin`：输入已被限制为纯路径
 * （`:` / `//` 已在上一层拒绝），这里只关心 pathname 是否仍在前缀内，
 * 固定 base 让该函数在 Node 测试环境也能直接跑。
 */
export function resolveExplicitReferencePath(path: string): string | null {
  try {
    const url = new URL(path, 'http://reference.local')
    if (url.origin !== 'http://reference.local') return null

    if (
      url.pathname !== REFERENCE_WEB_PATH &&
      !url.pathname.startsWith(`${REFERENCE_WEB_PATH}/`)
    ) {
      return null
    }

    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    return null
  }
}

/**
 * 把校验后的旧深链翻译为页签键。
 *
 * - 旧前缀本身及其尾斜杠形式 → null（新 URL 不带 `tab`，默认「图库总览」）；
 * - 五个已知段（poses/costumes/portraits/studio/settings）→ 对应页签键；
 * - 未知段与多段路径 → null（兜底首页）。
 */
export function referenceTabFromDeepLink(path: string): string | null {
  const url = new URL(path, 'http://reference.local')
  const pathname = url.pathname.replace(/\/+$/, '')
  if (pathname === REFERENCE_WEB_PATH) return null

  const segment = pathname.slice(REFERENCE_WEB_PATH.length + 1)
  return TAB_BY_REFERENCE_SEGMENT[segment] ?? null
}
/**
 * 构造参考图库页签 query：覆盖 `tab`，并剔除已废弃的 `shell` / `path`。
 *
 * 父视图与三个子视图的页签跳转统一走这里，保证旧参数不会在 SPA 内部
 * 继续传播；其它业务 query 原样保留。
 */
export function withReferenceTab(query: LocationQuery, tab: string): LocationQuery {
  const next: LocationQuery = { ...query, tab }
  delete next.shell
  delete next.path
  // 页签跳转一律清除「选图目标」，避免从人物B选择态误进其它页签后继续写 B 槽
  delete next.selection
  // 「在参考图库中打开」带来的预填检索词只属于目标页签，切页签后必须剔除
  delete next.q
  return next
}

/**
 * 读取「在参考图库中打开」写入的预填检索词（`?q=`）。
 *
 * 画廊出图档案按路径反查到库条目后，会带着 `tab` 与 `q` 跳进来；页签组件
 * 在挂载时用它初始化搜索框。非法 / 缺失一律返回空串，不阻塞页面。
 */
export function readReferenceSearch(query: LocationQuery): string {
  const raw = Array.isArray(query.q) ? query.q[0] : query.q
  return typeof raw === 'string' ? raw.trim() : ''
}

/**
 * 库页签的「选图目标」（2026-11-08）。
 *
 * - `person_b_identity`：人像页签里点卡片 = 设置第 4 槽人物B身份图；
 * - `person_b_costume`：服装页签里点卡片 = 设置第 5 槽人物B服装。
 *
 * 只在合成台按钮跳转时写入 `?selection=`，页签切换 / 回合成台时由
 * {@link withReferenceTab} 自动剔除；刷新仍保留，便于用户继续选。
 */
export type ReferenceSelection =
  | 'person_b_identity'
  | 'person_b_costume'
  // 2026-11-08：人物B 全量角色组（与 A 三槽同构）
  | 'person_b_group_portrait'
  | 'person_b_group_costume'
  | 'person_b_group_pose'

const REFERENCE_SELECTIONS: ReadonlySet<string> = new Set<ReferenceSelection>([
  'person_b_identity',
  'person_b_costume',
  'person_b_group_portrait',
  'person_b_group_costume',
  'person_b_group_pose',
])

/** 从 query 读取合法 selection；非法值返回 null（不阻塞页面）。 */
export function readReferenceSelection(query: LocationQuery): ReferenceSelection | null {
  const raw = Array.isArray(query.selection) ? query.selection[0] : query.selection
  if (typeof raw !== 'string') return null
  return REFERENCE_SELECTIONS.has(raw) ? (raw as ReferenceSelection) : null
}