import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import ImagePicker from './ImagePicker.vue'

vi.mock('../api/client', () => ({
  apiGet: vi.fn(async () => ({
    items: [
      { id: 1, filename: 'a.png' },
      { id: 2, filename: 'b.png' },
      { id: 3, filename: 'c.png' },
    ],
    total: 3,
    page: 1,
    page_size: 100,
  })),
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
    await wrapper.find('.picker-head .btn').trigger('click')
    const emitted = wrapper.emitted('update:modelValue') as number[][][]
    expect(emitted[0][0]).toEqual([])
  })
})
