/**
 * atelier 与参考图库（gallery-web）之间的跨应用链接。
 *
 * gallery-web 由 atelier 挂在子路径 `/ref-web/` 下托管，TanStack Router 的
 * basepath 也固定为 `/ref-web`。因此指向 atelier 自身页面（如 `/gallery`）
 * 的地址 **必须用原生 `<a href>` 做整页导航**：
 *
 * 若写成 TanStack `<Link to="/gallery">`，router 会把 basepath 拼进 URL，
 * 实际跳转成 `/ref-web/gallery` —— atelier 上并不存在这个路由，结果是 404。
 */

/** atelier 画廊首页路径（不在 TanStack basepath 内，必须整页导航）。 */
export const ATELIER_GALLERY_PATH = '/gallery'
/** atelier 顶栏导航项。href 均为 atelier 的真实路径，不含 `/ref-web` 前缀。 */
export interface AtelierNavLink {
  label: string
  href: string
}

/**
 * atelier 全局顶栏导航（顺序与文案和 Vue 主站顶栏保持一致）。
 *
 * 这些链接跨越了 gallery-web 的 basepath，渲染时 **必须使用原生 `<a href>`**，
 * 不得使用 TanStack Router 的 `<Link>`：后者会把 basepath 拼到地址前面，
 * 变成 `/ref-web/gallery` 这类 atelier 上不存在的路由。
 */
export const ATELIER_TOP_NAV: AtelierNavLink[] = [
  { label: '画廊', href: ATELIER_GALLERY_PATH },
  { label: '参考图库', href: '/ref-web' },
  { label: '提示词', href: '/prompt' },
  { label: '组合器', href: '/composer' },
  { label: '图像编辑', href: '/editor' },
  { label: '批量超分', href: '/upscale' },
  { label: '分类与标签', href: '/taxonomy' },
  { label: '任务', href: '/jobs' },
  { label: '统计', href: '/stats' },
]