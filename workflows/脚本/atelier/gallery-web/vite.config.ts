import fs from 'node:fs'
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

const MIME: Record<string, string> = {
  '.json': 'application/json; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.xml': 'application/xml; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
}

// 开发与预览时：直接挂载仓库根目录下的 data/、thumbs/、img/，避免拷贝 6.8 GB 素材
function localAssetsPlugin(): Plugin {
  const rootDir = import.meta.dirname
  const prefixes = ['/data/', '/thumbs/', '/img/']

  const serve = (req: any, res: any, next: any) => {
    const decoded = decodeURIComponent((req.url || '').split('?')[0])
    if (!prefixes.some((p) => decoded === p || decoded.startsWith(p))) {
      return next()
    }
    const filePath = path.join(rootDir, decoded)
    if (!filePath.startsWith(rootDir) || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      return next()
    }
    const ext = path.extname(filePath).toLowerCase()
    res.setHeader('Content-Type', MIME[ext] || 'application/octet-stream')
    res.setHeader('Cache-Control', 'public, max-age=3600')
    fs.createReadStream(filePath).pipe(res)
  }

  return {
    name: 'local-assets-plugin',
    configureServer(server) {
      server.middlewares.use(serve)
    },
    configurePreviewServer(server) {
      server.middlewares.use(serve)
    },
  }
}

// 本地 ComfyUI 同源代理：浏览器请求 /comfy/* → ComfyUI（默认 Desktop 端口 8000）
// 这样无需修改 ComfyUI 的 --enable-cors-header 白名单。可用环境变量 COMFYUI_URL 指定其他地址。
const COMFYUI_URL = process.env.COMFYUI_URL || 'http://127.0.0.1:8000'
const comfyProxy = {
  '/comfy': {
    target: COMFYUI_URL,
    changeOrigin: true,
    ws: true,
    rewrite: (p: string) => p.replace(/^\/comfy/, '') || '/',
    configure: (proxy: any) => {
      // ComfyUI 对带 Origin 的跨源请求做校验，代理转发时去掉浏览器 Origin，按同源请求处理
      proxy.on('proxyReq', (proxyReq: any) => proxyReq.removeHeader('origin'))
      proxy.on('proxyReqWs', (proxyReq: any) => proxyReq.removeHeader('origin'))
    },
  },
}

export default defineConfig({
  publicDir: false,
  plugins: [
    localAssetsPlugin(),
    tanstackRouter({ target: 'react', autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  build: {
    // 开启清空 outDir，并由 build:prod 的 scripts/clean-dist.mjs 兜底：
    // 部分受管控环境会把 fs.rmSync 拦截成 no-op，旧 hash 产物会与新产物一起堆积（实测 25 → 36 个文件）。
    emptyOutDir: true,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'react-vendor', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
            { name: 'tanstack-vendor', test: /node_modules[\\/]@tanstack[\\/]/ },
            { name: 'ui-vendor', test: /node_modules[\\/](radix-ui|@radix-ui|lucide-react|sonner)[\\/]/ },
          ],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: comfyProxy,
  },
  preview: {
    proxy: comfyProxy,
  },
})
