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

describe('CompareModal 多图对比', () => {
  it('渲染每张图一格', () => {
    const wrapper = mount(CompareModal, { props: { open: true, items: ITEMS } })
    expect(wrapper.findAll('.cell').length).toBe(3)
    expect(wrapper.text()).toContain('图片对比（3 张）')
  })

  it('默认同步模式，可切到分屏', async () => {
    const wrapper = mount(CompareModal, { props: { open: true, items: ITEMS } })
    expect(wrapper.find('.body').classes()).toContain('sync')
    const split = wrapper.findAll('.mode-switch .tool').find((b) => b.text() === '分屏')!
    await split.trigger('click')
    expect(wrapper.find('.body').classes()).toContain('split')
  })

  it('放大按钮提高缩放比例', async () => {
    const wrapper = mount(CompareModal, { props: { open: true, items: ITEMS } })
    expect(wrapper.find('.zoom').text()).toBe('100%')
    const plus = wrapper.findAll('.tool').find((b) => b.text() === '+')!
    await plus.trigger('click')
    expect(wrapper.find('.zoom').text()).toBe('120%')
  })

  it('重置回到 100%', async () => {
    const wrapper = mount(CompareModal, { props: { open: true, items: ITEMS } })
    const plus = wrapper.findAll('.tool').find((b) => b.text() === '+')!
    await plus.trigger('click')
    const reset = wrapper.findAll('.tool').find((b) => b.text() === '重置')!
    await reset.trigger('click')
    expect(wrapper.find('.zoom').text()).toBe('100%')
  })

  it('Esc 关闭', async () => {
    const wrapper = mount(CompareModal, { props: { open: true, items: ITEMS } })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
