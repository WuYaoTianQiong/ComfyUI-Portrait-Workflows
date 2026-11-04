/**
 * iframe 内嵌模式判定。
 *
 * gallery-web 被 atelier 以 iframe 承载时，外层 Vue 已经提供了完整的全局导航，
 * React 侧必须隐藏自己的第一行全局导航，避免出现两套导航。跨应用跳转则改用
 * `target="_top"`，让整页在顶层窗口跳转，而不是被困在 iframe 内部。
 *
 * 判定必须 **同时** 满足两个条件：
 * 1. 当前文档运行在 iframe 内（`window.self !== window.top`）；
 * 2. 地址显式带有 `embedded=1`。
 *
 * 只判 URL 是不安全的：用户直接打开 `/ref-web/?embedded=1` 时全局导航会被隐藏，
 * 且所有跨应用入口都用 `target="_top"` —— 而页面本身并不在 iframe 内，相当于
 * 被困在一个「没有导航」的页面里。只判 iframe 同样不行：宿主页面若临时内嵌
 * 却不希望隐藏导航，就会失去入口。两者同时成立才认定为内嵌模式。
 */
export function isEmbeddedMode(): boolean {
  // SSR / 构建期等无 window 的环境一律视为非内嵌。
  if (typeof window === 'undefined') return false

  if (window.self === window.top) return false

  return new URLSearchParams(window.location.search).get('embedded') === '1'
}