import { useLocation } from '@tanstack/react-router'
import { ATELIER_GALLERY_PATH, ATELIER_TOP_NAV } from '@/lib/atelierLinks'
import { isEmbeddedMode } from '@/lib/embedded'
import { cn } from '@/lib/utils'

/** 参考图库自身的入口（gallery-web 的宿主子路径）。 */
const REFERENCE_WEB_HREF = '/ref-web'

/**
 * 判断「参考图库」是否为当前导航项。
 *
 * 注意 TanStack Router 的 `useLocation().pathname` 已经剥离 basepath：
 * 生产环境拿到的是 `/`、`/studio`，而不是 `/ref-web/...`；dev 环境 basepath
 * 为空，路径同样是 `/`。因此单看 pathname 前缀会永远不命中，需要再对照
 * 浏览器真实地址：生产 BASE_URL 为 `/ref-web/`，dev 为 `/`（gallery-web 自身即根）。
 */
function isReferenceWebCurrent(pathname: string): boolean {
  if (pathname === REFERENCE_WEB_HREF || pathname.startsWith(`${REFERENCE_WEB_HREF}/`)) {
    return true
  }
  return typeof window !== 'undefined' && window.location.pathname.startsWith(import.meta.env.BASE_URL)
}

/**
 * atelier 全局顶栏（gallery-web 内的第一层导航）。
 *
 * 9 个入口全部指向 atelier 的页面，属于跨应用跳转，因此一律使用原生
 * `<a href>`：TanStack `<Link>` 会把 basepath 拼成 `/ref-web/gallery` 之类的错误地址。
 */
export function AtelierTopNav() {
  const pathname = useLocation({ select: (l) => l.pathname })

  // 双保险：AppHeader 已按内嵌模式做条件渲染，这里再兜一层，避免未来被
  // 其他布局直接引用时又把全局导航渲染进 iframe。必须先调用完 hook 再返回，
  // 以保证 hook 调用顺序稳定（embedded 状态本身在页面生命周期内不变）。
  if (isEmbeddedMode()) return null

  const referenceWebCurrent = isReferenceWebCurrent(pathname)

  return (
    <nav
      aria-label="画室全局导航"
      className="flex h-13 shrink-0 items-center gap-1 border-b border-border/60 px-4 text-sm"
    >
      {/* 品牌入口：整页导航回 atelier 画廊，与「画廊」项指向同一地址。 */}
      <a
        href={ATELIER_GALLERY_PATH}
        className="mr-2 flex shrink-0 items-center gap-2 rounded-md px-2 py-1 font-semibold text-foreground transition-colors hover:bg-muted/60"
      >
        <span
          aria-hidden="true"
          className="grid size-6 place-items-center rounded bg-primary text-[11px] font-bold text-primary-foreground"
        >
          AT
        </span>
        <span className="whitespace-nowrap">画室 Atelier</span>
      </a>

      {/* 窄屏时整条导航横向滚动，不换行、不折叠（各项 shrink-0 + 容器 flex-nowrap）。 */}
      <div className="flex min-w-0 flex-1 flex-nowrap items-center gap-1 overflow-x-auto">
        {ATELIER_TOP_NAV.map((item) => {
          const isCurrent = item.href === REFERENCE_WEB_HREF && referenceWebCurrent
          return (
            <a
              key={item.href}
              href={item.href}
              aria-current={isCurrent ? 'page' : undefined}
              className={cn(
                'shrink-0 rounded-md px-2.5 py-1.5 whitespace-nowrap transition-colors',
                isCurrent
                  ? 'bg-muted font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
              )}
            >
              {item.label}
            </a>
          )
        })}
      </div>
    </nav>
  )
}