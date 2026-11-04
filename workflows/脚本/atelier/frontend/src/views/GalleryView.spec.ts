import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import GalleryView from './GalleryView.vue'
import Lightbox from '../components/Lightbox.vue'
import { apiGet, apiPost } from '../api/client'
import { useToast } from '../composables/useToast'
import { useSettings } from '../composables/useSettings'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/images/ids')) {
      return { ids: [1, 2, 3], total: 3 }
    }
    if (path.includes('/api/images/facets')) {
      return {
        source: { local: 2, comfyui_sync: 0 },
        date: { '2026-10': 2 },
        model: {},
        orientation: { '竖图': 2 },
      }
    }
    if (path.includes('/api/workflows')) {
      return { workflows: [{ path: '/wf/a.json', name: '工作流A' }], default: '/wf/a.json' }
    }
    if (path.includes('/api/tags')) {
      return { tags: [{ id: 1, name: '标签', color: '#5b8fb9', usage_count: 0, prompt_count: 3 }] }
    }
    if (path.includes('/api/categories')) {
      return {
        categories: [
          {
            id: 7,
            name: '人像',
            parent_id: null,
            color: '#6366f1',
            sort_order: 0,
            prompt_count: 2,
            children: [],
          },
        ],
      }
    }
    return {
      items: [
        { id: 1, filename: 'a.png', subfolder: '', img_type: 'output', view_url: '', is_favorite: false, missing: false, created_at: '', captured_at: '', source: 'local', prompt_name: '', prompt_params: null, categories: [], tags: [] },
        { id: 2, filename: 'b.png', subfolder: '', img_type: 'output', view_url: '', is_favorite: false, missing: false, created_at: '', captured_at: '', source: 'local', prompt_name: '', prompt_params: null, categories: [], tags: [] },
      ],
      total: 2,
      page: 1,
      page_size: 60,
    }
  }),
  apiPost: vi.fn(async () => ({
    success: true,
    dry_run: true,
    total: 2,
    will_clean: 0,
    samples: [],
    guarded: false,
    message: '',
  })),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  thumbnailUrl: () => '/api/thumb?x.png',
  viewUrl: () => '/api/media/image?x.png',
}))

/** happy-dom 的 localStorage 不完整，这里补一份最小实现（刷新恢复用例需要）。 */
const store = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => {
    store.set(key, value)
  },
  removeItem: (key: string) => {
    store.delete(key)
  },
})

/** VTU 不支持 Playwright 的 has-text 选择器，只能 findAll + 过滤。 */
function cleanupButton(wrapper: ReturnType<typeof mount>) {
  const btn = wrapper.findAll('button').find((b) => b.text().includes('清理失效'))
  if (!btn) throw new Error('没找到「清理失效」按钮')
  return btn
}
describe('GalleryView 清理失效', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
    // toast 是模块级单例，测试之间要清干净
    useToast().toasts.value = []
    // 会话状态会跨用例保留，先清空再断言默认行为
    store.clear()
  })

  async function mountView() {
    const wrapper = mount(GalleryView, {
      global: {
      plugins: [
        [VueQueryPlugin, { queryClient: new QueryClient() }],
        // 画廊会读 route.query.image（深链定位），没有 router 会直接抛错
        createRouter({
          history: createMemoryHistory(),
          routes: [{ path: '/', component: { template: '<div />' } }, { path: '/gallery', component: { template: '<div />' } }],
        }),
      ],
      // Modal 用 Teleport 渲染到 body，测试里要 stub 掉才能在 wrapper 内查到
      stubs: { teleport: true },
    },
    })
    await flushPromises()
    return wrapper
  }

  it('分类筛选写入 category_id 并回到第 1 页', async () => {
    const wrapper = await mountView()
    const category = wrapper.findAll('.cat').find((b) => b.text().includes('人像'))
    expect(category).toBeTruthy()

    await category!.trigger('click')
    await flushPromises()

    const calls = vi.mocked(apiGet).mock.calls.filter(
      ([path]) =>
        String(path).includes('/api/images') &&
        !String(path).includes('/facets') &&
        !String(path).includes('/ids'),
    )
    const last = calls[calls.length - 1]
    expect(last?.[1]).toMatchObject({ category_id: 7, page: 1 })
  })

  it('点「清理失效」先发 dry_run 预览，不直接写库', async () => {
    const wrapper = await mountView()
    await cleanupButton(wrapper).trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, body, params] = vi.mocked(apiPost).mock.calls[0]
    expect(path).toBe('/api/images/cleanup_missing')
    expect(body).toBeUndefined()
    expect(params).toMatchObject({ dry_run: true })
    expect(params).not.toHaveProperty('confirm')
  })

  it('清理范围不带 missing —— 「只看失效」是清单不是范围', async () => {
    const wrapper = await mountView()
    await cleanupButton(wrapper).trigger('click')
    await flushPromises()

    const params = vi.mocked(apiPost).mock.calls[0][2] as Record<string, unknown>
    expect(params).not.toHaveProperty('missing')
  })

  it('无需清理时给出提示而不是弹确认框', async () => {
    const wrapper = await mountView()
    await cleanupButton(wrapper).trigger('click')
    await flushPromises()
    await wrapper.vm.$nextTick()

    // ToastHost 挂在 App.vue 根上，单测 GalleryView 时不在 DOM 里 —— 直接看 toast 状态
    const toasts = useToast().toasts.value
    expect(toasts.length).toBe(1)
    expect(toasts[0].text).toContain('无需清理')
  })
  it('点分面 chip 会把该维度加进查询参数', async () => {
    const wrapper = await mountView()
    await flushPromises()

    const chip = wrapper.findAll('.chip').find((b) => b.text().includes('local'))
    expect(chip).toBeTruthy()
    await chip!.trigger('click')
    await flushPromises()

    const historyCalls = vi
      .mocked(apiGet)
      .mock.calls.filter((c) => String(c[0]).includes('/api/images') && !String(c[0]).includes('facets'))
    const last = historyCalls[historyCalls.length - 1]
    expect((last[1] as Record<string, unknown>)?.source).toBe('local')
  })

  it('再点一次同一个 chip 取消该维度筛选', async () => {
    const wrapper = await mountView()
    await flushPromises()

    const chip = wrapper.findAll('.chip').find((b) => b.text().includes('local'))
    await chip!.trigger('click')
    await flushPromises()
    await wrapper.findAll('.chip').find((b) => b.text().includes('local'))!.trigger('click')
    await flushPromises()

    const historyCalls = vi
      .mocked(apiGet)
      .mock.calls.filter((c) => String(c[0]).includes('/api/images') && !String(c[0]).includes('facets'))
    const last = historyCalls[historyCalls.length - 1]
    expect((last[1] as Record<string, unknown>)?.source).toBe('')
  })
  it('「全选全部」跨页拉取当前筛选下的所有 id', async () => {
    const wrapper = await mountView()
    await flushPromises()

    const btn = wrapper.findAll('button').find((b) => b.text().includes('全选全部'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    const idsCalls = vi
      .mocked(apiGet)
      .mock.calls.filter((c) => String(c[0]).includes('/api/images/ids'))
    expect(idsCalls.length).toBe(1)
  })
  it('批量弹层提供「继承分类」与「投喂处理」', async () => {
    const wrapper = await mountView()
    const picks = wrapper.findAll('.card .pick')
    await picks[0].trigger('click')
    await picks[1].trigger('click')
    await flushPromises()

    const btn = wrapper.findAll('.btn').find((b) => b.text().includes('打标签'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('继承分类')
    expect(wrapper.text()).toContain('投喂处理')
  })

  it('「继承分类」按张调用 /api/images/{id}/inherit', async () => {
    const wrapper = await mountView()
    const picks = wrapper.findAll('.card .pick')
    await picks[0].trigger('click')
    await picks[1].trigger('click')
    await flushPromises()

    await wrapper.findAll('.btn').find((b) => b.text().includes('打标签'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('.btn').find((b) => b.text().includes('继承分类'))!.trigger('click')
    await flushPromises()

    const paths = vi.mocked(apiPost).mock.calls.map((c) => c[0])
    expect(paths).toContain('/api/images/1/inherit')
    expect(paths).toContain('/api/images/2/inherit')
  })

  it('批量删除的「同时删磁盘文件」勾选态会被记住并随请求发送', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const settings = useSettings()
    settings.deleteFiles.value = false

    const wrapper = await mountView()
    const deleteBtn = () => wrapper.findAll('.btn').find((b) => b.text().includes('删除选中'))!

    await wrapper.findAll('.card .pick')[0].trigger('click')
    await flushPromises()
    await deleteBtn().trigger('click')
    await flushPromises()
    expect(vi.mocked(apiPost).mock.calls[0][1]).toMatchObject({ ids: [1], delete_files: false })

    // 勾上之后必须落到 localStorage，下次进页面还认
    settings.deleteFiles.value = true
    await flushPromises()
    expect(store.get('pb.deleteFiles')).toBe('1')

    // 记住的勾选态要真的带进下一次请求（删除后选中被清空，重新选一张）
    await wrapper.findAll('.card .pick')[0].trigger('click')
    await flushPromises()
    await deleteBtn().trigger('click')
    await flushPromises()
    expect(vi.mocked(apiPost).mock.calls[1][1]).toMatchObject({ ids: [1], delete_files: true })

    confirmSpy.mockRestore()
  })

  it('刷新后按图片 id 恢复上次打开的灯箱', async () => {
    localStorage.setItem('pb.session.gallery', JSON.stringify({ viewerId: 2 }))
    const wrapper = await mountView()
    await flushPromises()

    // mock 数据里 id=2 是第二张（下标 1）
    expect(wrapper.findComponent(Lightbox).props('index')).toBe(1)
    localStorage.setItem('pb.session.gallery', JSON.stringify({ viewerId: null }))
  })

  it('卡片由缩略图、元信息行与操作区三段组成', async () => {
    const wrapper = await mountView()
    const card = wrapper.find('.card')

    expect(card.find('.thumb').exists()).toBe(true)
    expect(card.find('.caption .filename').exists()).toBe(true)
    expect(card.find('.caption .dim').exists()).toBe(true)
    expect(card.find('.actions .pick').exists()).toBe(true)
    expect(card.find('.actions .fav').exists()).toBe(true)
    expect(card.find('.actions .locate').exists()).toBe(true)
  })

  it('默认标准密度，可切换到紧凑档', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.cards').classes()).toContain('standard')
    expect(wrapper.find('.cards').classes()).not.toContain('compact')

    const compact = wrapper.findAll('button').find((b) => b.text() === '紧凑')!
    await compact.trigger('click')

    expect(wrapper.find('.cards').classes()).toContain('compact')
  })

  it('选中卡片后进入 picked 态并显示右上角对勾', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('.card .pick')[0].trigger('click')
    await flushPromises()

    expect(wrapper.find('.card').classes()).toContain('picked')
    expect(wrapper.find('.card .check-mark').exists()).toBe(true)
  })
})
