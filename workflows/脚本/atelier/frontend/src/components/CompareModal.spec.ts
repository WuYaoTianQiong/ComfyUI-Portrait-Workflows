import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CompareModal from './CompareModal.vue'
import type { HistoryItem } from '../api/types'

vi.mock('../api/client', () => ({
  viewUrl: (item: { filename: string }) => '/api/media/image?filename=' + item.filename,
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
}))

function item(
  id: number,
  filename: string,
  width: number | null = null,
  height: number | null = null,
): HistoryItem {
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
    width,
    height,
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

function mountModal(items = ITEMS) {
  return mount(CompareModal, { props: { open: true, items }, attachTo: document.body })
}

type Modal = ReturnType<typeof mountModal>

/** happy-dom 没有布局：手动给舞台尺寸，让「适应窗口」算得出比例。 */
function prepareCells(wrapper: Modal) {
  wrapper.findAll('.cell-scroll').forEach((cell) => {
    Object.defineProperty(cell.element, 'clientWidth', { value: 600, configurable: true })
    Object.defineProperty(cell.element, 'clientHeight', { value: 900, configurable: true })
  })
}

/** 触发图片 load，把自然尺寸交给视图实例。 */
async function loadImages(wrapper: Modal) {
  const imgs = wrapper.findAll('.cell img')
  for (const img of imgs) {
    Object.defineProperty(img.element, 'naturalWidth', { value: 832, configurable: true })
    Object.defineProperty(img.element, 'naturalHeight', { value: 1216, configurable: true })
  }
  await Promise.all(imgs.map((img) => img.trigger('load')))
}

async function prepare(wrapper: Modal) {
  prepareCells(wrapper)
  await loadImages(wrapper)
}

function imgStyles(wrapper: Modal) {
  return wrapper.findAll('.cell img').map((img) => img.attributes('style') ?? '')
}

/** 等 rAF 插值收敛。 */
function settle() {
  return new Promise((resolve) => setTimeout(resolve, 400))
}

describe('CompareModal 多图对比', () => {
  it('渲染每张图一格', () => {
    const wrapper = mountModal()
    expect(wrapper.findAll('.cell').length).toBe(3)
    expect(wrapper.text()).toContain('图片对比（3 张）')
  })

  it('按数量套用网格类名 —— 3 张时首图跨两列（旧版 compare-grid-N）', () => {
    const wrapper = mountModal()
    expect(wrapper.find('.body').classes()).toContain('compare-grid-3')
    expect(mountModal(ITEMS.slice(0, 2)).find('.body').classes()).toContain('compare-grid-2')
    expect(mountModal(ITEMS.slice(0, 1)).find('.body').classes()).toContain('compare-grid-1')
  })

  it('三张竖图自动改走三列并列', () => {
    const portrait = [
      item(1, 'a.png', 832, 1216),
      item(2, 'b.png', 832, 1216),
      item(3, 'c.png', 832, 1216),
    ]
    expect(mountModal(portrait).find('.body').classes()).toContain('compare-grid-3-row')
  })

  it('三张横图仍保留品字布局', () => {
    const landscape = [
      item(1, 'a.png', 1536, 1024),
      item(2, 'b.png', 1536, 1024),
      item(3, 'c.png', 1536, 1024),
    ]
    const wrapper = mountModal(landscape)
    expect(wrapper.find('.body').classes()).toContain('compare-grid-3')
    expect(wrapper.find('.body').classes()).not.toContain('compare-grid-3-row')
  })

  it('布局按钮可在并列与品字之间切换', async () => {
    const portrait = [
      item(1, 'a.png', 832, 1216),
      item(2, 'b.png', 832, 1216),
      item(3, 'c.png', 832, 1216),
    ]
    const wrapper = mountModal(portrait)
    const layoutBtn = wrapper.findAll('.tool').find((b) => b.text().includes('并列布局'))
    expect(layoutBtn).toBeTruthy()
    await layoutBtn!.trigger('click')
    expect(wrapper.find('.body').classes()).toContain('compare-grid-3')

    const back = wrapper.findAll('.tool').find((b) => b.text().includes('品字布局'))
    expect(back).toBeTruthy()
    await back!.trigger('click')
    expect(wrapper.find('.body').classes()).toContain('compare-grid-3-row')
  })

  it('默认开启缩放联动，可切到独立', async () => {
    const wrapper = mountModal()
    const btn = wrapper.find('.bar .tool')
    expect(btn.text()).toContain('缩放联动')
    await btn.trigger('click')
    expect(wrapper.find('.bar .tool').text()).toContain('独立缩放')
  })

  it('滚轮缩放：联动时所有图一起放大', async () => {
    const wrapper = mountModal()
    await prepare(wrapper)
    const before = imgStyles(wrapper)

    await wrapper.findAll('.cell')[0].trigger('wheel', { deltaY: -120 })
    await settle()

    const after = imgStyles(wrapper)
    expect(after[0]).not.toBe(before[0])
    expect(after[1]).toBe(after[0])
    expect(after[2]).toBe(after[0])
  })

  it('滚轮缩放：独立时只影响所在的那张', async () => {
    const wrapper = mountModal()
    await prepare(wrapper)
    const before = imgStyles(wrapper)

    await wrapper.find('.bar .tool').trigger('click') // 关掉联动
    await wrapper.findAll('.cell')[0].trigger('wheel', { deltaY: -120 })
    await settle()

    const after = imgStyles(wrapper)
    expect(after[0]).not.toBe(before[0])
    expect(after[1]).toBe(before[1])
    expect(after[2]).toBe(before[2])
  })

  it('重置按钮回到适应窗口的比例', async () => {
    const wrapper = mountModal()
    await prepare(wrapper)
    const before = imgStyles(wrapper)

    await wrapper.findAll('.cell')[0].trigger('wheel', { deltaY: -120 })
    await settle()
    expect(imgStyles(wrapper)[0]).not.toBe(before[0])

    const reset = wrapper.findAll('.tool').find((b) => b.text() === '重置')!
    await reset.trigger('click')
    await wrapper.vm.$nextTick()
    expect(imgStyles(wrapper)).toEqual(before)
  })

  it('Esc 关闭', async () => {
    const wrapper = mountModal()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
