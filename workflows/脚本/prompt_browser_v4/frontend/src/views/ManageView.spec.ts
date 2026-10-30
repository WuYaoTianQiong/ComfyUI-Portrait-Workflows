import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ManageView from './ManageView.vue'
import { apiPost } from '../api/client'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/categories')) {
      return {
        categories: [
          { id: 1, name: '分类A', parent_id: null, color: '#6366f1', prompt_count: 2, children: [] },
        ],
      }
    }
    if (path.includes('/api/tags')) {
      return {
        tags: [
          { id: 1, name: '有用', color: '#000', usage_count: 0, prompt_count: 2 },
          { id: 2, name: '没用', color: '#000', usage_count: 0, prompt_count: 0 },
        ],
      }
    }
    return {}
  }),
  apiPost: vi.fn(async () => ({ success: true, id: 9 })),
  apiPut: vi.fn(async () => ({ success: true })),
  apiDelete: vi.fn(async () => ({ success: true })),
}))

async function mountView() {
  const wrapper = mount(ManageView, {
    global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]] },
  })
  await flushPromises()
  return wrapper
}

describe('ManageView 分类/标签管理', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
  })

  it('默认展示分类列表', async () => {
    const wrapper = await mountView()
    expect(wrapper.findAll('.row').length).toBe(1)
    expect(wrapper.text()).toContain('分类A')
  })

  it('新建分类调用 POST /api/categories', async () => {
    const wrapper = await mountView()
    const input = wrapper.find('.name-input')
    await input.setValue('新分类')
    await wrapper.findAll('.btn').find((b) => b.text() === '添加')!.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, body] = vi.mocked(apiPost).mock.calls[0]
    expect(path).toBe('/api/categories')
    expect((body as Record<string, unknown>).name).toBe('新分类')
  })

  it('点名称进入内联编辑', async () => {
    const wrapper = await mountView()
    await wrapper.find('.row-name').trigger('click')
    expect(wrapper.findAll('.inline-edit').length).toBe(1)
  })

  it('切到标签页后可只看未使用的标签', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('.tabs button').find((b) => b.text() === '标签')!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.row').length).toBe(2)

    const filter = wrapper.find('.only-unused input')
    await filter.setValue(true)
    await flushPromises()
    expect(wrapper.findAll('.row').length).toBe(1)
    expect(wrapper.text()).toContain('没用')
    expect(wrapper.text()).not.toContain('有用')
  })
})
