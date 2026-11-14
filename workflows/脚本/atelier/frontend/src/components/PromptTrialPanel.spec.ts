import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PromptTrialPanel from './PromptTrialPanel.vue'
import { apiGet, apiPost } from '../api/client'
import { useSettings } from '../composables/useSettings'

vi.mock('../api/client', () => ({
  newIdempotencyKey: () => 'test-idem',
  apiPost: vi.fn(async () => ({ success: true, job_id: 42, seed: 12345, linked: 1 })),
  apiGet: vi.fn(async () => ({ workflows: [], default: '' })),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  thumbnailUrl: (item: { filename: string }) => `/thumb/${item.filename}`,
  viewUrl: (item: { filename: string }) => `/view/${item.filename}`,
}))

function wf(path: string, name: string) {
  return {
    path,
    name,
    image_slots: 0,
    caps: { prompt: true, negative: false, negative_effective: false, negative_cfg: null, quality: true, orientation: true },
    params: {
      quality_mode: 'scale',
      orientation_mode: 'swap',
      default_ratio: '2:3',
      aspect_ratios: ['2:3', '3:2', '9:16'],
    },
    size_preview: {
      '0.5x': { '2:3': { width: 512, height: 768 }, '3:2': { width: 768, height: 512 } },
      '1.0x': { '2:3': { width: 1024, height: 1536 }, '3:2': { width: 1536, height: 1024 } },
      '1.25x': { '2:3': { width: 1280, height: 1920 }, '3:2': { width: 1920, height: 1280 } },
    },
  }
}

const WORKFLOWS = [wf('/wf/a.json', 'A_文生图.json'), wf('/wf/b.json', 'B_文生图.json')]
const EDIT_WF = { ...wf('/wf/edit.json', '编辑.json'), image_slots: 1 }

/** 测试环境的 localStorage 不完整，给一个最小可用版。 */
function stubStorage(extra: Record<string, string> = {}) {
  const store: Record<string, string> = {
    'pb.workflowPath': '/wf/a.json',
    'pb.trialMatrix': JSON.stringify({ enabled: true, paths: ['/wf/a.json'], align: 'native' }),
    ...extra,
  }
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
    props: { open: true, promptId: props.promptId ?? null, promptName: props.promptName ?? '' },
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

function bodies() {
  return vi.mocked(apiPost).mock.calls
    .filter((c) => c[0] === '/api/runs/text')
    .map((c) => c[1] as Record<string, unknown>)
}

describe('PromptTrialPanel 试跑工作台', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
    vi.mocked(apiGet).mockReset()
    vi.mocked(apiGet).mockImplementation(async (path: string) => {
      if (path.startsWith('/api/jobs/')) {
        return {
          id: 42, status: 'done', total: 1, done_count: 1, job_type: 'single',
          created_at: '', updated_at: '', title: '',
          items: [{
            seed: 100, status: 'done', prompt_preview: '预览',
            images: [{ filename: 'trial.png', subfolder: '', type: 'output' }],
          }],
        }
      }
      if (path.startsWith('/api/images')) {
        return { items: [{ id: 555, filename: 'trial.png', subfolder: '' }], total: 1 }
      }
      return { workflows: [...WORKFLOWS, EDIT_WF], default: '/wf/a.json' }
    })
    stubStorage()
    // useSettings 是模块级单例，模块加载时就读过一次 localStorage，直接赋值。
    useSettings().workflowPath.value = '/wf/a.json'
  })

  it('是上排文本+参数、下排结果通栏的工作台', async () => {
    const wrapper = await mountPanel({ promptId: 1, promptName: '载体提示词' })
    expect(wrapper.find('.trial-grid').exists()).toBe(true)
    expect(wrapper.find('.pane-text .big-text').exists()).toBe(true)
    expect(wrapper.find('.trial-grid > .controls').exists()).toBe(true)
    expect(wrapper.find('.trial-grid > .results').exists()).toBe(true)
    expect((wrapper.find('.big-text').element as HTMLTextAreaElement).value).toBe('')
  })

  it('空文本不能跑图', async () => {
    const wrapper = await mountPanel()
    expect(findButton(wrapper, '跑')!.attributes('disabled')).toBeDefined()
  })

  it('粘贴文本后走 /api/runs/text，默认不关联载体', async () => {
    const wrapper = await mountPanel({ promptId: 1, promptName: '载体提示词' })
    await wrapper.find('.big-text').setValue('从别的网页复制来的提示词')
    await wrapper.findAll('.counts button')[0].trigger('click')
    await findButton(wrapper, '跑')!.trigger('click')
    await flushPromises()

    const sent = bodies()
    expect(sent).toHaveLength(1)
    expect(sent[0].prompt).toBe('从别的网页复制来的提示词')
    expect(sent[0].source_prompt_id).toBe(0)
  })

  it('显式选择关联后带上当前提示词 id', async () => {
    const wrapper = await mountPanel({ promptId: 7, promptName: '要关联的提示词' })
    await wrapper.find('.big-text').setValue('外来文本')
    await wrapper.findAll('.more-pop input[type="radio"]')[1].setValue(true)
    await wrapper.findAll('.counts button')[0].trigger('click')
    await findButton(wrapper, '跑')!.trigger('click')
    await flushPromises()

    expect(bodies()[0].source_prompt_id).toBe(7)
  })

  it('多工作流：2 个流 × 2 张 = 4 次提交，各带自己的工作流且同种子', async () => {
    stubStorage({
      'pb.trialMatrix': JSON.stringify({ enabled: true, paths: ['/wf/a.json', '/wf/b.json'], align: 'native' }),
    })
    const wrapper = await mountPanel()
    await wrapper.find('.big-text').setValue('横评文本')
    await wrapper.find('.mini-field.seed input').setValue('20261112')
    await findButton(wrapper, '跑')!.trigger('click')
    await flushPromises()

    const sent = bodies()
    expect(sent).toHaveLength(4)
    expect(new Set(sent.map((b) => b.workflow_path))).toEqual(new Set(['/wf/a.json', '/wf/b.json']))
    // 同种子：每个工作流的第 1 张都用基准种子，第 2 张 +1
    expect(sent.filter((b) => b.seed === 20261112)).toHaveLength(2)
    expect(sent.filter((b) => b.seed === 20261113)).toHaveLength(2)
  })

  it('张数 3 时种子依次 +1', async () => {
    const wrapper = await mountPanel()
    await wrapper.find('.big-text').setValue('多张测试')
    await wrapper.findAll('.counts button')[2].trigger('click')
    await wrapper.find('.mini-field.seed input').setValue('100')
    await findButton(wrapper, '跑')!.trigger('click')
    await flushPromises()

    expect(bodies().map((b) => b.seed)).toEqual([100, 101, 102])
  })

  it('逐流参数：每个勾选的工作流各自控制比例与分辨率', async () => {
    stubStorage({
      'pb.trialMatrix': JSON.stringify({ enabled: true, paths: ['/wf/a.json', '/wf/b.json'], align: 'native' }),
    })
    const wrapper = await mountPanel()
    const rows = wrapper.findAll('.flow-row')
    expect(rows).toHaveLength(2)

    // 第二个流改成 3:2 + 0.5x，第一个保持默认
    await rows[1].find('.wf-param-ratio').setValue('3:2')
    await flushPromises()
    // 比例变化会重排画质选项，必须重新取节点，旧 wrapper 可能已脱离文档
    const bRow = wrapper.findAll('.flow-row')[1]
    await bRow.find('.wf-param-quality').setValue('0.5x')
    await wrapper.find('.big-text').setValue('逐流参数')
    await findButton(wrapper, '跑')!.trigger('click')
    await flushPromises()

    const sent = bodies()
    const b = sent.filter((s) => s.workflow_path === '/wf/b.json')
    const a = sent.filter((s) => s.workflow_path === '/wf/a.json')
    expect(new Set(b.map((s) => s.aspect_ratio))).toEqual(new Set(['3:2']))
    expect(new Set(b.map((s) => s.quality))).toEqual(new Set(['0.5x']))
    expect(new Set(a.map((s) => s.aspect_ratio))).toEqual(new Set(['2:3']))
    expect(new Set(a.map((s) => s.quality))).toEqual(new Set(['1.0x']))

    // 比例/画质按工作流记忆（模块级缓存），还原以免污染后续用例
    const restore = wrapper.findAll('.flow-row')[1]
    await restore.find('.wf-param-ratio').setValue('2:3')
    await flushPromises()
    await wrapper.findAll('.flow-row')[1].find('.wf-param-quality').setValue('1.0x')
  })

  it('需要喂图的编辑类工作流在选择器里置灰', async () => {
    const wrapper = await mountPanel()
    await wrapper.find('.wf-trigger').trigger('click')
    await flushPromises()
    const blocked = wrapper.findAll('.wf-option.blocked')
    expect(blocked.length).toBe(1)
    expect(blocked[0].text()).toContain('输入图')
  })

  it('文本落盘，重开还在', async () => {
    const store = stubStorage()
    const wrapper = await mountPanel()
    await wrapper.find('.big-text').setValue('要留着的文本')
    await flushPromises()
    expect(JSON.parse(store['pb.trialDraft']).prompt).toBe('要留着的文本')
    wrapper.unmount()

    const again = await mountPanel()
    expect((again.find('.big-text').element as HTMLTextAreaElement).value).toBe('要留着的文本')
  })

  it('出好图后「存为提示词」可点，并预填当次全文', async () => {
    stubStorage({
      'pb.lastJob.prompt-trial.ids': '[42]',
      'pb.matrixBatch.trial': JSON.stringify({
        baseSeed: 100, lock: true, count: 1,
        cells: [{ path: '/wf/a.json', col: 0, seed: 100, tier: '1.0x', width: 1024, height: 1536, jobId: 42 }],
      }),
      'pb.trialDraft': JSON.stringify({ prompt: '归档文本', negative: '负向文本' }),
    })
    const wrapper = await mountPanel()
    await flushPromises()

    const save = findButton(wrapper, '存为提示词')!
    expect(save.attributes('disabled')).toBeUndefined()
    await save.trigger('click')
    await flushPromises()

    const editor = wrapper.findAll('textarea').find((t) => (t.element as HTMLTextAreaElement).value === '归档文本')
    expect(editor).toBeTruthy()
  })

  it('存为提示词后把整批图认领到新提示词', async () => {
    stubStorage({
      'pb.lastJob.prompt-trial.ids': '[42]',
      'pb.matrixBatch.trial': JSON.stringify({
        baseSeed: 100, lock: true, count: 1,
        cells: [{ path: '/wf/a.json', col: 0, seed: 100, tier: '1.0x', width: 1024, height: 1536, jobId: 42 }],
      }),
      'pb.trialDraft': JSON.stringify({ prompt: '归档文本', negative: '' }),
    })
    const wrapper = await mountPanel()
    await flushPromises()

    await findButton(wrapper, '存为提示词')!.trigger('click')
    await flushPromises()
    wrapper.findComponent({ name: 'PromptCreateModal' }).vm.$emit('created', 999)
    await flushPromises()

    const link = vi.mocked(apiPost).mock.calls.find((c) => c[0] === '/api/images/link_prompt')
    expect(link).toBeTruthy()
    expect(link![1]).toEqual({ image_ids: [555], prompt_id: 999 })
    expect(wrapper.emitted('created')?.[0]).toEqual([999])
  })
})
