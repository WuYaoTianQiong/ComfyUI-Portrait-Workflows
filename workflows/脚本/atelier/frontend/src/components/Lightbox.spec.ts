import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import Lightbox from './Lightbox.vue'
import Modal from './Modal.vue'
import type { HistoryItem } from '../api/types'

enableAutoUnmount(afterEach)

vi.mock('../api/client', () => ({
  viewUrl: (item: { filename: string }) => '/api/media/image?filename=' + item.filename,
  thumbnailUrl: (item: { filename: string }) => '/api/thumb?filename=' + item.filename,
}))

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

  it('缺失的图给出明确提示', () => {
    const missing = { ...item(1, 'a.png'), missing: true }
    const wrapper = mount(Lightbox, { props: { items: [missing], index: 0 } })
    expect(wrapper.find('.missing-tip').text()).toContain('磁盘上已找不到')
  })

  it('有 prompt_id 时提供跳转提示词入口', async () => {
    const withPrompt = { ...item(1, 'a.png'), prompt_id: 1127, prompt_name: '日系卧室' }
    const wrapper = mount(Lightbox, { props: { items: [withPrompt], index: 0 } })
    const link = wrapper.find('.prompt-link')
    expect(link.text()).toContain('跳到提示词')
    await link.trigger('click')
    expect(wrapper.emitted('jump-to-prompt')?.[0]).toEqual([1127])
  })

  it('无 prompt_id 但有临时提示词时打开参数弹窗', async () => {
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
    const link = wrapper.find('.prompt-link')
    expect(link.text()).toContain('查看提示词信息')
    await link.trigger('click')
    expect(wrapper.findComponent(Modal).props('open')).toBe(true)
    expect(document.body.querySelector('.prompt-text')?.textContent).toContain('临时正文')
    // 标题与文件信息在右栏；左栏只有提示词；没有额外标题栏
    const side = document.body.querySelector('.prompt-side')?.textContent ?? ''
    const main = document.body.querySelector('.prompt-main')?.textContent ?? ''
    expect(side).toContain('出图参数（未关联提示词库）')
    expect(side).toContain('文件信息')
    expect(main).toContain('临时正文')
    expect(main).not.toContain('文件信息')
    expect(document.body.querySelector('.modal-head')).toBeNull()

    // 标题与文件名点击复制
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    ;(document.body.querySelector('.side-filename') as HTMLElement).click()
    await wrapper.vm.$nextTick()
    expect(writeText).toHaveBeenCalledWith('a.png')
    ;(document.body.querySelector('.side-heading') as HTMLElement).click()
    expect(writeText).toHaveBeenCalledTimes(2)
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
})
