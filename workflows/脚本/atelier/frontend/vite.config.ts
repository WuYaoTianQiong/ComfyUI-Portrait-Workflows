import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端固定 8656；开发期前端跑 5173，所有请求代理过去。
// 这样新前端可以在不碰旧页面的前提下逐页验证，随时能退回 static/ 那套。
const BACKEND = 'http://127.0.0.1:8656'

export default defineConfig({
  plugins: [vue()],
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
