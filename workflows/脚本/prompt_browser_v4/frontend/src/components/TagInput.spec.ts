import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TagInput from './TagInput.vue'
import type { TagRow } from '../api/types'

function tag(id: number, name: string, count: number): TagRow {
  return { id, name, color: '#5b8fb9', usage_count: 0, prompt_count: count }
}

const SUGGESTIONS: TagRow[] = [
  tag(1, '女性', 175),
  tag(2, '古风', 59),
  tag(3, '包', 71),
]

describe('TagInput', () => {
  it('展示已选标签', () => {
    const wrapper = mount(TagInput, {
      props: { modelValue: ['女性', '古风'], suggestions: SUGGESTIONS },
    })
    expect(wrapper.findAll('.picked-tag').length).toBe(2)
    expect(wrapper.text()).toContain('女性')
  })

  it('候选排除已选标签', async () => {
    const wrapper = mount(TagInput, {
      props: { modelValue: ['女性'], suggestions: SUGGESTIONS },
    })
    await wrapper.find('input').trigger('focus')
    await wrapper.vm.$nextTick()
    const names = wrapper.findAll('.candidate .name').map((n) => n.text())
    expect(names).not.toContain('女性')
    expect(names).toContain('古风')
  })

  it('输入关键字过滤候选', async () => {
    const wrapper = mount(TagInput, {
      props: { modelValue: [], suggestions: SUGGESTIONS },
    })
    await wrapper.find('input').setValue('古')
    await wrapper.find('input').trigger('focus')
    await wrapper.vm.$nextTick()
    const names = wrapper.findAll('.candidate .name').map((n) => n.text())
    expect(names).toEqual(['古风'])
  })

  it('点候选追加到已选', async () => {
    const wrapper = mount(TagInput, {
      props: { modelValue: ['女性'], suggestions: SUGGESTIONS },
    })
    await wrapper.find('input').trigger('focus')
    await wrapper.vm.$nextTick()
    const target = wrapper.findAll('.candidate').find((c) => c.text().includes('古风'))!
    await target.trigger('mousedown')
    const emitted = wrapper.emitted('update:modelValue') as string[][]
    expect(emitted[0][0]).toEqual(['女性', '古风'])
  })

  it('回车创建新标签', async () => {
    const wrapper = mount(TagInput, {
      props: { modelValue: [], suggestions: SUGGESTIONS },
    })
    await wrapper.find('input').setValue('新标签')
    await wrapper.find('input').trigger('keyup.enter')
    const emitted = wrapper.emitted('update:modelValue') as string[][]
    expect(emitted[0][0]).toEqual(['新标签'])
  })

  it('点已选标签的叉移除', async () => {
    const wrapper = mount(TagInput, {
      props: { modelValue: ['女性', '古风'], suggestions: SUGGESTIONS },
    })
    await wrapper.findAll('.picked-tag button')[0].trigger('click')
    const emitted = wrapper.emitted('update:modelValue') as string[][]
    expect(emitted[0][0]).toEqual(['古风'])
  })

  it('重复添加同一个标签被忽略', async () => {
    const wrapper = mount(TagInput, {
      props: { modelValue: ['女性'], suggestions: SUGGESTIONS },
    })
    await wrapper.find('input').setValue('女性')
    await wrapper.find('input').trigger('keyup.enter')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
})
