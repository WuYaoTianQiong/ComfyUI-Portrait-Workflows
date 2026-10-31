import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'

import App from './App.vue'
import { router } from './router'
import './styles/tokens.css'

/**
 * 全局查询客户端。
 *
 * 取代旧前端的 `setInterval(loadHistory, 30000)` 与十几个 `window._galleryXxx`
 * 裸变量：缓存键即状态，窗口重新聚焦时才刷新，翻页/切筛选不会重复请求同一份数据。
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
})

createApp(App).use(router).use(createPinia()).use(VueQueryPlugin, { queryClient }).mount('#app')
