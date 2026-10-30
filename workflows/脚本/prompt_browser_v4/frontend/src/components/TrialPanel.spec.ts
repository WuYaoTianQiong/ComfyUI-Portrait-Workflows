import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import TrialPanel from './TrialPanel.vue'
import { apiPost } from '../api/client'
import { useSettings } from '../composables/useSettings'

vi.mock('../api/client', () => ({
  apiPost: vi.fn(async () => ({ success: true, job_id: 42 })),
  apiGet: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))

/** 测试环境的 localStorage 不完整（只有部分实现），给一个最小可用版。 */
function stubStorage() {
  vi.stubGlobal('localStorage', {
    getItem: vi.fn((k: string) => (k === 'pb.workflowPath' ? '/wf/a.json' : null)),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
  })
}

async function mountPanel() {
  const wrapper = mount(TrialPanel, {
    props: {
      open: true,
      prompt: '一张测试图片的提示词',
      negativePrompt: '',
      promptId: 1,
    },
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
      stubs: { teleport: true },
    },
  })
  await flushPromises()
  return wrapper
}

describe('TrialPanel 试跑 / 变体', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
    stubStorage()
    // useSettings 是模块级单例，模块加载时就读过一次 localStorage，
    // 那时还没 stub —— 直接赋值，别指望 localStorage。
    useSettings().workflowPath.value = '/wf/a.json'
  })

  it('试跑调 /api/run_text 且带上当前提示词', async () => {
    const wrapper = await mountPanel()
    const btn = wrapper.findAll('button').find((b) => b.text().includes('试跑一张'))!
    await btn.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, body] = vi.mocked(apiPost).mock.calls[0]
    expect(path).toBe('/api/run_text')
    expect((body as Record<string, unknown>).prompt).toBe('一张测试图片的提示词')
  })

  it('变体按张数提交多次', async () => {
    const wrapper = await mountPanel()
    await wrapper.findAll('.counts button')[2].trigger('click')

    const btn = wrapper.findAll('button').find((b) => b.text().includes('张变体'))!
    await btn.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(3)
  })

  it('试跑记录写进日志', async () => {
    const wrapper = await mountPanel()
    const btn = wrapper.findAll('button').find((b) => b.text().includes('试跑一张'))!
    await btn.trigger('click')
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.log-row').length).toBe(1)
  })
})