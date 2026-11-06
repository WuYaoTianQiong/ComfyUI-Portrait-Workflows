import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import ComposerView from './ComposerView.vue'
import { apiPost } from '../api/client'
import { useSettings } from '../composables/useSettings'

// happy-dom 没有 EventSource；提交随机组合后会订阅进度，必须给个假的
class FakeEventSource {
  addEventListener() {}
  close() {}
  onerror: (() => void) | null = null
}
vi.stubGlobal('EventSource', FakeEventSource)

/**
 * 测试环境的 `localStorage` 不是可用的 Storage（node 的 `--localstorage-file`
 * 只有一个空壳全局），必须补一份最小实现，否则组合器的会话/画布持久化会静默失败，
 * 「刷新后还在」这类断言也就无从谈起。
 */
const store = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => {
    store.set(key, value)
  },
  removeItem: (key: string) => {
    store.delete(key)
  },
  clear: () => store.clear(),
})

// 碎片夹具可在单个用例里替换（分批加载需要 > 40 条），避免影响其它用例的随机断言
const fixture = vi.hoisted(() => ({
  faces: [
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
  /** 刷新后要能接回来的"上一次任务"（后端 /api/jobs/{id} 的快照形状） */
  job: {
    id: 9,
    status: 'done',
    title: '批量随机组合 (1 组)',
    total: 1,
    done_count: 1,
    items: [
      {
        status: 'done',
        prompt_preview: '【人物面部】正脸，柔和光线',
        seed: 12345,
        images: [{ filename: 'a.png', subfolder: '', type: 'output' }],
      },
    ],
  },
}))

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/jobs/')) {
      // 按 id 返回同形状的快照，标题带上 id 便于断言"列出的是哪几个任务"
      const id = Number(path.split('/api/jobs/')[1])
      return { ...fixture.job, id, title: `批量随机组合 #${id}` }
    }
    if (path.includes('/api/composer/fragments')) {
      return {
        grouped: { 人物面部: fixture.faces },
        fragment_count: fixture.faces.length,
      }
    }
    if (path.includes('/api/categories')) return { categories: [] }
    if (path.includes('/api/tags')) return { tags: [] }
    if (path.includes('/api/templates')) {
      return { templates: [{ id: 1, name: '模板A', fragment_count: 2 }] }
    }
    if (path.includes('/api/workflows')) return { workflows: [], default: '' }
    return {}
  }),
  apiPost: vi.fn(async () => ({ success: true })),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  // 任务结果的缩略图与原图地址（结果中心/灯箱会用到）
  thumbnailUrl: () => '/api/thumb',
  viewUrl: () => '/api/media/image',
}))

const stub = { template: '<div />' }
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: stub },
    { path: '/jobs', component: stub },
  ],
})

async function mountView() {
  const wrapper = mount(ComposerView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }], router],
      stubs: { teleport: true },
    },
  })
  await flushPromises()
  return wrapper
}

describe('ComposerView 自定义碎片 / 复制 / 存为提示词', () => {
  beforeEach(() => {
    vi.mocked(apiPost).mockClear()
    // 组合器自己把画布 / 固定列 / 结果中心写进 localStorage，用例之间必须清干净，
    // 否则上一例留下的"弹窗开着 / 画布有内容"会污染下一例
    for (const key of [
      'pb.session.composer',
      'pb.composerCanvas',
      'pb.composerPinned',
      'pb.lastJob.composer',
      'pb.lastJob.composer.ids',
    ]) {
      store.delete(key)
    }
    // happy-dom 没有剪贴板实现。
    // 注意：不能整个替换 navigator —— happy-dom 的 localStorage 挂在它上面，
    // 换掉之后 localStorage.getItem 就不再是函数了。
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn(async () => undefined) },
      configurable: true,
    })
  })

  it('8 条滚筒每列都有「自定义」入口', async () => {
    const wrapper = await mountView()
    expect(wrapper.findAll('.card.add').length).toBe(8)
    expect(wrapper.findAll('.reel').length).toBe(8)
  })

  it('自定义碎片填入后在该列显示「自」标记', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('.card.add')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.custom-body textarea').exists()).toBe(true)

    await wrapper.find('.custom-body textarea').setValue('自己写的一段')
    const apply = wrapper.findAll('button').find((b) => b.text() === '填入画布')!
    await apply.trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.card.custom.on').length).toBe(1)
    expect(wrapper.text()).toContain('自己写的一段')
  })

  it('自定义碎片存为 prompt（不再写 fragments 表）', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('.card.add')[0].trigger('click')
    await flushPromises()

    await wrapper.find('.custom-body textarea').setValue('自己写的一段')
    const btn = wrapper.findAll('button').find((b) => b.text() === '存为碎片')!
    await btn.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, body] = vi.mocked(apiPost).mock.calls[0]
    expect(path).toBe('/api/prompts')
    expect(String((body as Record<string, unknown>).prompt)).toBe('【人物面部】\n自己写的一段')
  })

  it('结果中心提供「复制」与「存为提示词」', async () => {
    const wrapper = await mountView()
    const resultBtn = wrapper.findAll('button').find((b) => b.text().includes('结果'))!
    await resultBtn.trigger('click')
    await flushPromises()

    const labels = wrapper.findAll('button').map((b) => b.text())
    expect(labels).toContain('复制')
    expect(labels).toContain('存为提示词')
  })

  it('存为提示词把组合结果 POST 到 /api/prompts', async () => {
    const wrapper = await mountView()
    // 先填一个碎片，让画布非空
    await wrapper.findAll('.reel-body .card').at(0)?.trigger('click')
    await flushPromises()

    const resultBtn = wrapper.findAll('button').find((b) => b.text().includes('结果'))!
    await resultBtn.trigger('click')
    await flushPromises()

    vi.stubGlobal('prompt', () => '我的组合')
    const btn = wrapper.findAll('button').find((b) => b.text() === '存为提示词')!
    await btn.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, body] = vi.mocked(apiPost).mock.calls[0]
    expect(path).toBe('/api/prompts')
    expect((body as Record<string, unknown>).name).toBe('我的组合')
    expect(String((body as Record<string, unknown>).prompt)).toContain('【人物面部】')
  })

  it('点整行表头即可锁定/解锁该列', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('.reel-body .card').at(0)?.trigger('click')
    await flushPromises()

    const head = wrapper.findAll('.reel-head')[0]
    await head.trigger('click')
    expect(head.classes()).toContain('on')

    await head.trigger('click')
    expect(head.classes()).not.toContain('on')
  })

  it('点列头定位图标把已选碎片滚到中间，且不会误锁该列', async () => {
    const wrapper = await mountView()
    const body = wrapper.findAll('.reel-body')[0]
    await body.find('.card').trigger('click')
    await flushPromises()

    const on = body.find('.card.on').element as HTMLElement
    const scrollIntoView = vi.fn()
    on.scrollIntoView = scrollIntoView

    const head = wrapper.findAll('.reel-head')[0]
    await head.find('.locate-ico').trigger('click')
    await flushPromises()

    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'center', behavior: 'smooth' })
    expect(head.classes()).not.toContain('on')
  })

  it('双击卡片打开全文弹层', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('.reel-body .card').at(0)?.trigger('dblclick')
    await flushPromises()

    expect(wrapper.text()).toContain('碎片全文')
    expect(wrapper.find('.frag-full').text()).toContain('正脸，柔和光线')
  })

  it('模板库面板列出模板', async () => {
    const wrapper = await mountView()
    const btn = wrapper.findAll('button').find((b) => b.text().includes('模板'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.tpl-row').length).toBe(1)
  })

  it('随机一版只在本地抽，不出图', async () => {
    const wrapper = await mountView()
    const btn = wrapper.findAll('button').find((b) => b.text().includes('随机一版'))!
    await btn.trigger('click')
    await flushPromises()

    // 抽取只改画布，不调用任何提交接口
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.findAll('.card.on').length).toBe(1)
    expect(wrapper.find('.reel-picked').text()).toContain('正脸')
  })

  it('结果中心随机页：改组数后重抽，确认才提交 composed_prompts', async () => {
    useSettings().composerWorkflowPath.value = 'F:/fake.json'
    vi.mocked(apiPost).mockResolvedValueOnce({
      success: true,
      job_id: 1,
      results: [{ index: 0, success: true }],
    } as never)

    const wrapper = await mountView()
    // 默认随机 1 组
    const preview = wrapper.findAll('button').find((b) => b.text().includes('预览'))!
    await preview.trigger('click')
    await flushPromises()

    // 预览阶段没有任何提交
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('结果中心')
    expect(wrapper.findAll('.res-card').length).toBe(1)
    expect(wrapper.find('.res-grid').classes()).toContain('single')
    expect(wrapper.find('.res-text').text()).toContain('【人物面部】')

    // 组数 chips 移到了弹窗里；改成 3 组后重抽
    const chip = wrapper.findAll('.res-chip').find((c) => c.text() === '3 组')!
    await chip.trigger('click')
    const regen = wrapper.findAll('button').find((b) => b.text().includes('重新抽取'))!
    await regen.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.res-card').length).toBe(3)

    const confirm = wrapper.findAll('button').find((b) => b.text().includes('确认出图'))!
    await confirm.trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    const [path, body] = vi.mocked(apiPost).mock.calls[0]
    expect(path).toBe('/api/composer/batch_random_run')
    const combos = (body as Record<string, unknown>).composed_prompts as string[]
    expect(combos.length).toBe(3)
    expect(combos[0]).toContain('【人物面部】')
    // 只改组合器自己那份，提示词页的工作流不受影响
    expect(useSettings().workflowPath.value).toBe('')
    useSettings().composerWorkflowPath.value = ''
  })

  it('碎片列首屏 40 条，滚到列底自动追加下一批', async () => {
    const base = fixture.faces
    fixture.faces = Array.from({ length: 45 }, (_, i) => ({
      prompt_id: i + 1,
      prompt_name: `示例提示词${i + 1}`,
      type: '人物面部',
      content: `面部碎片 ${i + 1}`,
      tags: '',
      source: 'prompt',
      dup_count: 1,
    }))

    // 用可控的 IntersectionObserver：挂载时记录回调，用例里手动模拟"滚到底"
    let onIntersect: ((entries: Array<{ target: Element; isIntersecting: boolean }>) => void) | null =
      null
    class FakeObserver {
      constructor(cb: typeof onIntersect) {
        onIntersect = cb
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal('IntersectionObserver', FakeObserver)

    try {
      const wrapper = await mountView()
      const firstReel = () => wrapper.findAll('.reel')[0]
      const cards = () => firstReel().findAll('.reel-body .card:not(.add)')

      expect(cards().length).toBe(40)
      const more = firstReel().find('.more')
      expect(more.exists()).toBe(true)

      onIntersect!([{ target: more.element, isIntersecting: true }])
      await flushPromises()

      expect(cards().length).toBe(45)
      expect(firstReel().find('.more').exists()).toBe(false)
    } finally {
      fixture.faces = base
    }
  })

  it('刷新后画布与固定列都还在，并重新高亮选中项', async () => {
    const first = await mountView()
    await first.findAll('.reel-body .card').at(0)?.trigger('click')
    await first.findAll('.reel-head')[0].trigger('click') // 锁定第一列
    await flushPromises()
    first.unmount()

    const again = await mountView()

    expect(again.findAll('.card.on').length).toBe(1)
    expect(again.findAll('.reel-head')[0].classes()).toContain('on')
    expect(again.find('.reel-picked').text()).toContain('正脸，柔和光线')
  })

  it('刷新后结果中心仍开着，抽出来的组合还在', async () => {
    const first = await mountView()
    await first.findAll('button').find((b) => b.text().includes('预览'))!.trigger('click')
    await flushPromises()
    expect(first.findAll('.res-card').length).toBe(1)
    first.unmount()

    const again = await mountView()

    // 弹窗没有自己关掉，随机组也不是空的
    expect(again.text()).toContain('结果中心')
    expect(again.findAll('.res-card').length).toBe(1)
    expect(again.find('.res-text').text()).toContain('【人物面部】')
  })

  it('「负面提示词」按钮直接开居中弹窗，而不是角落抽屉', async () => {
    const wrapper = await mountView()
    const btn = wrapper.findAll('button').find((b) => b.text().includes('负面提示词'))!
    await btn.trigger('click')
    await flushPromises()

    const box = wrapper.find('.neg-text')
    expect(box.exists()).toBe(true)
    expect(wrapper.find('.settings-panel').exists()).toBe(false)

    await box.setValue('低清晰度, 水印')
    await flushPromises()
    const saved = JSON.parse(localStorage.getItem('pb.session.composer') ?? '{}')
    expect(saved.negativePrompt).toBe('低清晰度, 水印')
  })

  it('队列模式：上一组还没跑完也能接着提交下一组', async () => {
    useSettings().composerWorkflowPath.value = 'F:/fake.json'
    vi.mocked(apiPost).mockResolvedValue({
      success: true,
      job_id: 1,
      results: [{ index: 0, success: true }],
    } as never)

    const wrapper = await mountView()
    // 画布非空才能点「试跑」
    await wrapper.findAll('.reel-body .card').at(0)?.trigger('click')
    await flushPromises()

    const runBtn = () => wrapper.findAll('button').find((b) => b.text().includes('试跑'))!
    await runBtn().trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledTimes(1)
    // FakeEventSource 不会推终态，等于"任务还在跑"；按钮此时必须已经恢复
    const btn = runBtn()
    expect(btn.attributes('disabled')).toBeUndefined()
    expect(btn.text()).toContain('试跑')
    expect(wrapper.find('.job-state.queue').text()).toContain('1')

    // 接着提交第二组：后端会各自建 job，ComfyUI 排队跑
    await runBtn().trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledTimes(2)

    useSettings().composerWorkflowPath.value = ''
  })

  it('刷新后结果中心仍能看到上一次任务（任务结果页签不再清空）', async () => {
    // 上一次提交记下的 job id（旧格式：单个 id，没有 .ids 列表）
    store.set('pb.lastJob.composer', '9')

    const wrapper = await mountView()
    // 先打开结果中心（页签在弹窗里）
    await wrapper.findAll('button').find((b) => b.text().includes('组合结果'))!.trigger('click')
    await flushPromises()

    // 挂载后按 id 从 /api/jobs/9 取回快照
    const tab = wrapper.findAll('button').find((b) => b.text().includes('任务结果'))!
    expect(tab.text()).toContain('· 1')

    await tab.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.job-card').length).toBe(1)
    expect(wrapper.findAll('.job-row').length).toBe(1)
    expect(wrapper.text()).toContain('批量随机组合')
    expect(wrapper.text()).toContain('正脸，柔和光线')
  })

  it('任务结果列出本次会话的所有任务，并可逐条展开', async () => {
    // 本次会话提交过两个任务（新→旧）
    store.set('pb.lastJob.composer.ids', JSON.stringify([11, 10]))

    const wrapper = await mountView()
    await wrapper.findAll('button').find((b) => b.text().includes('组合结果'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text().includes('任务结果'))!.trigger('click')
    await flushPromises()

    const cards = wrapper.findAll('.job-card')
    expect(cards.length).toBe(2)
    expect(cards[0].text()).toContain('#11')
    expect(cards[1].text()).toContain('#10')
    // 默认只展开最新那条
    expect(wrapper.findAll('.job-row').length).toBe(1)

    await cards[1].find('.job-title').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.job-row').length).toBe(2)
  })
})
