import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TagCloud from './TagCloud.vue'
import type { TagRow } from '../api/types'

function tag(id: number, name: string, count: number): TagRow {
  return { id, name, color: '#5b8fb9', usage_count: 0, prompt_count: count }
}

const TAGS: TagRow[] = [
  tag(1, '有图', 5),
  tag(2, '零计数', 0),
  tag(3, '另一个有图', 2),
]

describe('TagCloud', () => {
  it('只展示有计数的标签 —— 库里有 80 多个孤儿标签，全铺出来会把有用的淹掉', () => {
    const wrapper = mount(TagCloud, {
      props: { tags: TAGS, selected: [], match: 'all' },
    })
    const names = wrapper.findAll('.tag').map((n) => n.text())
    expect(names).toHaveLength(2)
    expect(names.join()).toContain('有图')
    expect(names.join()).not.toContain('零计数')
  })

  it('已选中的零计数标签仍然显示 —— 否则用户选中后它就消失，取消不掉了', () => {
    const wrapper = mount(TagCloud, {
      props: { tags: TAGS, selected: [2], match: 'all' },
    })
    const names = wrapper.findAll('.tag').map((n) => n.text())
    expect(names.join()).toContain('零计数')
    expect(names).toHaveLength(3)
  })

  it('点击标签 emit toggle 并带上 id', async () => {
    const wrapper = mount(TagCloud, {
      props: { tags: TAGS, selected: [], match: 'all' },
    })
    await wrapper.findAll('.tag')[0].trigger('click')
    expect(wrapper.emitted('toggle')?.[0]).toEqual([1])
  })

  it('切换匹配方式 emit update:match', async () => {
    const wrapper = mount(TagCloud, {
      props: { tags: TAGS, selected: [], match: 'all' },
    })
    await wrapper.findAll('.mode-switch .btn')[1].trigger('click')
    expect(wrapper.emitted('update:match')?.[0]).toEqual(['any'])
  })

  it('当前匹配方式对应按钮高亮', () => {
    const wrapper = mount(TagCloud, {
      props: { tags: TAGS, selected: [], match: 'any' },
    })
    const buttons = wrapper.findAll('.mode-switch .btn')
    expect(buttons[0].classes()).not.toContain('active')
    expect(buttons[1].classes()).toContain('active')
  })

  it('没有可用标签时显示占位文案', () => {
    const wrapper = mount(TagCloud, {
      props: { tags: [], selected: [], match: 'all', emptyText: '暂无带图片的标签' },
    })
    expect(wrapper.find('.empty-state').text()).toBe('暂无带图片的标签')
  })
})
