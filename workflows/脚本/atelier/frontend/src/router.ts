import { createRouter, createWebHistory } from 'vue-router'

import GalleryView from './views/GalleryView.vue'
import PromptView from './views/PromptView.vue'
import ComposerView from './views/ComposerView.vue'
import EditorView from './views/EditorView.vue'
import UpscaleView from './views/UpscaleView.vue'
import JobCenterView from './views/JobCenterView.vue'
import TaxonomyView from './views/TaxonomyView.vue'
import StatsView from './views/StatsView.vue'
import DesignView from './views/DesignView.vue'
import ReferenceEmbedView from './views/ReferenceEmbedView.vue'

/**
 * 参考图库（上游 React 台）由 `/reference` 用 iframe 承载。
 *
 * 阶段一曾用 `location.replace('/ref-web/')` 整页跳走，外层顶栏随之中断；
 * 本轮用户拍板改为 iframe 承载，Vue 侧导航常驻，切换完全无感。
 *
 * 入口地址仍由后端 `/api/system/status` 的 `reference_web_url` 下发，
 * 由 `ReferenceEmbedView` 组装（强制 `embedded=1`，隐藏 React 侧全局导航）。
 *
 * `/ref-web` 是服务端子路径，不属于 Vue Router：Vue 只负责 `/reference`
 * 这一层壳，iframe 内的刷新与深链仍由服务端静态挂载处理，不能改成
 * router 的内部 redirect（会被 catch-all 兜回 /gallery）。
 * 旧的 `ReferenceView.vue` / `RefLightbox.vue` / `api/reference.ts` 已删除
 * （2026-11-04 验收收尾）；`/api/reference/*` 后端接口保留，继续服务混源出图与参考板。
 */

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
    { path: '/reference', name: 'reference', component: ReferenceEmbedView },
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
