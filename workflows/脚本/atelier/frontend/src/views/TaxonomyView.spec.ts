import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import TaxonomyView from './TaxonomyView.vue'
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
    // 深链定位用：不分页、全量按类型分组的碎片索引
    if (path.includes('/api/fragments/by_type')) {
      return {
        grouped: { 人物面部: [{ fragment_id: 1, name: '侧脸', fragment_type: '人物面部' }] },
        total: 1,
      }
    }
    if (path.includes('/api/fragments')) {
      return {
        items: [
          { id: 1, name: '侧脸', fragment_type: '人物面部', content: '微微侧脸', tags: '', usage_count: 2 },
        ],
        total: 1,
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

const stub = { template: '<div />' }

async function mountView(initialPath = '/taxonomy') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/taxonomy', component: stub },
      { path: '/', component: stub },
    ],
  })
  // 深链（?panel=fragment&frag=1）必须在挂载前就生效，否则组件读到的是空路由
  await router.push(initialPath)
  await router.isReady()
  const wrapper = mount(TaxonomyView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }], router],
    },
  })
  await flushPromises()
  return wrapper
}

describe('TaxonomyView 分类与标签', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
    // 组件里用了 confirm 二次确认，测试环境默认没有
    vi.stubGlobal('confirm', () => true)
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
  it('「一键自动分类」调用全量自动分类端点', async () => {
    const wrapper = await mountView()
    const btn = wrapper.findAll('.btn').find((b) => b.text().includes('一键自动分类'))!
    expect(btn).toBeTruthy()
    await btn.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(vi.mocked(apiPost).mock.calls[0][0]).toBe('/api/categories/auto-classify')
  })
  // α 之后碎片库 tab 已删除（碎片 = 单块 prompt，在提示词页管理）
})
