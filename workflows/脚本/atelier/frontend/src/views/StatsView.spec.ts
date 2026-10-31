import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import StatsView from './StatsView.vue'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/system/stats')) {
      return {
        prompt_count: 331,
        history_count: 14,
        job_count: 144,
        fragment_count: 6,
        top_tags: [
          { name: '女性', count: 175, color: '#ff0000' },
          { name: '古风', count: 59, color: '#00ff00' },
        ],
      }
    }
    if (path.includes('/api/images/facets')) {
      return {
        source: { local: 6, comfyui_sync: 3 },
        date: {},
        model: {},
        orientation: { 竖图: 6, 横图: 2 },
      }
    }
    return {}
  }),
}))

async function mountView() {
  const wrapper = mount(StatsView, {
    global: { plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]] },
  })
  await flushPromises()
  return wrapper
}

describe('StatsView 统计页', () => {
  it('展示总量卡片', async () => {
    const wrapper = await mountView()
    const nums = wrapper.findAll('.card .num').map((n) => n.text())
    expect(nums).toContain('331')
    expect(nums).toContain('14')
  })

  it('热门标签带使用数', async () => {
    const wrapper = await mountView()
    expect(wrapper.findAll('.tag').length).toBe(2)
    expect(wrapper.findAll('.tag')[0].text()).toContain('175')
  })

  it('来源分布按数量降序', async () => {
    const wrapper = await mountView()
    const names = wrapper.findAll('.panel')[1].findAll('.bar-name').map((n) => n.text())
    expect(names[0]).toContain('本机出图')
    expect(names[1]).toContain('ComfyUI 同步')
  })
})
