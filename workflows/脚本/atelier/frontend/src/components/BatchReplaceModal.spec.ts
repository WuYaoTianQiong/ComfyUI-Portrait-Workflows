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
    prompt: '【人物面部】黑色长发\n\n【人物身材】旧身材\n\n【场景环境】街道',
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
    prompt: '【人物面部】短发\n\n【场景环境】室内',
    seed: null,
  },
]

const CANDIDATES = [
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
]

/**
 * `/api/composition/batch_replace` 的替身：按后端的语义（空行分块、只换目标块、
 * 其余块原样保留、没有该块时 replaced=null）算一遍。组件本身已经不解析文本了，
 * 所以这里必须模拟后端，而不是复用前端代码。
 */
function fakeBatchReplace(body: {
  texts: Array<{ id: number; text: string }>
  type: string
  content: string
  missing?: 'skip' | 'append'
}) {
  const items = body.texts.map((t) => {
    let oldContent = ''
    let hit = false
    const blocks = String(t.text).split(/\n\s*\n/)
    const out = blocks.map((block) => {
      const matched = block.match(/^\s*【([^】]+)】\s*([\s\S]*)$/)
      if (matched && matched[1].trim() === body.type) {
        oldContent = matched[2].trim()
        hit = true
        return `【${body.type}】\n${body.content}`
      }
      return block
    })
    if (!hit && body.missing === 'append' && body.content.trim()) {
      const base = String(t.text).trim()
      return {
        id: t.id,
        old_content: '',
        replaced: base
          ? `${base}\n\n【${body.type}】\n${body.content}`
          : `【${body.type}】\n${body.content}`,
        action: 'appended',
      }
    }
    return {
      id: t.id,
      old_content: oldContent,
      replaced: hit ? out.join('\n\n').trim() : null,
      action: hit ? 'replaced' : 'skipped',
    }
  })
  return { items, skipped: items.filter((i) => i.action === 'skipped').length }
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
      return { grouped: { 人物身材: CANDIDATES }, fragment_count: CANDIDATES.length }
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
      quality: '4K',
      orientation: 'portrait',
      caps: { prompt: true, negative: true, quality: true, orientation: true },
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

/** 选类型 + 从候选列表点一条，进入可预览状态（预览要等后端的批量替换返回）。 */
async function prepare(wrapper: Wrapper) {
  await wrapper.find('.type-select').setValue('人物身材')
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

  it('候选碎片来自提示词与碎片库，点一条就填入替换内容', async () => {
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
    expect(wrapper.text()).toContain('跳过 1 条')
  })

  it('候选检索能搜到提示词里出现过的具体碎片', async () => {
    const wrapper = await mountModal()
    await wrapper.find('.type-select').setValue('人物身材')
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

  it('列表支持全选 / 取消全选 / 反选，且检索只作用于当前结果', async () => {
    const wrapper = await mountModal()
    await prepare(wrapper)
    expect(wrapper.text()).toContain('已选 2 / 2')

    await button(wrapper, '取消全选').trigger('click')
    expect(wrapper.text()).toContain('已选 0 / 2')
    expect(button(wrapper, '替换并出图 0 条').attributes('disabled')).toBeDefined()

    await button(wrapper, '全选').trigger('click')
    expect(wrapper.text()).toContain('已选 2 / 2')

    await wrapper.find('.prompt-search').setValue('也有身材')
    expect(wrapper.findAll('.row').length).toBe(1)
    await button(wrapper, '反选').trigger('click')
    expect(wrapper.text()).toContain('已选 1 / 2')
  })

  it('提交时只带替换后的文本和原提示词参数，不写回库', async () => {
    const wrapper = await mountModal()
    await prepare(wrapper)

    await button(wrapper, '替换并出图 2 条').trigger('click')

    const payload = wrapper.emitted('submit')![0][0] as {
      type: string
      items: Array<{ promptId: number; seed: number; promptOverride: string }>
    }
    expect(payload.type).toBe('人物身材')
    expect(payload.items.length).toBe(2)
    expect(payload.items[0].promptId).toBe(1)
    expect(payload.items[0].seed).toBe(7)
    expect(payload.items[0].promptOverride).toContain('【人物身材】\n统一身材，比例自然')
    expect(payload.items[0].promptOverride).toContain('【场景环境】街道')
    expect(payload.items[0].promptOverride).not.toContain('旧身材')
  })

  it('缺少目标类型时可选择追加，而不是只跳过', async () => {
    const wrapper = await mountModal()
    await wrapper.find('.type-select').setValue('人物身材')
    await wrapper.findAll('.missing-seg button').find((b) => b.text() === '追加')!.trigger('click')
    await wrapper.find('.cand-row').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(wrapper.findAll('.row').length).toBe(3)
    expect(wrapper.findAll('.append-tag').length).toBe(1)
    expect(wrapper.text()).toContain('追加 1')
    const appendedRow = wrapper.findAll('.row').find((r) => r.find('.append-tag').exists())!
    expect(appendedRow.find('.old').text()).toContain('缺少该类型')
    expect(button(wrapper, '替换/追加并出图 3 条')).toBeTruthy()
  })

  it('再次打开保留上次的类型、替换内容与追加策略', async () => {
    const first = await mountModal()
    await prepare(first)
    await first.findAll('.missing-seg button').find((b) => b.text() === '追加')!.trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 350))
    first.unmount()

    const second = await mountModal()
    expect((second.find('.type-select').element as HTMLSelectElement).value).toBe('人物身材')
    expect((second.find('.content-input').element as HTMLTextAreaElement).value).toBe(
      '统一身材，比例自然',
    )
    expect(
      second.findAll('.missing-seg button').find((b) => b.text() === '追加')!.classes(),
    ).toContain('on')
  })
})
