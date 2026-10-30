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
    // 构建产物落到 static_next/（与旧的 static/ 并存）。
    // 后端把 / 指向它、把旧前端挂在 /legacy，两个版本同时可访问，随时能回退。
    // 构建产物不入库（见仓库 .gitignore）。
    outDir: '../static_next',
    emptyOutDir: true,
    sourcemap: true,
  },
})
