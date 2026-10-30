import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PromptView from './PromptView.vue'
import { apiDelete, apiPost } from '../api/client'

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

describe('PromptView 分类关联', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
    vi.mocked(apiDelete).mockClear()
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
})
