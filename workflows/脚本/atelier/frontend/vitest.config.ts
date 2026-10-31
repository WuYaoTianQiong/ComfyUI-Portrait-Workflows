import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

/**
 * 前端单元 / 组件测试配置。
 *
 * 独立于 vite.config.ts：构建配置和测试配置的演进节奏不同（构建要产出，
 * 测试要快），混在一起迟早互相牵制。
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.spec.ts'],
    globals: true,
  },
})
