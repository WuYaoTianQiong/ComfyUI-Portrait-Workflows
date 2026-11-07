import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PromptTrialPanel from './PromptTrialPanel.vue'
import { apiGet, apiPost } from '../api/client'
import { useSettings } from '../composables/useSettings'

vi.mock('../api/client', () => ({
  newIdempotencyKey: () => 'test-idem',
  apiPost: vi.fn(async () => ({ success: true, job_id: 42, seed: 12345 })),
  apiGet: vi.fn(async (_path: string) => ({ workflows: [], default: '' })),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  thumbnailUrl: (item: { filename: string }) => `/thumb/${item.filename}`,
}))

/** 测试环境的 localStorage 不完整（只有部分实现），给一个最小可用版。 */
function stubStorage(extra: Record<string, string> = {}) {
  const store: Record<string, string> = { 'pb.workflowPath': '/wf/a.json', ...extra }
  vi.stubGlobal('localStorage', {
    getItem: vi.fn((k: string) => store[k] ?? null),
    setItem: vi.fn((k: string, v: string) => {
      store[k] = String(v)
    }),
    removeItem: vi.fn((k: string) => {
      delete store[k]
    }),
    clear: vi.fn(),
  })
  return store
}

async function mountPanel(props: { promptId?: number | null; promptName?: string } = {}) {
  const wrapper = mount(PromptTrialPanel, {
    props: {
      open: true,
      promptId: props.promptId ?? null,
      promptName: props.promptName ?? '',
    },
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
      stubs: { teleport: true },
    },
  })
  await flushPromises()
  return wrapper
}

function findButton(wrapper: VueWrapper, text: string) {
  return wrapper.findAll('button').find((b) => b.text().includes(text))
}

describe('PromptTrialPanel 临时试跑', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
    vi.mocked(apiGet).mockReset()
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path.startsWith('/api/jobs/')) {
        return {
          id: 42,
          status: 'done',
          total: 1,
          done_count: 1,
          items: [
            {
              seed: 42,
              status: 'done',
              prompt_preview: '预览',
              images: [{ filename: 'trial.png', subfolder: '', type: 'output' }],
            },
          ],
        }
      }
      return { workflows: [], default: '' }
    })
    stubStorage()
    // useSettings 是模块级单例，模块加载时就读过一次 localStorage，
    // 那时还没 stub —— 直接赋值，别指望 localStorage。
    useSettings().workflowPath.value = '/wf/a.json'
  })

  it('打开是空白粘贴框，不预填任何载体文本', async () => {
    const wrapper = await mountPanel({ promptId: 1, promptName: '载体提示词' })
    const input = wrapper.find('.prompt-input')
    expect((input.element as HTMLTextAreaElement).value).toBe('')
  })

  it('空文本不能跑图', async () => {
    const wrapper = await mountPanel()
    const btn = findButton(wrapper, '跑图')!
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('粘贴文本后跑图走 /api/runs/text，默认不关联', async () => {
    const wrapper = await mountPanel({ promptId: 1, promptName: '载体提示词' })
    await wrapper.find('.prompt-input').setValue('从别的网页复制来的提示词')
    await findButton(wrapper, '跑图')!.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, body] = vi.mocked(apiPost).mock.calls[0]
    expect(path).toBe('/api/runs/text')
    expect((body as Record<string, unknown>).prompt).toBe('从别的网页复制来的提示词')
    expect((body as Record<string, unknown>).source_prompt_id).toBe(0)
  })

  it('显式选择关联后带上当前提示词 id', async () => {
    const wrapper = await mountPanel({ promptId: 7, promptName: '要关联的提示词' })
    await wrapper.find('.prompt-input').setValue('外来文本')
    await wrapper.findAll('input[type="radio"]')[1].setValue(true)
    await findButton(wrapper, '跑图')!.trigger('click')
    await flushPromises()

    const body = vi.mocked(apiPost).mock.calls[0][1] as Record<string, unknown>
    expect(body.source_prompt_id).toBe(7)
  })

  it('张数 3 提交 3 次，种子依次 +1', async () => {
    const wrapper = await mountPanel()
    await wrapper.find('.prompt-input').setValue('多张测试')
    await wrapper.findAll('.counts button')[2].trigger('click')
    await wrapper.find('.seed-field input').setValue('100')
    await findButton(wrapper, '跑图')!.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(3)
    const seeds = vi.mocked(apiPost).mock.calls.map(
      (call) => (call[1] as Record<string, unknown>).seed,
    )
    expect(seeds).toEqual([100, 101, 102])
  })

  it('刷新后恢复任务行，存为提示词预填当次全文', async () => {
    stubStorage({
      'pb.lastJob.prompt-trial.ids': '[42]',
      'pb.trialRuns': JSON.stringify({
        42: { prompt: '归档文本', negative_prompt: '负向文本', seed: 42 },
      }),
    })
    const wrapper = await mountPanel()

    expect(wrapper.findAll('.result-row').length).toBe(1)
    const save = wrapper
      .findAll('.result-row button')
      .find((b) => b.text().includes('存为提示词'))!
    expect(save.attributes('disabled')).toBeUndefined()

    await save.trigger('click')
    await flushPromises()

    const promptEditor = wrapper.find('textarea[rows="10"]')
    expect((promptEditor.element as HTMLTextAreaElement).value).toBe('归档文本')
  })
})
