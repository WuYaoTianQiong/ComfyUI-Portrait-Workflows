import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import GalleryView from './GalleryView.vue'
import { apiGet, apiPost } from '../api/client'
import { useToast } from '../composables/useToast'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/history/facets')) {
      return {
        source: { local: 2, comfyui_sync: 0 },
        date: { '2026-10': 2 },
        model: {},
        orientation: { '竖图': 2 },
      }
    }
    if (path.includes('/api/tags')) {
      return { tags: [{ id: 1, name: '标签', color: '#5b8fb9', usage_count: 0, prompt_count: 3 }] }
    }
    return {
      items: [
        { id: 1, filename: 'a.png', subfolder: '', img_type: 'output', view_url: '', favorite: false, missing: false, created_at: '', captured_at: '', source: 'local', prompt_name: '', prompt_params: null, categories: [], tags: [] },
        { id: 2, filename: 'b.png', subfolder: '', img_type: 'output', view_url: '', favorite: false, missing: false, created_at: '', captured_at: '', source: 'local', prompt_name: '', prompt_params: null, categories: [], tags: [] },
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
}))

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
  })

  async function mountView() {
    const wrapper = mount(GalleryView, {
      global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]] },
    })
    await flushPromises()
    return wrapper
  }

  it('点「清理失效」先发 dry_run 预览，不直接写库', async () => {
    const wrapper = await mountView()
    await cleanupButton(wrapper).trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, body, params] = vi.mocked(apiPost).mock.calls[0]
    expect(path).toBe('/api/history/cleanup_missing')
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
      .mock.calls.filter((c) => String(c[0]).includes('/api/history') && !String(c[0]).includes('facets'))
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
      .mock.calls.filter((c) => String(c[0]).includes('/api/history') && !String(c[0]).includes('facets'))
    const last = historyCalls[historyCalls.length - 1]
    expect((last[1] as Record<string, unknown>)?.source).toBe('')
  })
})
