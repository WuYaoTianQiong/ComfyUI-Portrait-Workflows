import { createRouter, createWebHistory } from 'vue-router'
import { defineComponent, h } from 'vue'

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
 * 参考图库已切到 atelier 托管的 React 台（默认 `/ref-web/`）。
 *
 * 入口地址由后端 `/api/system/status` 的 `reference_web_url` 下发，
 * 换端口或反代前缀时无需改前端；请求失败（旧后端、后端重启、超时）
 * 才回落默认 `/ref-web/`。
 *
 * `/ref-web` 是服务端子路径，不属于 Vue Router；必须整页跳转，
 * 不能用 router 的内部 redirect（会被 catch-all 兜回 /gallery）。
 * 旧的 `ReferenceView.vue` / `RefLightbox.vue` / `api/reference.ts` 已删除
 * （2026-11-04 验收收尾）；`/api/reference/*` 后端接口保留，继续服务混源出图与参考板。
 */

/** 后端未下发入口或请求失败时的兜底地址。 */
const REFERENCE_WEB_FALLBACK = '/ref-web/'

/**
 * 静态挂载入口需要尾斜杠：后端下发的默认值是 /ref-web（无斜杠），
 * 缺斜杠会多一次 307 跳转，历史里也多一条记录。
 */
function normalizeReferenceWebUrl(url: string | null | undefined): string {
  if (!url) return REFERENCE_WEB_FALLBACK
  return url.endsWith('/') ? url : `${url}/`
}

/**
 * 读取后端下发的参考图库地址。
 *
 * `/api/system/status` 在 ComfyUI 离线时要等一次探活超时（实测约 8s），
 * 这里 4s 后放弃并回落默认地址，避免用户盯着「正在打开参考图库…」干等。
 */
async function resolveReferenceWebUrl(): Promise<string> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 4_000)
  try {
    const response = await fetch('/api/system/status', {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
    if (!response.ok) return REFERENCE_WEB_FALLBACK
    const body = (await response.json()) as { reference_web_url?: string | null }
    return normalizeReferenceWebUrl(body?.reference_web_url)
  } catch {
    return REFERENCE_WEB_FALLBACK
  } finally {
    clearTimeout(timer)
  }
}

const ReferenceWebRedirect = defineComponent({
  name: 'ReferenceWebRedirect',
  setup() {
    if (typeof window !== 'undefined') {
      void resolveReferenceWebUrl().then((url) => {
        // 中间跳转页不得留在 history，否则后退会再次触发重定向形成回弹；
        // 返回画廊由 gallery-web 内的原生链接负责，不依赖 history。
        window.location.replace(url)
      })
    }
    return () =>
      h(
        'div',
        { style: 'padding: 32px; font-size: 14px; color: #1f2430' },
        '正在打开参考图库…',
      )
  },
})

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
    { path: '/reference', name: 'reference', component: ReferenceWebRedirect },
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
