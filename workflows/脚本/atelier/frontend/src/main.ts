import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'

import App from './App.vue'
import { router } from './router'
import { applyInitialTheme } from './utils/theme'
import './styles/tokens.css'

// 必须在 createApp().mount() 之前写 `<html data-theme>`：
// 让 tokens.css 在首帧就按用户上次选择的主题生效，避免深色闪一下再变浅色。
applyInitialTheme()

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
