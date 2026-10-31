import { createRouter, createWebHistory } from 'vue-router'

import GalleryView from './views/GalleryView.vue'
import PromptView from './views/PromptView.vue'
import ComposerView from './views/ComposerView.vue'
import FaceswapView from './views/FaceswapView.vue'
import JobCenterView from './views/JobCenterView.vue'
import ManageView from './views/ManageView.vue'
import StatsView from './views/StatsView.vue'
import DesignView from './views/DesignView.vue'

/**
 * URL 路由：每个页签一个真实路径。
 *
 * 之前用内存 `ref` 切页，刷新回画廊、返回无效、不能分享链接。
 * 路由参数让「跳到提示词」变成可深链的 `/prompt/123`。
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
    { path: '/faceswap', name: 'faceswap', component: FaceswapView },
    { path: '/jobs', name: 'jobs', component: JobCenterView },
    { path: '/manage', name: 'manage', component: ManageView },
    { path: '/stats', name: 'stats', component: StatsView },
    { path: '/design', name: 'design', component: DesignView },
    { path: '/:pathMatch(.*)*', redirect: '/gallery' },
  ],
})
