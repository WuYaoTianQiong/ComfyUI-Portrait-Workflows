import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import FilePicker from './FilePicker.vue'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.includes('/api/fs/list')) {
      return {
        path: 'F:\\out',
        parent: 'F:\\',
        roots: [{ name: 'ComfyUI/output', path: 'F:\\out' }],
        dirs: [{ name: 'sub', path: 'F:\\out\\sub' }],
        images: [
          { name: 'a.png', path: 'F:\\out\\a.png', size: 1, mtime: 0 },
          { name: 'b.png', path: 'F:\\out\\b.png', size: 1, mtime: 0 },
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
    expect(wrapper.findAll('.cell').length).toBe(2)
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
})
