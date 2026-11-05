import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRouter, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { redirectToEmbeddedShell } from '@/lib/embedded'
import { StudioProvider } from '@/store/studioStore'
import { routeTree } from './routeTree.gen'
import './index.css'
import './notifications.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: Infinity,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

const router = createRouter({
  routeTree,
  context: { queryClient },
  // 构建时由 vite --base 注入；去掉尾部斜杠交给 TanStack Router 作为 basepath。
  basepath: import.meta.env.BASE_URL.replace(/\/$/, ''),
  defaultPreload: 'intent',
  defaultPreloadStaleTime: 0,
  scrollRestoration: true,
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
  interface StaticDataRouteOption {
    title?: string
  }
}

// 直接访问 /ref-web 深链时先切到 Vue 的 /reference 外壳；已发起整页替换就不再
// 挂载 React 根，避免旧的独立导航（侧栏品牌、返回入口）先闪一下。
// store/provider 的初始化顺序保持原样，只有渲染被条件跳过。
if (!redirectToEmbeddedShell()) {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <StudioProvider>
            <RouterProvider router={router} />
          </StudioProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </StrictMode>
  )
}
