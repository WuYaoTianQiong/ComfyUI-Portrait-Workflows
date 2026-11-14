import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Lightbox from './Lightbox.vue'
import Modal from './Modal.vue'
import { apiPost } from '../api/client'
import type { HistoryItem } from '../api/types'

enableAutoUnmount(afterEach)

const { routerPush } = vi.hoisted(() => ({ routerPush: vi.fn() }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('../api/client', () => ({
  viewUrl: (item: { filename: string }) => '/api/media/image?filename=' + item.filename,
  thumbnailUrl: (item: { filename: string }) => '/api/thumb?filename=' + item.filename,
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/reference/resolve')) {
      return { found: true, library: 'portrait', item_id: 'p1', name: '测试', tab: 'portrait', q: 'p1' }
    }
    if (path.includes('/api/prompts/')) {
      return { prompt: '库里的当前正文', negative_prompt: '库负面' }
    }
    return { run: {} }
  }),
  apiPost: vi.fn(async () => ({ success: true, path: 'a.png' })),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

/** happy-dom 的 localStorage 不完整，这里补一份最小实现（刷新恢复用例需要）。 */
const store = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => {
    store.set(key, value)
  },
  removeItem: (key: string) => {
    store.delete(key)
  },
})

function item(id: number, filename: string): HistoryItem {
  return {
    id,
    job_id: null,
    prompt_id: null,
    comfyui_prompt_id: null,
    filename,
    subfolder: '',
    img_type: 'output',
    view_url: '',
    is_favorite: false,
    missing: false,
    width: null,
    height: null,
    file_size: null,
    created_at: '2026-10-30 10:00:00',
    captured_at: '2026-10-30 10:00:00',
    source: 'local',
    prompt_name: 'p',
    prompt_params: null,
    categories: [],
    tags: [],
  }
}

const ITEMS = [item(1, 'a.png'), item(2, 'b.png'), item(3, 'c.png')]

function press(key: string) {
  window.dispatchEvent(new KeyboardEvent('keydown', { key }))
}

describe('Lightbox', () => {
  it('显示当前序号与总数', () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
    expect(wrapper.find('.pos').text()).toBe('1 / 3')
  })

  it('按 → 翻到下一张', async () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
    press('ArrowRight')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:index')?.[0]).toEqual([1])
  })

  it('按 ← 翻到上一张', async () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 2 } })
    press('ArrowLeft')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:index')?.[0]).toEqual([1])
  })

  it('第一张按 ← 不越界', async () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
    press('ArrowLeft')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:index')).toBeUndefined()
  })

  it('最后一张按 → 不越界', async () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 2 } })
    press('ArrowRight')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:index')).toBeUndefined()
  })

  it('按 Esc 关闭', async () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
    press('Escape')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('信息卡默认展开并显示完整信息', () => {
    const withMeta = { ...item(1, 'a.png'), width: 1128, height: 2008, file_size: 2.5 * 1024 * 1024 }
    const wrapper = mount(Lightbox, { props: { items: [withMeta], index: 0 } })
    expect(wrapper.find('.info-body').exists()).toBe(true)
    expect(wrapper.find('.info-head').text()).toContain('a.png')
    expect(wrapper.find('.info-sum').text()).toBe('1128×2008')
  })

  it('2 秒无悬停后渐渐变淡，鼠标移入恢复', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
      const info = wrapper.find('.info')
      expect(info.classes()).not.toContain('faded')
      vi.advanceTimersByTime(2000)
      await wrapper.vm.$nextTick()
      expect(info.classes()).toContain('faded')
      await info.trigger('mouseenter')
      expect(info.classes()).not.toContain('faded')
    } finally {
      vi.useRealTimers()
    }
  })

  it('拖拽图片时划过信息卡不会恢复显示', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
      vi.advanceTimersByTime(2000)
      await wrapper.vm.$nextTick()
      const info = wrapper.find('.info')
      expect(info.classes()).toContain('faded')
      await wrapper.find('.stage').trigger('mousedown')
      await info.trigger('mouseenter')
      await info.trigger('mousemove')
      expect(info.classes()).toContain('faded')
      window.dispatchEvent(new MouseEvent('mousemove', { clientX: 20, clientY: 20 }))
      window.dispatchEvent(new MouseEvent('mouseup'))
      // 拖拽后在信息卡上松手：click 落到根节点也不能关灯箱
      await wrapper.find('.lightbox').trigger('click')
      expect(wrapper.emitted('close')).toBeUndefined()
    } finally {
      vi.useRealTimers()
    }
  })

  it('展示分辨率、体积与来源', () => {
    const withMeta = { ...item(1, 'a.png'), width: 1128, height: 2008, file_size: 2.5 * 1024 * 1024 }
    const wrapper = mount(Lightbox, { props: { items: [withMeta], index: 0 } })
    const facts = wrapper.find('.facts').text()
    expect(facts).toContain('1128×2008')
    expect(facts).toContain('2.5 MB')
    expect(facts).toContain('本机出图')
  })

  it('view_url 优先显示，缺失时回落到 viewUrl 拼装', () => {
    const withViewUrl = {
      ...item(1, 'a.png'),
      view_url: '/api/reference/items/pose/P001/image?kind=image',
    }
    const linked = mount(Lightbox, { props: { items: [withViewUrl], index: 0 } })
    expect(linked.find('.stage img').attributes('src')).toBe(
      '/api/reference/items/pose/P001/image?kind=image',
    )

    // 老记录 / 占位 fixture 的 view_url 为空：行为与改动前一致
    const fallback = mount(Lightbox, { props: { items: [item(2, 'b.png')], index: 0 } })
    expect(fallback.find('.stage img').attributes('src')).toBe('/api/media/image?filename=b.png')
  })

  it('readonly 隐藏写操作按钮，保留查看类工具', () => {
    const withPrompt = { ...item(1, 'a.png'), prompt_id: 1127 }
    const wrapper = mount(Lightbox, {
      props: { items: [withPrompt], index: 0, readonly: true },
    })
    const tools = wrapper.findAll('.bar .tool').map((button) => button.text())
    const tips = wrapper.findAll('.bar .tool').map((button) => button.attributes('data-tip') ?? '')

    // 写操作：投喂 / 重出图 / 提示词 / 收藏 / 删除（图标化后按 data-tip 断言）
    expect(tips.some((t) => t.startsWith('把这张图作为输入运行工作流'))).toBe(false)
    expect(tips.some((t) => t.startsWith('用当前工作流再抽一张'))).toBe(false)
    expect(tools).not.toContain('↗')
    expect(tools).not.toContain('☆')
    expect(tips).not.toContain('删除记录')
    // 查看类：下载 / 翻转 / 旋转 / 1:1 / 缩放 / 信息 / 关闭
    expect(tips).toContain('下载原图')
    expect(tools).toContain('⇋')
    expect(tools).toContain('⟳')
    expect(tools).toContain('1:1')
    expect(tools).toContain('ⓘ')
    expect(tools).toContain('✕')
  })

  it('fileActions=false 隐藏下载 / 目录 / 出片档案 / 存储位置', async () => {
    const wrapper = mount(Lightbox, {
      props: { items: [item(1, 'a.png')], index: 0, fileActions: false },
    })
    const tools = wrapper.findAll('.bar .tool').map((button) => button.text())
    const tips = wrapper.findAll('.bar .tool').map((button) => button.attributes('data-tip') ?? '')

    expect(tips).not.toContain('下载原图')
    expect(tools).not.toContain('目录')
    expect(wrapper.find('.prompt-link').exists()).toBe(false)
    expect(wrapper.find('.info').exists()).toBe(true)
    // 信息面板里不再给出依赖媒体三目录的假路径
    expect(wrapper.find('.info-body').text()).not.toContain('存储位置')

    // 缩放 / 翻转 / 旋转 / 信息 / 关闭仍然可用
    expect(tools).toContain('⇋')
    expect(tools).toContain('⟳')
    expect(tools).toContain('ⓘ')
    expect(tools).toContain('✕')
  })

  it('默认 fileActions=true：下载 / 目录 / 出片档案照常渲染', () => {
    const wrapper = mount(Lightbox, { props: { items: [item(1, 'a.png')], index: 0 } })
    const tools = wrapper.findAll('.bar .tool').map((button) => button.text())
    const tips = wrapper.findAll('.bar .tool').map((button) => button.attributes('data-tip') ?? '')

    expect(tips).toContain('下载原图')
    // 所有工具栏按钮都必须有即时的悬停说明
    expect(tips.every((tip) => tip.trim().length > 0)).toBe(true)
    expect(tools).toContain('目录')
    expect(wrapper.find('.prompt-link').exists()).toBe(true)
  })

  it('投喂只列单图工作流，并把提示词/档位传给后端', async () => {
    const wfs = [
      { path: '/wf/t2i.json', name: '文生图', image_slots: 0 },
      {
        path: '/wf/text.json',
        name: '图生文',
        image_slots: 1,
        caps: { image_output: false },
      },
      {
        path: '/wf/up.json',
        name: '超分工作流',
        image_slots: 1,
        caps: { prompt: true, negative: true, quality: true, orientation: false, image_output: true },
        params: { quality_mode: 'scale', quality_tiers: ['1.0x'] },
        size_preview: {},
      },
    ]
    const wrapper = mount(Lightbox, {
      props: { items: [item(1, 'a.png')], index: 0, workflows: wfs as any },
    })
    await wrapper.find('.bar .tool[data-tip*="运行工作流"]').trigger('click')
    expect(wrapper.find('.wf-picker').exists()).toBe(true)
    expect(wrapper.find('.wf-picker').text()).toContain('超分工作流')
    expect(wrapper.find('.wf-picker').text()).not.toContain('文生图')
    expect(wrapper.find('.wf-picker').text()).not.toContain('图生文')

    await wrapper.find('.wf-picker input').setValue('一只猫')
    await wrapper.find('.wf-actions .primary').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith(
      '/api/images/1/process',
      expect.objectContaining({
        workflow_path: '/wf/up.json',
        prompt: '一只猫',
        quality: '1.0x',
      }),
    )
  })

  it('缺失的图给出明确提示', () => {
    const missing = { ...item(1, 'a.png'), missing: true }
    const wrapper = mount(Lightbox, { props: { items: [missing], index: 0 } })
    expect(wrapper.find('.missing-tip').text()).toContain('磁盘上已找不到')
  })

  it('所有图片都显示统一的「出图档案」入口', () => {
    const linked = mount(Lightbox, {
      props: { items: [{ ...item(1, 'a.png'), prompt_id: 1127 }], index: 0 },
    })
    expect(linked.find('.prompt-link').text()).toContain('出图档案')

    const plain = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
    expect(plain.find('.prompt-link').text()).toContain('出图档案')
  })

  it('已关联提示词的图也能打开档案，显示提示词快照并可跳到提示词库', async () => {
    const withPrompt = {
      ...item(1, 'a.png'),
      prompt_id: 1127,
      prompt_name: '日系卧室',
      prompt_params: { prompt: '出图时的正文', negative_prompt: '低质量', source: 'prompt_run' },
    }
    const wrapper = mount(Lightbox, { props: { items: [withPrompt], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    expect(wrapper.findComponent(Modal).props('open')).toBe(true)
    expect(document.body.querySelector('.prompt-text')?.textContent).toContain('出图时的正文')
    expect(document.body.querySelector('.side-tag')?.textContent).toContain('已关联提示词库')

    const jump = document.body.querySelector('.prompt-jump') as HTMLElement
    expect(jump.textContent).toContain('日系卧室')
    jump.click()
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('jump-to-prompt')?.[0]).toEqual([1127])
  })

  it('显示提交时的编译器快照与实际负向', async () => {
    const withCompiled = {
      ...item(1, 'a.png'),
      prompt_params: {
        prompt: '原始正向，不要印章',
        negative_prompt: '原始负向',
        source: 'prompt_run',
        compiled: {
          positive: '编译后的正向，画面干净',
          negative: '印章, 水印',
          notes: ['把文字/水印类否定改写为「纸面干净」'],
          warnings: ['列表型否定仍有未处理项：摆拍'],
          negative_effective: true,
        },
      },
    }
    const wrapper = mount(Lightbox, { props: { items: [withCompiled], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    expect(document.body.querySelector('.compiled-positive')?.textContent).toContain('编译后的正向')
    expect(document.body.querySelector('.compiled-negative')?.textContent).toContain('印章, 水印')
    expect(document.body.querySelector('.compiled-notes')?.textContent).toContain('纸面干净')
    expect(document.body.querySelector('.compiled-notes.warn')?.textContent).toContain('摆拍')
  })

  it('负向不生效时编译快照明确标注不提交', async () => {
    const withCompiled = {
      ...item(1, 'a.png'),
      prompt_params: {
        prompt: '原始正向',
        compiled: {
          positive: '编译后的正向',
          negative: '水印',
          negative_effective: false,
        },
      },
    }
    const wrapper = mount(Lightbox, { props: { items: [withCompiled], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    expect(document.body.querySelector('.compiled-negative')?.textContent).toContain('工作流负向不生效')
  })

  it('已关联提示词但缺正文时回退到提示词库当前版本', async () => {
    const withPrompt = {
      ...item(1, 'a.png'),
      prompt_id: 1127,
      prompt_name: '日系卧室',
      prompt_params: null,
    }
    const wrapper = mount(Lightbox, { props: { items: [withPrompt], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    await flushPromises()
    expect(document.body.querySelector('.prompt-text')?.textContent).toContain('库里的当前正文')
    expect(document.body.querySelector('.text-note')?.textContent).toContain('当前提示词库版本')
    expect(document.body.querySelector('.neg-prompt')?.textContent).toContain('库负面')
  })

  it('临时提示词同样打开统一档案弹窗', async () => {
    const temp = {
      ...item(1, 'a.png'),
      prompt_id: 0,
      prompt_params: {
        prompt: '临时正文',
        negative_prompt: '负面词',
        source: 'composer',
        model: 'm.safetensors',
        width: 1024,
        height: 1536,
      },
    }
    const wrapper = mount(Lightbox, { props: { items: [temp], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    expect(wrapper.findComponent(Modal).props('open')).toBe(true)
    expect(document.body.querySelector('.prompt-text')?.textContent).toContain('临时正文')
    // 标题与文件信息在右栏；左栏只有提示词；没有额外标题栏
    const side = document.body.querySelector('.prompt-side')?.textContent ?? ''
    const main = document.body.querySelector('.prompt-main')?.textContent ?? ''
    expect(side).toContain('出图档案')
    expect(side).toContain('临时提示词')
    expect(side).toContain('概览')
    expect(side).toContain('文件与任务')
    expect(main).toContain('临时正文')
    expect(main).not.toContain('文件与任务')
    expect(document.body.querySelector('.modal-head')).toBeNull()
    // 概览指标格 + 长字段整行
    expect(document.body.querySelectorAll('.side-card').length).toBeGreaterThanOrEqual(2)
    expect(document.body.querySelectorAll('.stat').length).toBeGreaterThan(0)
    expect(document.body.querySelectorAll('.side-facts .kv.wide').length).toBeGreaterThan(0)

    // 文件名点击复制
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    ;(document.body.querySelector('.side-filename') as HTMLElement).click()
    await wrapper.vm.$nextTick()
    expect(writeText).toHaveBeenCalledWith('a.png')
  })

  it('存储位置点击后在资源管理器中定位', async () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    const path = document.body.querySelector('.side-facts dd.path') as HTMLElement
    expect(path.textContent).toContain('output/a.png')
    path.click()
    await flushPromises()
    expect(apiPost).toHaveBeenCalledWith('/api/images/reveal', { id: 1 })
  })

  it('来源提示词可点击跳到对应提示词', async () => {
    const replaced = {
      ...item(1, 'a.png'),
      prompt_id: 0,
      prompt_params: {
        prompt: '替换后的正文',
        source: 'batch_replace',
        source_prompt_id: 1049,
        source_prompt_name: '午后庭院',
      },
    }
    const wrapper = mount(Lightbox, { props: { items: [replaced], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    const rows = Array.from(document.body.querySelectorAll('.side-facts .kv'))
    const row = rows.find((el) => el.textContent?.includes('来源提示词')) as HTMLElement
    const link = row.querySelector('dd.linkable') as HTMLElement
    expect(link.textContent).toContain('午后庭院')
    expect(link.textContent).toContain('#1049')
    link.click()
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('jump-to-prompt')?.[0]).toEqual([1049])
  })

  it('source_prompt_id=0 不显示来源提示词行', async () => {
    const noSource = {
      ...item(1, 'a.png'),
      prompt_id: 0,
      prompt_params: { prompt: '正文', source: 'composer', source_prompt_id: 0 },
    }
    const wrapper = mount(Lightbox, { props: { items: [noSource], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    expect(document.body.querySelector('.prompt-side')?.textContent ?? '').not.toContain('来源提示词')
  })

  it('出图档案展示合成台落库的参考图缩略图，点击后页内放大', async () => {
    const withRefs = {
      ...item(1, 'a.png'),
      prompt_id: 0,
      prompt_params: {
        prompt: '合成正文',
        source: 'faceswap',
        inputs: [
          { role: 'target', node: '2', meta: { source: 'file', path: 'F:\\ref\\portrait.webp' } },
          { role: 'ref1', node: '3', meta: { source: 'file', path: 'F:\\ref\\costume.webp' } },
          { role: 'ref2', node: '1', meta: { source: 'file', path: 'F:\\ref\\pose.webp' } },
        ],
      },
    }
    const wrapper = mount(Lightbox, { props: { items: [withRefs], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')

    const cards = Array.from(document.body.querySelectorAll('.ref-card')) as HTMLButtonElement[]
    expect(cards).toHaveLength(3)
    expect(cards[0].querySelector('.ref-label')?.textContent).toBe('主图')
    expect(cards[1].querySelector('.ref-label')?.textContent).toBe('参考1')
    const thumb = cards[1].querySelector('.ref-thumb') as HTMLImageElement
    expect(thumb.getAttribute('src')).toContain('/api/browser/thumb?path=')

    // 参考图区块默认展开，点标题可收起/再展开
    const refToggle = Array.from(document.body.querySelectorAll('.side-toggle'))
      .find((el) => el.textContent?.includes('参考图')) as HTMLButtonElement
    refToggle.click()
    await wrapper.vm.$nextTick()
    expect((document.body.querySelector('.ref-grid') as HTMLElement).style.display).toBe('none')
    refToggle.click()
    await wrapper.vm.$nextTick()
    expect((document.body.querySelector('.ref-grid') as HTMLElement).style.display).toBe('')

    cards[1].click()
    await wrapper.vm.$nextTick()
    const preview = document.body.querySelector('.ref-preview')
    expect(preview).not.toBeNull()
    expect(preview?.textContent).toContain('参考1')
    const previewImg = preview?.querySelector('.ref-preview-img') as HTMLImageElement
    expect(previewImg.getAttribute('src')).toContain('/api/browser/image?path=')
    expect(previewImg.getAttribute('src')).toContain(
      encodeURIComponent('F:\\ref\\costume.webp'),
    )
    const external = preview?.querySelector('a') as HTMLAnchorElement
    expect(external.getAttribute('href')).toContain('/api/browser/image?path=')
    expect(external.getAttribute('target')).toBe('_blank')
  })

  it('参考图放大层按 Esc 只关闭自己，档案保持打开', async () => {
    const withRefs = {
      ...item(1, 'a.png'),
      prompt_id: 0,
      prompt_params: {
        prompt: '合成正文',
        source: 'faceswap',
        inputs: [{ role: 'target', meta: { path: 'F:\\ref\\portrait.webp' } }],
      },
    }
    const wrapper = mount(Lightbox, { props: { items: [withRefs], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    const card = document.body.querySelector('.ref-card') as HTMLButtonElement
    card.click()
    await wrapper.vm.$nextTick()
    expect(document.body.querySelector('.ref-preview')).not.toBeNull()

    press('Escape')
    await wrapper.vm.$nextTick()
    expect(document.body.querySelector('.ref-preview')).toBeNull()
    expect(wrapper.findComponent(Modal).props('open')).toBe(true)
  })

  it('参考图预览工具条支持翻转 / 旋转 / 1:1', async () => {
    const withRefs = {
      ...item(1, 'a.png'),
      prompt_id: 0,
      prompt_params: {
        prompt: '合成正文',
        source: 'faceswap',
        inputs: [{ role: 'target', meta: { path: 'F:\\ref\\portrait.webp' } }],
      },
    }
    const wrapper = mount(Lightbox, { props: { items: [withRefs], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    ;(document.body.querySelector('.ref-card') as HTMLButtonElement).click()
    await wrapper.vm.$nextTick()

    const preview = document.body.querySelector('.ref-preview') as HTMLElement
    const img = preview.querySelector('.ref-preview-img') as HTMLImageElement
    Object.defineProperty(img, 'naturalWidth', { configurable: true, value: 1200 })
    Object.defineProperty(img, 'naturalHeight', { configurable: true, value: 1600 })
    img.dispatchEvent(new Event('load'))
    await wrapper.vm.$nextTick()

    const buttons = Array.from(
      preview.querySelectorAll('.ref-preview-bar button'),
    ) as HTMLButtonElement[]
    const flip = buttons.find((b) => b.textContent?.trim() === '⇋') as HTMLButtonElement
    const rotate = buttons.find((b) => b.textContent?.trim() === '⟳') as HTMLButtonElement
    const actual = buttons.find((b) => b.textContent?.trim() === '1:1') as HTMLButtonElement

    flip.click()
    await wrapper.vm.$nextTick()
    expect(img.style.transform).toContain('scale(-')

    rotate.click()
    await wrapper.vm.$nextTick()
    expect(img.style.transform).toContain('rotate(90deg)')

    actual.click()
    await wrapper.vm.$nextTick()
    expect(actual.classList.contains('active')).toBe(true)
  })

  it('「在参考图库中打开」按反查结果跳到对应页签并预填检索词', async () => {
    const withRefs = {
      ...item(1, 'a.png'),
      prompt_id: 0,
      prompt_params: {
        prompt: '合成正文',
        source: 'faceswap',
        inputs: [{ role: 'target', meta: { path: 'F:\\ref\\portrait.webp' } }],
      },
    }
    const wrapper = mount(Lightbox, { props: { items: [withRefs], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    ;(document.body.querySelector('.ref-card') as HTMLButtonElement).click()
    await wrapper.vm.$nextTick()

    const open = Array.from(
      document.body.querySelectorAll('.ref-preview-bar button'),
    ).find((b) => b.textContent?.includes('在参考图库中打开')) as HTMLButtonElement
    open.click()
    await flushPromises()

    expect(routerPush).toHaveBeenCalledWith({
      path: '/reference',
      query: { tab: 'portrait', q: 'p1' },
    })
    expect(document.body.querySelector('.ref-preview')).toBeNull()
  })

  it('没有输入图路径时不出现参考图区块', async () => {
    const wrapper = mount(Lightbox, { props: { items: [item(1, 'a.png')], index: 0 } })
    await wrapper.find('.prompt-link').trigger('click')
    expect(document.body.querySelector('.ref-card')).toBeNull()
  })

  it('刷新后自动恢复临时提示词弹窗', async () => {
    const temp = {
      ...item(7, 't.png'),
      prompt_id: 0,
      prompt_params: { prompt: '恢复正文', source: 'composer' },
    }
    localStorage.setItem('pb.viewer.promptOpen', '7')
    const wrapper = mount(Lightbox, { props: { items: [temp], index: 0 } })
    await wrapper.vm.$nextTick()
    expect(wrapper.findComponent(Modal).props('open')).toBe(true)
    // 避免影响后续用例
    localStorage.setItem('pb.viewer.promptOpen', '0')
  })

  it('点击 stage 空白关闭查看器', async () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
    await wrapper.find('.stage').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('点击图片本身不关闭查看器', async () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
    await wrapper.find('.stage img').trigger('click')
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('首屏先显示加载占位，加载完成后隐藏', async () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
    expect(wrapper.find('.stage-state.loading').exists()).toBe(true)

    await wrapper.find('.stage img').trigger('load')
    expect(wrapper.find('.stage-state.loading').exists()).toBe(false)
  })

  it('图片加载失败显示重试，点击后回到加载态', async () => {
    const wrapper = mount(Lightbox, { props: { items: ITEMS, index: 0 } })
    await wrapper.find('.stage img').trigger('error')

    const errorState = wrapper.find('.stage-state.error')
    expect(errorState.exists()).toBe(true)
    expect(errorState.text()).toContain('加载失败')

    await errorState.find('button').trigger('click')
    expect(wrapper.find('.stage-state.loading').exists()).toBe(true)
  })
})
