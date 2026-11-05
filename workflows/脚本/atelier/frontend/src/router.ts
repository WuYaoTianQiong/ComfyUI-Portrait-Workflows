import { createRouter, createWebHistory } from 'vue-router'
import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'

import GalleryView from './views/GalleryView.vue'
import PromptView from './views/PromptView.vue'
import ComposerView from './views/ComposerView.vue'
import EditorView from './views/EditorView.vue'
import UpscaleView from './views/UpscaleView.vue'
import JobCenterView from './views/JobCenterView.vue'
import TaxonomyView from './views/TaxonomyView.vue'
import StatsView from './views/StatsView.vue'
import DesignView from './views/DesignView.vue'
import ReferenceView from './views/ReferenceView.vue'
import {
  referenceTabFromDeepLink,
  resolveExplicitReferencePath,
  sanitizeReferencePath,
} from './views/reference/referenceDeepLink'

/**
 * 参考图库入口归一（施工手册《参考图库_React转Vue统一迁移》§6）。
 *
 * 阶段 4.3 已删除 React 子应用与 iframe 壳，`/reference` 只剩纯 Vue 实现：
 * - `?shell=` 开关已废弃：无论带什么值都渲染 Vue 版，这里顺手把它从 URL 移除，
 *   避免旧书签继续传播已失效的参数；
 * - `?path=<旧前缀>/xxx` 是 iframe 时代的深链：用与后端同一套校验
 *   （旧前缀边界、禁 `..` / `//` / `\` / `:`、URL 解析后二次校验）
 *   翻译成 `?tab=xxx`；非法值直接去掉 `path`，回落默认页（图库总览），不白屏。
 *
 * 返回 `true` 表示参数已干净、无需跳转；返回路由地址时用 `replace`，
 * 不把旧深链记进浏览器历史。
 */
function normalizeReferenceEntry(to: RouteLocationNormalized): RouteLocationRaw | true {
  const query = { ...to.query }
  let changed = false

  if (to.query.path !== undefined) {
    changed = true
    delete query.path

    const rawPath = sanitizeReferencePath(to.query.path)
    const resolved = rawPath ? resolveExplicitReferencePath(rawPath) : null
    const tab = resolved ? referenceTabFromDeepLink(resolved) : null
    if (tab) query.tab = tab
  }

  if (to.query.shell !== undefined) {
    changed = true
    delete query.shell
  }

  if (!changed) return true
  return { path: '/reference', query, hash: to.hash, replace: true }
}

/**
 * URL 路由：每个页签一个真实路径。
 *
 * 之前用内存 `ref` 切页，刷新回画廊、返回无效、不能分享链接。
 * 路由参数让「跳到提示词」变成可深链的 `/prompt/123`。
 *
 * 路由段 / 视图名 / 导航文案三者同名（`命名规范.md` §8）：
 * `/gallery` ↔ `GalleryView` ↔ "画廊"、`/editor` ↔ `EditorView` ↔ "图像编辑"、
 * `/upscale` ↔ `UpscaleView` ↔ "批量超分"、`/taxonomy` ↔ `TaxonomyView` ↔ "分类与标签"。
 * 旧路径 `/faceswap`、`/manage`、`/design`
 * 各留一条 redirect，书签不失效。设计令牌预览是开发用页面，只在 `/dev/design`，顶栏无入口。
 */
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/gallery' },
    { path: '/gallery', name: 'gallery', component: GalleryView },
    {
      path: '/reference',
      name: 'reference',
      component: ReferenceView,

    },
    {
      path: '/prompt/:id?',
      name: 'prompt',
      component: PromptView,
      props: (route) => ({
        selectId: Number(route.params.id) > 0 ? Number(route.params.id) : null,
      }),
    },
    { path: '/composer', name: 'composer', component: ComposerView },
    { path: '/editor', name: 'editor', component: EditorView },
    { path: '/upscale', name: 'upscale', component: UpscaleView },
    { path: '/taxonomy', name: 'taxonomy', component: TaxonomyView },
    { path: '/jobs', name: 'jobs', component: JobCenterView },
    { path: '/stats', name: 'stats', component: StatsView },
    { path: '/dev/design', name: 'dev-design', component: DesignView },
    // 旧路径：P2c 改名后留一版 redirect，书签与外链不断
    { path: '/faceswap', redirect: '/editor' },
    { path: '/manage', redirect: '/taxonomy' },
    { path: '/design', redirect: '/dev/design' },
    { path: '/:pathMatch(.*)*', redirect: '/gallery' },
  ],
})
/**
 * 参考图库入口守卫：注册为全局 `beforeEach` 而不是路由级 `beforeEnter`。
 *
 * 原因：子视图切页签时是「同一路由的 query 变化」，不会触发 `beforeEnter`；
 * 全局守卫能在每次导航（含同路由 query 更新）都把 `shell` / `path` 清洗掉，
 * 保证旧参数不会在 SPA 内部传播。
 */
router.beforeEach((to) => {
  if (to.name !== 'reference') return true
  return normalizeReferenceEntry(to)
})