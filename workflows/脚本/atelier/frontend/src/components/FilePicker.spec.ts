import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import FilePicker from './FilePicker.vue'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/browser/list')) {
      return {
        path: 'F:\\out',
        parent: 'F:\\',
        roots: [{ name: 'ComfyUI/output', path: 'F:\\out' }],
        dirs: [{ name: 'sub', path: 'F:\\out\\sub' }],
        images: [
          { name: 'a.png', path: 'F:\\out\\a.png', size: 1, mtime: 0 },
          { name: 'b.png', path: 'F:\\out\\b.png', size: 1, mtime: 1 },
          { name: 'c.jpg', path: 'F:\\out\\c.jpg', size: 1, mtime: 2 },
        ],
        truncated: false,
      }
    }
    return {}
  }),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))

async function mountPicker(selected: string[] = []) {
  const wrapper = mount(FilePicker, {
    props: { open: true, title: '从磁盘选主图', modelValue: selected },
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
      // Modal 用 Teleport 渲染到 body，测试里要 stub 掉才能在 wrapper 内查到
      stubs: { teleport: true },
    },
  })
  await flushPromises()
  return wrapper
}

describe('FilePicker 磁盘选图', () => {
  it('列出当前目录的图片与子目录', async () => {
    const wrapper = await mountPicker()
    expect(wrapper.findAll('.cell').length).toBe(3)
    expect(wrapper.findAll('.dir').length).toBe(1)
  })

  it('点图片切换选中状态', async () => {
    const wrapper = await mountPicker()
    await wrapper.findAll('.cell')[0].trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.cell.on').length).toBe(1)
  })

  it('确定后把路径 emit 出去', async () => {
    const wrapper = await mountPicker()
    await wrapper.findAll('.cell')[1].trigger('click')
    await flushPromises()
    const ok = wrapper.findAll('button').find((b) => b.text() === '确定')!
    await ok.trigger('click')
    const emitted = wrapper.emitted('update:modelValue') as string[][]
    expect(emitted[0][0]).toEqual(['F:\\out\\b.png'])
  })

  it('打开时带入已有的选择', async () => {
    const wrapper = await mountPicker(['F:\\out\\a.png'])
    expect(wrapper.findAll('.cell.on').length).toBe(1)
    expect(wrapper.text()).toContain('已选 1 张')
  })

  it('全选本目录后确定会提交全部图片', async () => {
    const wrapper = await mountPicker()
    await wrapper.findAll('button').find((b) => b.text().startsWith('全选'))!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.cell.on').length).toBe(3)
    await wrapper.findAll('button').find((b) => b.text() === '确定')!.trigger('click')
    const emitted = wrapper.emitted('update:modelValue') as string[][]
    expect(emitted[0][0]).toEqual(['F:\\out\\a.png', 'F:\\out\\b.png', 'F:\\out\\c.jpg'])
  })

  it('反选只反转当前目录的勾选状态', async () => {
    const wrapper = await mountPicker()
    await wrapper.findAll('.cell')[0].trigger('click')
    await wrapper.findAll('button').find((b) => b.text() === '反选')!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.cell.on').length).toBe(2)
    const emittedOn = wrapper.findAll('.cell.on').map((c) => c.attributes('title'))
    expect(emittedOn).toEqual(['b.png', 'c.jpg'])
  })

  it('已选清单能显示所有已选图片并单张移除', async () => {
    const wrapper = await mountPicker(['F:\\out\\a.png', 'F:\\out\\b.png'])
    expect(wrapper.find('.picked-bar').exists()).toBe(true)
    expect(wrapper.findAll('.picked-bar .path-item').length).toBe(2)
    expect(wrapper.findAll('.picked-bar .name').map((n) => n.text())).toEqual(['a.png', 'b.png'])

    await wrapper.findAll('.picked-bar .remove')[0].trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.picked-bar .path-item').length).toBe(1)
    expect(wrapper.findAll('.cell.on').length).toBe(1)
  })

  it('清空已选后可以重新挑图', async () => {
    const wrapper = await mountPicker(['F:\\out\\a.png'])
    await wrapper.findAll('button').find((b) => b.text() === '清空已选')!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.cell.on').length).toBe(0)
    await wrapper.findAll('button').find((b) => b.text() === '确定')!.trigger('click')
    const emitted = wrapper.emitted('update:modelValue') as string[][]
    expect(emitted[0][0]).toEqual([])
  })

  it('搜索与格式筛选都只作用于当前目录列表', async () => {
    const wrapper = await mountPicker()
    await wrapper.find('.filters .search').setValue('jpg')
    await flushPromises()
    expect(wrapper.findAll('.cell').length).toBe(1)
    expect(wrapper.text()).toContain('本目录 1 / 3 张')

    await wrapper.find('.filters .search').setValue('')
    await wrapper.find('.filters .type').setValue('.png')
    await flushPromises()
    expect(wrapper.findAll('.cell').length).toBe(2)
  })

  it('按时间倒序时最新图片排在最前', async () => {
    const wrapper = await mountPicker()
    await wrapper.find('.filters .sort').setValue('mtime_desc')
    await flushPromises()
    expect(wrapper.findAll('.cell')[0].attributes('title')).toBe('c.jpg')
  })
})
