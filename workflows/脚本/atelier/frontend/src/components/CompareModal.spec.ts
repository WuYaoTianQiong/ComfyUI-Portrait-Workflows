import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CompareModal from './CompareModal.vue'
import type { HistoryItem } from '../api/types'

vi.mock('../api/client', () => ({
  viewUrl: (item: { filename: string }) => '/api/image?filename=' + item.filename,
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
}))

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
    favorite: false,
    missing: false,
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
  return mount(CompareModal, { props: { open: true, items } })
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

  it('默认开启缩放联动，可切到独立', async () => {
    const wrapper = mountModal()
    const btn = wrapper.find('.bar .tool')
    expect(btn.text()).toContain('缩放联动')
    await btn.trigger('click')
    expect(wrapper.find('.bar .tool').text()).toContain('独立缩放')
  })

  it('滚轮缩放：联动时所有图一起放大', async () => {
    const wrapper = mountModal()
    const cell = wrapper.findAll('.cell')[0]
    await cell.trigger('wheel', { deltaY: -100 })
    await wrapper.vm.$nextTick()

    const styles = wrapper.findAll('.cell img').map((img) => img.attributes('style'))
    expect(styles[0]).toContain('--zoom: 1.15')
    expect(styles[1]).toBe(styles[0])
    expect(styles[2]).toBe(styles[0])

  })
  it('滚轮缩放：独立时只影响所在的那张', async () => {
    const wrapper = mountModal()
    await wrapper.find('.bar .tool').trigger('click') // 关掉联动
    const cell = wrapper.findAll('.cell')[0]
    await cell.trigger('wheel', { deltaY: -100 })
    await wrapper.vm.$nextTick()

    const styles = wrapper.findAll('.cell img').map((img) => img.attributes('style'))
    expect(styles[0]).toContain('--zoom: 1.15')
    expect(styles[1]).not.toContain('--zoom: 1.15')

  })
  it('重置按钮把缩放与平移归零', async () => {
    const wrapper = mountModal()
    await wrapper.findAll('.cell')[0].trigger('wheel', { deltaY: -100 })
    await wrapper.vm.$nextTick()
    const reset = wrapper.findAll('.tool').find((b) => b.text() === '重置')!
    await reset.trigger('click')
    await wrapper.vm.$nextTick()
    const style = wrapper.findAll('.cell img')[0].attributes('style') ?? ''
    expect(style).toContain('translate(0px, 0px)')
  })

  it('Esc 关闭', async () => {
    const wrapper = mountModal()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
