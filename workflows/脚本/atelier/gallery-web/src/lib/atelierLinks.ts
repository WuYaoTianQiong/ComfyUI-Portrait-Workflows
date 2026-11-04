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