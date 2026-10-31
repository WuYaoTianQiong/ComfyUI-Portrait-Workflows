import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PromptView from './PromptView.vue'
import { apiDelete, apiGet, apiPost } from '../api/client'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/categories')) {
      return {
        categories: [
          { id: 1, name: '分类A', parent_id: null, color: '#6366f1', prompt_count: 1, children: [] },
          { id: 2, name: '分类B', parent_id: null, color: '#22c55e', prompt_count: 0, children: [] },
        ],
      }
    }
    if (path.includes('/api/tags')) return { tags: [] }
    if (path.includes('/api/prompts/')) {
      return {
        id: 1,
        name: '示例',
        prompt: '内容',
        negative_prompt: '',
        steps: null,
        cfg_scale: null,
        sampler: '',
        seed: null,
        model: '',
        width: null,
        height: null,
        tags: '',
        note: '',
        created_at: '2026-10-30 10:00:00',
        updated_at: '2026-10-30 10:00:00',
        is_favorite: false,
        is_pinned: false,
        usage_count: 0,
        last_used_at: null,
        rating: null,
        categories: [{ id: 1, name: '分类A', color: '#6366f1' }],
        tags_detail: [],
      }
    }
    return {
      prompts: [
        {
          id: 1,
          prompt_preview: '内容',
          tags: '',
          steps: null,
          sampler: '',
          model: '',
          name: '示例',
          created_at: '2026-10-30 10:00:00',
          is_favorite: false,
          is_pinned: false,
          rating: null,
          usage_count: 0,
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    }
  }),
  apiPost: vi.fn(async () => ({ success: true })),
  apiPut: vi.fn(async () => ({ success: true })),
  apiDelete: vi.fn(async () => ({ success: true })),
}))

async function mountView() {
  const wrapper = mount(PromptView, {
    global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]] },
  })
  await flushPromises()
  return wrapper
}

async function mountWithSelect(selectId: number) {
  const wrapper = mount(PromptView, {
    props: { selectId },
    global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]] },
  })
  await flushPromises()
  return wrapper
}

describe('PromptView 分类关联', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
    vi.mocked(apiDelete).mockClear()
    vi.mocked(apiPost).mockClear()
  })

  it('详情页列出所有分类', async () => {
    const wrapper = await mountView()
    await wrapper.find('.row').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.cat-chip').length).toBe(2)
  })

  it('已关联的分类高亮', async () => {
    const wrapper = await mountView()
    await wrapper.find('.row').trigger('click')
    await flushPromises()
    const on = wrapper.findAll('.cat-chip').filter((c) => c.classes().includes('on'))
    expect(on.length).toBe(1)
    expect(on[0].text()).toBe('分类A')
  })

  it('点未关联的分类走 POST 关联', async () => {
    const wrapper = await mountView()
    await wrapper.find('.row').trigger('click')
    await flushPromises()
    const target = wrapper.findAll('.cat-chip').find((c) => c.text() === '分类B')!
    await target.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(vi.mocked(apiPost).mock.calls[0][0]).toBe('/api/categories/2/prompts/1')
  })

  it('点已关联的分类走 DELETE 取消关联', async () => {
    const wrapper = await mountView()
    await wrapper.find('.row').trigger('click')
    await flushPromises()
    const target = wrapper.findAll('.cat-chip').find((c) => c.text() === '分类A')!
    await target.trigger('click')
    await flushPromises()

    expect(apiDelete).toHaveBeenCalledTimes(1)
    expect(vi.mocked(apiDelete).mock.calls[0][0]).toBe('/api/categories/1/prompts/1')
  })
  it('「自动归类」调用单条自动分类端点', async () => {
    const wrapper = await mountView()
    await wrapper.find('.row').trigger('click')
    await flushPromises()

    const btn = wrapper.findAll('.btn').find((b) => b.text().includes('自动归类'))!
    expect(btn).toBeTruthy()
    await btn.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(vi.mocked(apiPost).mock.calls[0][0]).toBe('/api/categories/auto-classify/1')
  })
})

describe('PromptView 外部跳转与草稿恢复', () => {
  // happy-dom 的 localStorage 只提供 getItem/setItem，这里补一个完整实现
  const store = new Map<string, string>()

  beforeEach(() => {
    vi.mocked(apiGet).mockClear()
    vi.mocked(apiPost).mockClear()
    vi.mocked(apiDelete).mockClear()
    store.clear()
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    })
  })

  it('跳到提示词：直接查询目标 id 而不是列表第一条', async () => {
    await mountWithSelect(7)

    // 目标 id 不在列表首页里，也必须查询 7
    expect(vi.mocked(apiGet)).toHaveBeenCalledWith('/api/prompts/7')
  })

  it('详情到达后恢复本地草稿', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    localStorage.setItem('pb.draft.7', JSON.stringify({ prompt: '草稿内容' }))

    const wrapper = await mountWithSelect(7)

    const editor = wrapper.find('textarea').element as HTMLTextAreaElement
    expect(editor.value).toBe('草稿内容')
    confirmSpy.mockRestore()
    localStorage.removeItem('pb.draft.7')
  })

  it('放弃恢复时清掉本地草稿', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    localStorage.setItem('pb.draft.7', JSON.stringify({ prompt: '草稿内容' }))

    const wrapper = await mountWithSelect(7)

    const editor = wrapper.find('textarea').element as HTMLTextAreaElement
    expect(editor.value).toBe('内容')
    expect(localStorage.getItem('pb.draft.7')).toBeNull()
    confirmSpy.mockRestore()
  })

  it('回到提示词页时恢复上次的搜索词', async () => {
    localStorage.setItem(
      'pb.session.prompt',
      JSON.stringify({
        page: 2,
        search: '关键词',
        categoryId: null,
        tagIds: [],
        tagMatch: 'all',
        selectedId: 1,
        scrollTop: 0,
      }),
    )

    const wrapper = await mountView()

    expect((wrapper.find('.search').element as HTMLInputElement).value).toBe('关键词')
  })
})
