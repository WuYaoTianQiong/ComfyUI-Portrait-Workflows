import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import ImagePicker from './ImagePicker.vue'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async (_path: string, params?: Record<string, unknown>) => {
    // 「清理失效」按 ids 精确校验：只返回仍存在的记录，id=2 标记文件缺失
    if (params && 'ids' in params) {
      const wanted = String(params.ids)
        .split(',')
        .filter(Boolean)
        .map(Number)
      const items = [
        { id: 1, filename: 'a.png' },
        { id: 2, filename: 'b.png', missing: true },
      ].filter((item) => wanted.includes(item.id))
      return { items, total: items.length, page: 1, page_size: items.length }
    }
    return {
      items: [
        { id: 1, filename: 'a.png' },
        { id: 2, filename: 'b.png' },
        { id: 3, filename: 'c.png' },
      ],
      total: 3,
      page: 1,
      page_size: 100,
    }
  }),
  thumbnailUrl: (i: { filename: string }) => '/api/thumb?filename=' + i.filename,
}))

async function mountPicker(selected: number[] = []) {
  const wrapper = mount(ImagePicker, {
    props: { title: '主图', modelValue: selected },
    global: {
      plugins: [[VueQueryPlugin, { queryClient: new QueryClient() }]],
    },
  })
  await flushPromises()
  return wrapper
}

describe('ImagePicker', () => {
  it('渲染可选项', async () => {
    const wrapper = await mountPicker()
    expect(wrapper.findAll('.cell')).toHaveLength(3)
  })

  it('勾选后 emit 完整的选择顺序 —— 1:1 配对靠它，不能只存集合', async () => {
    const wrapper = await mountPicker()
    const cells = wrapper.findAll('.cell')
    await cells[0].trigger('click')
    // 受控组件：父组件要把新值回传，否则下一次点击读到的还是初始 props
    let emitted = wrapper.emitted('update:modelValue') as number[][][]
    expect(emitted[0][0]).toEqual([1])
    await wrapper.setProps({ modelValue: emitted[0][0] })

    await cells[1].trigger('click')
    emitted = wrapper.emitted('update:modelValue') as number[][][]
    expect(emitted[1][0]).toEqual([1, 2])
  })

  it('取消勾选时移除并保持其余顺序', async () => {
    const wrapper = await mountPicker([1, 2, 3])
    await wrapper.findAll('.cell')[0].trigger('click')
    const emitted = wrapper.emitted('update:modelValue') as number[][][]
    expect(emitted[0][0]).toEqual([2, 3])
  })

  it('已选项显示顺序序号', async () => {
    const wrapper = await mountPicker([1, 2])
    const orders = wrapper.findAll('.order').map((n) => n.text())
    expect(orders).toEqual(['1', '2'])
  })

  it('标题旁显示已选数量', async () => {
    const wrapper = await mountPicker([1, 2, 3])
    expect(wrapper.find('.count').text()).toContain('已选 3')
  })

  it('清空按钮 emit 空数组', async () => {
    const wrapper = await mountPicker([1])
    const clear = wrapper.findAll('.picker-head button').find((b) => b.text() === '清空')!
    await clear.trigger('click')
    const emitted = wrapper.emitted('update:modelValue') as number[][][]
    expect(emitted[0][0]).toEqual([])
  })

  it('清理失效移除已删除记录与文件缺失的已选 id', async () => {
    const wrapper = await mountPicker([1, 2, 3])
    await wrapper.find('.picker-head .cleanup').trigger('click')
    await flushPromises()
    const emitted = wrapper.emitted('update:modelValue') as number[][][]
    expect(emitted[0][0]).toEqual([1])

    // 受控组件：父组件回传后计数应跟着降下来
    await wrapper.setProps({ modelValue: emitted[0][0] })
    expect(wrapper.find('.count').text()).toContain('已选 1')
  })
})
