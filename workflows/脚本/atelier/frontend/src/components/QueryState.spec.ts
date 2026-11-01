import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import QueryState from './QueryState.vue'

describe('QueryState', () => {
  it('错误态给出信息与重试入口', async () => {
    const wrapper = mount(QueryState, {
      props: { error: new Error('后端 500') },
    })
    expect(wrapper.get('[role="alert"]').text()).toContain('加载失败')
    expect(wrapper.text()).toContain('后端 500')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('loading / empty / 默认插槽三态互斥', () => {
    const loading = mount(QueryState, { props: { loading: true } })
    expect(loading.text()).toContain('加载中')

    const empty = mount(QueryState, { props: { empty: true, emptyText: '没有记录' } })
    expect(empty.text()).toContain('没有记录')

    const content = mount(QueryState, {
      props: { empty: false },
      slots: { default: '<p>数据内容</p>' },
    })
    expect(content.text()).toContain('数据内容')
  })
})
