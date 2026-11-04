import { createRouter, createWebHistory } from 'vue-router'
import { defineAsyncComponent, defineComponent, h, type Component } from 'vue'

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
 * 参考图库路由：骨架阶段先挂占位页。
 *
 * 用 `import.meta.glob` 而不是静态 import —— 会话 1 只能改 router.ts，
 * ReferenceView.vue 归会话 2；文件还没创建时静态 import 会直接把构建打挂。
 * 文件一旦落地，glob 自动命中并切到真实页面，router.ts 不需要再改。
 */
const referenceViewModules = import.meta.glob<{ default: Component }>('./views/ReferenceView.vue')
const referenceViewLoader = referenceViewModules['./views/ReferenceView.vue']

const ReferencePlaceholder = defineComponent({
  name: 'ReferencePlaceholder',
  render: () =>
    h('div', { style: 'padding: 32px' }, [
      h('h2', { style: 'margin: 0 0 12px; font-size: 20px; color: #1f2430' }, 'AI 参考图库'),
      h(
        'p',
        { style: 'margin: 0; font-size: 14px; color: #1f2430' },
        '页面施工中：浏览、检索、灯箱与白模/深度切换由后续会话接入。',
      ),
    ]),
})

const ReferenceView = referenceViewLoader
  ? defineAsyncComponent(() => referenceViewLoader().then((mod) => mod.default))
  : ReferencePlaceholder

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
    { path: '/reference', name: 'reference', component: ReferenceView },
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
