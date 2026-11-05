import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// tsconfig 没有引入 @types/node（前端代码不使用 Node API），
// 这里用 DOM 的 URL 计算项目根目录，避免为一行别名引入 Node 类型依赖。
// Windows 下 pathname 形如 /F:/x/，去掉盘符前的斜杠即可。
// URL.pathname 是百分号编码的（仓库路径含中文），先 decode 再处理盘符。
const projectRoot = decodeURIComponent(new URL('./', import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1')

// 后端固定 8656；开发期前端跑 5173，所有请求代理过去。
// 这样新前端可以在不碰旧页面的前提下逐页验证，随时能退回 static/ 那套。
const BACKEND = 'http://127.0.0.1:8656'

export default defineConfig({
  plugins: [vue()],
  // 与 vitest.config.ts 的别名保持一致：阶段 1.2 的数据层用 `@/api/reference`
  // 导入，缺这条别名时 `vite build` 会解析失败（typecheck / vitest 不受影响，
  // 因为它们走 tsconfig paths 与 vitest 自己的 alias）。
  resolve: {
    alias: {
      '@': `${projectRoot}src`,
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/output': { target: BACKEND, changeOrigin: true },
      '/input': { target: BACKEND, changeOrigin: true },
      '/temp': { target: BACKEND, changeOrigin: true },
    },
  },
  build: {
    // 构建产物落到 web/：后端把它挂到 /，并作为 SPA fallback 的 index 来源。
    // 构建产物不入库（见仓库 .gitignore）。
    outDir: '../web',
    emptyOutDir: true,
    sourcemap: true,
  },
})
