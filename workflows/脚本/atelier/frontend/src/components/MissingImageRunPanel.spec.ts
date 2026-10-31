import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MissingImageRunPanel from './MissingImageRunPanel.vue'
import { apiPost } from '../api/client'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/generate_missing/list')) {
      return {
        items: [
          { id: 10, name: '缺图一', category: '组合', steps: 8, cfg_scale: 3, sampler: 'euler', model: 'm', width: 1128, height: 2008 },
          { id: 11, name: '缺图二', category: '', steps: null, cfg_scale: null, sampler: '', model: '', width: null, height: null },
        ],
      }
    }
    if (path.includes('/api/workflows')) {
      return { workflows: [{ path: '/wf/a.json', name: '工作流A' }], default: '/wf/a.json' }
    }
    return {}
  }),
  apiPost: vi.fn(async () => ({ success: true, job_id: 7, count: 2, results: [], errors: [] })),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))

async function mountPanel() {
  const wrapper = mount(MissingImageRunPanel, {
    props: { open: true },
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
      // Modal 用 Teleport 渲染到 body，测试里要 stub 掉才能在 wrapper 内查到
      stubs: { teleport: true },
    },
  })
  await flushPromises()
  return wrapper
}

describe('MissingImageRunPanel 缺图批量补跑', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
  })

  it('列出缺图的提示词', async () => {
    const wrapper = await mountPanel()
    expect(wrapper.findAll('.item').length).toBe(2)
    expect(wrapper.text()).toContain('缺图一')
  })

  it('默认全选', async () => {
    const wrapper = await mountPanel()
    expect(wrapper.text()).toContain('已选 2')
  })

  it('取消勾选后计数变化', async () => {
    const wrapper = await mountPanel()
    await wrapper.findAll('.item input[type=checkbox]')[0].trigger('change')
    await flushPromises()
    expect(wrapper.text()).toContain('已选 1')
  })

  it('提交带上勾选的 prompt_ids 与工作流', async () => {
    const wrapper = await mountPanel()
    await wrapper.findAll('.item input[type=checkbox]')[0].trigger('change')
    await flushPromises()
    const btn = wrapper.findAll('button').find((b) => b.text().includes('补跑'))!
    await btn.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, body] = vi.mocked(apiPost).mock.calls[0]
    expect(path).toBe('/api/generate_missing')
    expect((body as Record<string, unknown>).prompt_ids).toEqual([11])
    expect((body as Record<string, unknown>).workflow_path).toBe('/wf/a.json')
  })
})
