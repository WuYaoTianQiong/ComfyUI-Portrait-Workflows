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
