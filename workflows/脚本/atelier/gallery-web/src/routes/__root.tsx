import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Link, Outlet } from '@tanstack/react-router'
import { AppHeader } from '@/components/layout/AppHeader'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { RecipeDock } from '@/components/layout/RecipeDock'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootLayout,
  notFoundComponent: NotFoundPage,
})

function RootLayout() {
  return (
    <TooltipProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <AppHeader />
          <main className="@container/main flex min-w-0 flex-1 flex-col px-4 pt-4 pb-10 sm:px-6 md:px-8">
            <div className="mx-auto flex min-w-0 w-full max-w-7xl flex-1 flex-col gap-4 md:gap-6">
              <Outlet />
            </div>
            <RecipeDock />
          </main>
        </SidebarInset>
      </SidebarProvider>
      <Toaster position="top-center" richColors />
    </TooltipProvider>
  )
}

/**
 * 未匹配路由的兜底页。
 *
 * root route 的 notFoundComponent 会渲染在 RootLayout 的 <Outlet /> 位置，
 * 因此这里只输出内容区，侧栏与顶栏保持可用。
 *
 * 返回链接用 TanStack 的 `to="/"`：router 会按 basepath 自动生成 `/ref-web/`，
 * 不要手写成固定 `/ref-web/`，否则 base 调整后会拼错地址。
 */
function NotFoundPage() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-24 text-center">
      <span className="rounded-full border border-border px-2.5 py-0.5 text-xs font-semibold">404</span>
      <h1 className="text-xl font-semibold">页面不存在</h1>
      <p className="max-w-md text-sm">该地址在参考图库里没有对应页面，可能已删除或链接有误。</p>
      <Link to="/" className="mt-1 text-sm font-medium underline underline-offset-4 hover:text-primary">
        返回参考图库总览
      </Link>
    </div>
  )
}
