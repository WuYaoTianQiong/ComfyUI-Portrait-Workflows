import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BatchReplaceModal from './BatchReplaceModal.vue'
import { apiGet } from '../api/client'

/** happy-dom 的 localStorage 在某些运行方式下只是空壳，补一份最小实现。 */
const store = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => void store.set(key, value),
  removeItem: (key: string) => void store.delete(key),
  clear: () => store.clear(),
})

const PROMPTS = [
  {
    id: 1,
    name: '有身材的提示词',
    prompt:
      '【人物面部】黑色长发\n\n【人物身材】旧身材\n\n【人物服饰】白色连衣裙\n\n【场景环境】街道',
    seed: 7,
  },
  {
    id: 2,
    name: '也有身材的提示词',
    prompt: '【人物面部】短发\n\n【人物身材】另一个旧身材',
    seed: null,
  },
  {
    id: 3,
    name: '没有身材的提示词',
    prompt: '【人物面部】短发\n\n【人物服饰】旧外套\n\n【场景环境】室内',
    seed: null,
  },
]

const CANDIDATES: Record<string, Array<{
  fragment_id?: number
  prompt_id: number | null
  prompt_name: string
  type: string
  content: string
  source: 'prompt' | 'library'
  dup_count: number
}>> = {
  人物身材: [
    {
      fragment_id: 10,
      prompt_id: null,
      prompt_name: '',
      type: '人物身材',
      content: '统一身材，比例自然',
      source: 'library',
      dup_count: 1,
    },
    {
      fragment_id: undefined,
      prompt_id: 1,
      prompt_name: '有身材的提示词',
      type: '人物身材',
      content: '纤细修长，腰线清晰',
      source: 'prompt',
      dup_count: 3,
    },
  ],
  人物服饰: [
    {
      fragment_id: 20,
      prompt_id: null,
      prompt_name: '',
      type: '人物服饰',
      content: '统一黑裙',
      source: 'library',
      dup_count: 1,
    },
  ],
}

/**
 * `/api/composition/batch_replace` 的替身：按后端语义逐条应用替换清单
 * （空行分块、只换目标块、其余块原样保留、缺失时按各自的 missing 策略）。
 * 组件本身不解析文本，所以这里必须模拟后端。
 */
function fakeBatchReplace(body: {
  texts: Array<{ id: number; text: string }>
  replacements: Array<{ type: string; content: string; missing?: 'skip' | 'append' }>
}) {
  const items = body.texts.map((t) => {
    let text = String(t.text)
    const outcomes: Array<{
      type: string
      old_content: string
      action: 'replaced' | 'appended' | 'skipped'
    }> = []
    for (const spec of body.replacements) {
      let oldContent = ''
      let hit = false
      const blocks = text.split(/\n\s*\n/)
      const out = blocks.map((block) => {
        const matched = block.match(/^\s*【([^】]+)】\s*([\s\S]*)$/)
        if (matched && matched[1].trim() === spec.type) {
          oldContent = matched[2].trim()
          hit = true
          return `【${spec.type}】\n${spec.content.trim()}`
        }
        return block
      })
      if (hit) {
        text = out.join('\n\n').trim()
        outcomes.push({ type: spec.type, old_content: oldContent, action: 'replaced' })
      } else if (spec.missing === 'append' && spec.content.trim()) {
        const base = text.trim()
        text = base
          ? `${base}\n\n【${spec.type}】\n${spec.content.trim()}`
          : `【${spec.type}】\n${spec.content.trim()}`
        outcomes.push({ type: spec.type, old_content: '', action: 'appended' })
      } else {
        outcomes.push({ type: spec.type, old_content: '', action: 'skipped' })
      }
    }
    const changed = outcomes.some((o) => o.action !== 'skipped')
    return { id: t.id, replaced: changed ? text : null, outcomes }
  })
  return { items }
}

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string, params?: Record<string, unknown>) => {
    if (path.includes('/api/prompts/full')) {
      const ids = params?.ids ? String(params.ids).split(',') : null
      const items = ids
        ? PROMPTS.filter((p) => ids.includes(String(p.id)))
        : PROMPTS
      return { items, total: items.length }
    }
    if (path.includes('/api/composer/fragments')) {
      const type = String(params?.fragment_type ?? '')
      return {
        grouped: type ? { [type]: CANDIDATES[type] ?? [] } : CANDIDATES,
        fragment_count: (CANDIDATES[type] ?? []).length,
      }
    }
    if (path === '/api/workflows') {
      return {
        workflows: [
          { path: 'F:/wf.json', name: '主工作流' },
          { path: 'F:/wf-fast.json', name: '快速工作流' },
        ],
        default: 'F:/wf.json',
      }
    }
    return {}
  }),
  apiPost: vi.fn(async (path: string, body?: unknown) => {
    if (path === '/api/composition/batch_replace') {
      return fakeBatchReplace(body as Parameters<typeof fakeBatchReplace>[0])
    }
    return {}
  }),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))

async function mountModal(selectedIds: number[] = []) {
  const wrapper = mount(BatchReplaceModal, {
    props: {
      open: true,
      search: '',
      categoryId: null,
      tagIds: [],
      tagMatch: 'all',
      fragmentTypes: [],
      fragmentMatch: 'has',
      selectedIds,
      workflowPath: 'F:/wf.json',
    },
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
      stubs: { teleport: true },
    },
  })
  await flushPromises()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountModal>>

/** 添加一个类型，并从候选列表点一条，进入可预览状态。 */
async function prepare(wrapper: Wrapper, type = '人物身材') {
  await wrapper.find('.add-type').setValue(type)
  await flushPromises()
  await wrapper.find('.cand-row').trigger('click')
  await flushPromises()
  await flushPromises()
}

function button(wrapper: Wrapper, text: string) {
  return wrapper.findAll('button').find((b) => b.text() === text)!
}

describe('BatchReplaceModal', () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockClear()
    localStorage.clear()
  })

  it('添加类型后候选碎片来自提示词与碎片库，点一条就填入替换内容', async () => {
    const wrapper = await mountModal()
    await prepare(wrapper)

    expect(wrapper.findAll('.cand-row').length).toBe(2)
    expect(wrapper.find('.cand-row').classes()).toContain('on')
    expect(wrapper.text()).toContain('来自提示词与碎片库')
    expect((wrapper.find('.content-input').element as HTMLTextAreaElement).value).toBe(
      '统一身材，比例自然',
    )
    expect(wrapper.findAll('.row').length).toBe(2)
    expect(wrapper.find('.row .old').text()).toBe('旧身材')
    expect(wrapper.text()).toContain('未命中 1')
  })

  it('候选检索能搜到提示词里出现过的具体碎片', async () => {
    const wrapper = await mountModal()
    await wrapper.find('.add-type').setValue('人物身材')
    await flushPromises()
    expect(wrapper.findAll('.cand-row').length).toBe(2)

    await wrapper.find('.cand-search').setValue('纤细')
    expect(wrapper.findAll('.cand-row').length).toBe(1)
    expect(wrapper.find('.cand-row .cand-content').text()).toContain('纤细修长')

    await wrapper.find('.cand-row').trigger('click')
    expect((wrapper.find('.content-input').element as HTMLTextAreaElement).value).toBe(
      '纤细修长，腰线清晰',
    )
  })

  it('多类型清单一次预览，每条提示词按各自命中的类型展示差异', async () => {
    const wrapper = await mountModal()
    await prepare(wrapper)
    await prepare(wrapper, '人物服饰')

    expect(wrapper.findAll('.chip').length).toBe(2)
    expect(wrapper.findAll('.row').length).toBe(3)
    // p1 身材+服饰、p2 身材、p3 服饰 => 替换 4 处；p2 缺服饰、p3 缺身材 => 跳过 2 处
    expect(wrapper.text()).toContain('替换 4 处')
    expect(wrapper.text()).toContain('跳过 2 处')

    const first = wrapper.findAll('.row')[0]
    expect(first.findAll('.old').map((n) => n.text())).toEqual(['旧身材', '白色连衣裙'])
    expect(first.findAll('.diff-label').map((n) => n.text())).toContain('原【人物服饰】')

    await button(wrapper, '替换 4 处并出图').trigger('click')
    const payload = wrapper.emitted('submit')![0][0] as {
      types: string[]
      items: Array<{ promptId: number; seed: number; promptOverride: string }>
    }
    expect(payload.types).toEqual(['人物身材', '人物服饰'])
    const firstItem = payload.items.find((i) => i.promptId === 1)!
    expect(firstItem.promptOverride).toContain('【人物身材】\n统一身材，比例自然')
    expect(firstItem.promptOverride).toContain('【人物服饰】\n统一黑裙')
    expect(firstItem.promptOverride).not.toContain('旧身材')
    expect(firstItem.promptOverride).not.toContain('白色连衣裙')
  })

  it('范围勾选优先：左侧勾选 1 条时只处理这一条，可切回当前筛选', async () => {
    const wrapper = await mountModal([1])
    expect(button(wrapper, '已勾选 1 条').classes()).toContain('on')

    await prepare(wrapper)
    expect(wrapper.findAll('.row').length).toBe(1)
    expect(wrapper.find('.row .name').text()).toBe('有身材的提示词')
    expect(vi.mocked(apiGet)).toHaveBeenCalledWith('/api/prompts/full', { ids: '1' })

    await button(wrapper, '当前筛选全部').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.row').length).toBe(2)
  })

  it('范围勾选优先：上次记住的「当前筛选全部」不覆盖本次勾选', async () => {
    localStorage.setItem('pb.batchReplace', JSON.stringify({ rows: [] }))
    const wrapper = await mountModal([1])
    expect(button(wrapper, '已勾选 1 条').classes()).toContain('on')
    expect(button(wrapper, '当前筛选全部').classes()).not.toContain('on')

    await prepare(wrapper)
    expect(wrapper.findAll('.row').length).toBe(1)
    expect(wrapper.find('.row .name').text()).toBe('有身材的提示词')
  })

  it('列表支持全选 / 取消全选 / 反选，且检索只作用于当前结果', async () => {
    const wrapper = await mountModal()
    await prepare(wrapper)
    expect(wrapper.text()).toContain('已选 2 / 2')

    await button(wrapper, '取消全选').trigger('click')
    expect(wrapper.text()).toContain('已选 0 / 2')
    expect(wrapper.find('.btn.primary').text()).toBe('开始出图')
    expect(wrapper.find('.btn.primary').attributes('disabled')).toBeDefined()

    await button(wrapper, '全选').trigger('click')
    expect(wrapper.text()).toContain('已选 2 / 2')
    expect(wrapper.find('.btn.primary').text()).toBe('替换 2 处并出图')

    await wrapper.find('.prompt-search').setValue('也有身材')
    expect(wrapper.findAll('.row').length).toBe(1)
    await button(wrapper, '反选').trigger('click')
    expect(wrapper.text()).toContain('已选 1 / 2')
    expect(wrapper.text()).toContain('可见 1')
    expect(wrapper.text()).toContain('隐藏 1')
  })

  it('提交时只带替换后的文本和原提示词参数，不写回库', async () => {
    const wrapper = await mountModal()
    await prepare(wrapper)

    await button(wrapper, '替换 2 处并出图').trigger('click')

    const payload = wrapper.emitted('submit')![0][0] as {
      types: string[]
      items: Array<{ promptId: number; seed: number; promptOverride: string }>
    }
    expect(payload.types).toEqual(['人物身材'])
    expect(payload.items.length).toBe(2)
    expect(payload.items[0].promptId).toBe(1)
    expect(payload.items[0].seed).toBe(7)
    expect(payload.items[0].promptOverride).toContain('【人物身材】\n统一身材，比例自然')
    expect(payload.items[0].promptOverride).toContain('【场景环境】街道')
    expect(payload.items[0].promptOverride).not.toContain('旧身材')
  })

  it('缺少目标类型时可选择追加，而不是只跳过', async () => {
    const wrapper = await mountModal()
    await wrapper.find('.add-type').setValue('人物身材')
    await flushPromises()
    await wrapper.findAll('.missing-seg button').find((b) => b.text() === '在末尾追加')!.trigger('click')
    await wrapper.find('.cand-row').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(wrapper.findAll('.row').length).toBe(3)
    expect(wrapper.findAll('.append-tag').length).toBe(1)
    expect(wrapper.text()).toContain('追加 1 处')
    const appendedRow = wrapper.findAll('.row').find((r) => r.find('.append-tag').exists())!
    expect(appendedRow.find('.diff-note').text()).toContain('原提示词没有【人物身材】')
    expect(button(wrapper, '替换 2 · 追加 1 处并出图')).toBeTruthy()
  })

  it('可以移除清单里的某一类，移除后不再参与预览', async () => {
    const wrapper = await mountModal()
    await prepare(wrapper)
    await prepare(wrapper, '人物服饰')
    expect(wrapper.findAll('.chip').length).toBe(2)

    await wrapper.findAll('.chip')[1].find('.chip-x').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(wrapper.findAll('.chip').length).toBe(1)
    expect(wrapper.text()).toContain('替换 2 处')
  })

  it('弹窗内可直接切换出图工作流，提交时带上所选路径', async () => {
    const wrapper = await mountModal()
    await prepare(wrapper)

    await wrapper.find('.wf-trigger').trigger('click')
    const options = wrapper.findAll('.wf-option')
    expect(options.length).toBe(2)
    await options.find((o) => o.text().includes('快速工作流'))!.trigger('click')
    expect(wrapper.find('.wf-trigger').text()).toContain('快速工作流')

    await button(wrapper, '替换 2 处并出图').trigger('click')
    const payload = wrapper.emitted('submit')![0][0] as { workflowPath: string }
    expect(payload.workflowPath).toBe('F:/wf-fast.json')
  })

  it('再次打开保留上次的替换清单与各类型的追加策略', async () => {
    const first = await mountModal()
    await prepare(first)
    await first.findAll('.missing-seg button').find((b) => b.text() === '在末尾追加')!.trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 350))
    first.unmount()

    const second = await mountModal()
    expect(second.findAll('.chip').length).toBe(1)
    expect((second.find('.type-select').element as HTMLSelectElement).value).toBe('人物身材')
    expect((second.find('.content-input').element as HTMLTextAreaElement).value).toBe(
      '统一身材，比例自然',
    )
    expect(
      second.findAll('.missing-seg button').find((b) => b.text() === '在末尾追加')!.classes(),
    ).toContain('on')
  })
})
