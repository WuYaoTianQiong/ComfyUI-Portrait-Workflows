import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ComposerView from './ComposerView.vue'
import { apiPost } from '../api/client'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/composer/fragments')) {
      return {
        grouped: {
          人物面部: [
            {
              prompt_id: 7,
              prompt_name: '示例提示词',
              type: '人物面部',
              content: '正脸，柔和光线',
              tags: '',
              source: 'prompt',
              dup_count: 1,
            },
          ],
        },
        fragment_count: 1,
      }
    }
    if (path.includes('/api/categories')) return { categories: [] }
    if (path.includes('/api/tags')) return { tags: [] }
    if (path.includes('/api/templates')) return { templates: [] }
    if (path.includes('/api/workflows')) return { workflows: [], default: '' }
    return {}
  }),
  apiPost: vi.fn(async () => ({ success: true })),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))

async function mountView() {
  const wrapper = mount(ComposerView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
      stubs: { teleport: true },
    },
  })
  await flushPromises()
  return wrapper
}

describe('ComposerView 自定义碎片 / 复制 / 存为提示词', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
    // happy-dom 没有剪贴板实现。
    // 注意：不能整个替换 navigator —— happy-dom 的 localStorage 挂在它上面，
    // 换掉之后 localStorage.getItem 就不再是函数了。
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn(async () => undefined) },
      configurable: true,
    })
  })

  it('每个空槽位都有「手写一段」入口', async () => {
    const wrapper = await mountView()
    expect(wrapper.findAll('.slot-empty .slot-remove').length).toBe(8)
  })

  it('自定义碎片填入槽位后打上「自」标记', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('.slot-empty .slot-remove')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.custom-body textarea').exists()).toBe(true)

    await wrapper.find('.custom-body textarea').setValue('自己写的一段')
    const apply = wrapper.findAll('button').find((b) => b.text() === '填入画布')!
    await apply.trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.slot-src.custom').length).toBe(1)
    expect(wrapper.text()).toContain('自己写的一段')
  })

  it('画布头有「复制」与「存为提示词」', async () => {
    const wrapper = await mountView()
    const labels = wrapper.findAll('.canvas-head button').map((b) => b.text())
    expect(labels).toContain('复制')
    expect(labels).toContain('存为提示词')
  })

  it('存为提示词把组合结果 POST 到 /api/prompts', async () => {
    const wrapper = await mountView()
    // 先填一个碎片，让画布非空
    await wrapper.findAll('.frag').at(0)?.trigger('click')
    await flushPromises()

    vi.stubGlobal('prompt', () => '我的组合')
    const btn = wrapper.findAll('.canvas-head button').find((b) => b.text() === '存为提示词')!
    await btn.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, body] = vi.mocked(apiPost).mock.calls[0]
    expect(path).toBe('/api/prompts')
    expect((body as Record<string, unknown>).name).toBe('我的组合')
    expect(String((body as Record<string, unknown>).prompt)).toContain('【人物面部】')
  })
})
