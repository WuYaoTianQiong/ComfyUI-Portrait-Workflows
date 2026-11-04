import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import RefLightbox from './RefLightbox.vue'
import type { ReferenceItem } from '../api/reference'

/**
 * 参考图库灯箱的只读行为：渲染、白模/深度切换、下载入口。
 *
 * 组件里用了 ResizeObserver 与 window keydown，happy-dom 没有前者时补一个空实现；
 * 图片本身不会真的加载，断言只针对 src / 属性，不依赖网络。
 */
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub)

function item(overrides: Partial<ReferenceItem> = {}): ReferenceItem {
  return {
    id: 'P001_front',
    library: 'pose',
    name: '正面站姿',
    subtitle: 'P001 · 正面',
    group: '日常',
    facet: '站姿',
    angle: '正面',
    tags: ['站姿'],
    keywords: 'standing',
    thumb_url: '/api/reference/items/pose/P001_front/image?kind=thumb',
    image_url: '/api/reference/items/pose/P001_front/image?kind=image',
    depth_url: '/api/reference/items/pose/P001_front/image?kind=depth',
    depth_thumb_url: '/api/reference/items/pose/P001_front/image?kind=depth_thumb',
    hot: false,
    featured: false,
    nsfw: false,
    remote: false,
    ...overrides,
  }
}

function mountLightbox(items: ReferenceItem[] = [item()], index = 0) {
  return mount(RefLightbox, {
    props: { items, index },
    // Teleport 到 body 后在 wrapper 里查不到节点，测试里就地渲染
    global: { stubs: { teleport: true } },
  })
}

function findTool(wrapper: ReturnType<typeof mountLightbox>, text: string) {
  const tool = wrapper.findAll('.lb-tools .tool').find((node) => node.text() === text)
  if (!tool) throw new Error(`没找到工具按钮：${text}`)
  return tool
}

describe('RefLightbox', () => {
  it('渲染条目标题、信息与角度位置', () => {
    const wrapper = mountLightbox([item(), item({ id: 'P001_side', angle: '侧面' })], 0)

    expect(wrapper.find('.lb-title .name').text()).toBe('正面站姿')
    expect(wrapper.find('.lb-title .sub').text()).toBe('P001 · 正面')
    expect(wrapper.find('.lb-title .pos').text()).toBe('角度 1/2 · 正面')
    expect(wrapper.find('.info').text()).toContain('P001_front')
    expect(wrapper.find('.info').text()).toContain('日常')
  })

  it('姿势条目默认显示原图，切到深度后使用 depth_url', async () => {
    const wrapper = mountLightbox()
    expect(wrapper.find('.stage img').attributes('src')).toBe(item().image_url)

    await findTool(wrapper, '深度').trigger('click')
    expect(wrapper.find('.stage img').attributes('src')).toBe(item().depth_url)

    await findTool(wrapper, '白模').trigger('click')
    expect(wrapper.find('.stage img').attributes('src')).toBe(item().image_url)
  })

  it('没有深度图时「深度」按钮禁用，不会切换 src', async () => {
    const wrapper = mountLightbox([item({ depth_url: null, depth_thumb_url: null })])
    const depth = findTool(wrapper, '深度')
    expect(depth.attributes('disabled')).toBeDefined()

    await depth.trigger('click')
    expect(wrapper.find('.stage img').attributes('src')).toBe(item().image_url)
  })

  it('非姿势库不显示白模/深度切换', () => {
    const costume = item({ library: 'costume', depth_url: null, depth_thumb_url: null })
    const wrapper = mountLightbox([costume])

    const labels = wrapper.findAll('.lb-tools .tool').map((node) => node.text())
    expect(labels).not.toContain('白模')
    expect(labels).not.toContain('深度')
  })

  it('本地条目提供带 download 的原图链接', () => {
    const wrapper = mountLightbox()
    const link = wrapper.findAll('.lb-tools a').find((node) => node.text() === '下载')
    expect(link).toBeTruthy()
    expect(link!.attributes('href')).toBe(item().image_url)
    expect(link!.attributes('download')).toBe('pose-P001_front')
  })

  it('外链条目改为新窗口打开原图，不提供下载属性', () => {
    const remote = item({
      library: 'costume-anime',
      id: 'charadb-O001',
      remote: true,
      image_url: 'https://example.invalid/img/O001.jpg',
      depth_url: null,
      depth_thumb_url: null,
    })
    const wrapper = mountLightbox([remote])
    const link = wrapper.findAll('.lb-tools a').find((node) => node.text() === '打开原图')
    expect(link).toBeTruthy()
    expect(link!.attributes('target')).toBe('_blank')
    expect(link!.attributes('download')).toBeUndefined()
    expect(wrapper.find('.remote-note').text()).toContain('不能作为参考输入')
  })

  it('左右箭头切换角度并发出 update:index', async () => {
    const wrapper = mountLightbox([item(), item({ id: 'P001_side', angle: '侧面' })], 0)
    await wrapper.find('.nav.next').trigger('click')
    expect(wrapper.emitted('update:index')?.[0]).toEqual([1])
    expect(wrapper.find('.nav.prev').attributes('disabled')).toBeDefined()
  })

  it('按 Esc 与点击舞台空白都发出 close', async () => {
    const wrapper = mountLightbox()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('close')).toBeTruthy()

    const second = mountLightbox()
    await second.find('.stage').trigger('click')
    expect(second.emitted('close')).toBeTruthy()
  })
})