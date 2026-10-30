import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import Lightbox from './Lightbox.vue'
import type { HistoryItem } from '../api/types'

vi.mock('../api/client', () => ({
  viewUrl: (item: { filename: string }) => '/api/image?filename=' + item.filename,
  thumbnailUrl: (item: { filename: string }) => '/api/thumb?filename=' + item.filename,
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

  it('展示分辨率、体积与来源', () => {
    const withMeta = { ...item(1, 'a.png'), width: 1128, height: 2008, file_size: 2.5 * 1024 * 1024 }
    const wrapper = mount(Lightbox, { props: { items: [withMeta], index: 0 } })
    const facts = wrapper.find('.facts').text()
    expect(facts).toContain('1128×2008')
    expect(facts).toContain('2.5 MB')
    expect(facts).toContain('本机出图')
  })

  it('缺失的图给出明确提示', () => {
    const missing = { ...item(1, 'a.png'), missing: true }
    const wrapper = mount(Lightbox, { props: { items: [missing], index: 0 } })
    expect(wrapper.find('.missing-tip').text()).toContain('磁盘上已找不到')
  })
})
