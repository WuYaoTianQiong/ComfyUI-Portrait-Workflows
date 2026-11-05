/**
 * iframe 内嵌模式判定与深链归壳。
 *
 * gallery-web 被 atelier 以 iframe 承载时，外层 Vue 已经提供了完整的全局导航，
 * React 侧必须隐藏自己的第一行全局导航，避免出现两套导航。跨应用跳转则改用
 * `target="_top"`，让整页在顶层窗口跳转，而不是被困在 iframe 内部。
 *
 * 判定只以「当前文档是否运行在 iframe 内」为准（`window.self !== window.top`）。
 *
 * 不能依赖地址里的 `embedded=1`：TanStack Router 在 iframe 内做客户端导航时会把
 * query 丢掉（例如点击侧栏后地址变成 `/ref-web/portraits`），组件重渲染时
 * 判定会瞬间变回「非嵌入」，侧栏品牌、返回入口与全局导航就会重新出现。
 * 宿主把页面放进 iframe，本身就是「嵌入」的明确意图，因此不再要求 query。
 *
 * 顶层窗口直接打开 `/ref-web/?embedded=1` 时 `self === top`，仍视为非嵌入，
 * 导航保留，避免用户被困在没有入口的页面里。
 */
export function isEmbeddedMode(): boolean {
  // SSR / 构建期等无 window 的环境一律视为非内嵌。
  if (typeof window === 'undefined') return false

  return window.self !== window.top
}

/** 参考图库在 atelier 站点下的固定挂载路径（不带尾斜杠）。 */
const REFERENCE_PATH_PREFIX = '/ref-web'

/** Vue 外壳的入口路径。 */
const SHELL_PATH = '/reference'

/**
 * 把构建期 `BASE_URL` 归一化为不带尾斜杠的路径前缀。
 *
 * 生产构建为 `/ref-web/` → `/ref-web`；开发时 gallery-web 自身即根（`/`）或
 * 相对 base（`./`）没有可用的子路径前缀，返回空串。
 */
function resolveBasePrefix(): string {
  const base = import.meta.env?.BASE_URL
  if (typeof base !== 'string' || !base.startsWith('/')) return ''

  const normalized = `/${base.replace(/^\/+|\/+$/g, '')}`
  return normalized === '/' ? '' : normalized
}

/**
 * 一次深链访问可能落在固定挂载路径，也可能落在构建 base 对应的路径上，
 * 两者都视为参考图库的入口，统一交给 Vue 外壳。
 */
function collectShellPrefixes(): string[] {
  const prefixes = [REFERENCE_PATH_PREFIX]
  const basePrefix = resolveBasePrefix()
  if (basePrefix && basePrefix !== REFERENCE_PATH_PREFIX) prefixes.push(basePrefix)
  return prefixes
}

/** 路径必须等于前缀本身，或以「前缀 + /」开始，避免 `/ref-webevil` 误命中。 */
function matchesPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`)
}

/**
 * 非内嵌模式下直接访问 `/ref-web` 深链时，把整页 replace 到 Vue 的 `/reference`，
 * 由外层 Vue 提供统一导航，React 只作为 iframe 内容。
 *
 * 背景：旧的书签、外链或标签页可能直接指向 `/ref-web/poses` 等深链。若让 React
 * 原地渲染，它会按独立站点输出侧栏品牌、跨应用返回入口和完整导航，与外层 Vue
 * 的导航叠加成多套入口。因此这里在 React 根渲染之前改走外壳，并通过 `path`
 * 参数把原始深链交给 `ReferenceEmbedView` 塞进 iframe。
 *
 * 返回 true 表示已发起整页替换，调用方不应继续渲染 React 根，否则旧的独立导航
 * 会在跳转完成前闪一下。
 */
export function redirectToEmbeddedShell(): boolean {
  if (typeof window === 'undefined') return false

  // 已在 iframe 内且带 embedded=1：这是 iframe 内容的正常渲染路径，绝不重定向，
  // 否则会在 iframe 里再套一层 Vue 外壳，形成无限嵌套。
  if (isEmbeddedMode()) return false

  // 显式声明 embedded=1（即使当前在顶层窗口）也尊重其语义，不重定向，避免
  // 调试或宿主临时内嵌时出现外壳套外壳。
  if (new URLSearchParams(window.location.search).get('embedded') === '1') return false

  const { pathname, search, hash } = window.location
  if (!collectShellPrefixes().some((prefix) => matchesPrefix(pathname, prefix))) return false

  // 把原始深链（路径 + query + hash）整体交给外壳解析，避免丢失页内定位。
  const target = `${SHELL_PATH}?path=${encodeURIComponent(pathname + search + hash)}`
  window.location.replace(target)
  return true
}
