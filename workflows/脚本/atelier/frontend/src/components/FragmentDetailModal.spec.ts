import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import FragmentDetailModal from './FragmentDetailModal.vue'

/**
 * α 之后碎片统一从 prompts 解析，编辑一律跳提示词页。
 * 这里断言的是"出口给得对"：有 promptId 就给「编辑来源提示词」，没有就不给。
 */
const base = {
  type: '人物面部',
  content: '正脸，柔和光线',
  promptName: '示例提示词',
  dupCount: 1,
}

function mountModal(fragment: Record<string, unknown>) {
  return mount(FragmentDetailModal, {
    props: { open: true, fragment: { ...base, ...fragment } as never },
    global: { stubs: { teleport: true } },
  })
}

function buttonTexts(wrapper: ReturnType<typeof mountModal>) {
  return wrapper.findAll('.meta button').map((b) => b.text())
}

describe('FragmentDetailModal 编辑出口', () => {
  it('有 promptId：给「编辑来源提示词」，点了带 promptId 出去', async () => {
    const wrapper = mountModal({ source: 'prompt', promptId: 7 })
    expect(buttonTexts(wrapper)).toEqual(['✎ 编辑来源提示词'])

    await wrapper.find('.meta button').trigger('click')
    expect(wrapper.emitted('jump')).toEqual([[7, '人物面部']])
  })

  it('没有 promptId（自定义碎片）时不给按钮', () => {
    const wrapper = mountModal({ source: 'custom', promptId: null })
    expect(buttonTexts(wrapper)).toEqual([])
  })

  it('同一段散落在多条提示词里时明确提示只改当前这条', () => {
    const wrapper = mountModal({ source: 'prompt', promptId: 7, dupCount: 3 })
    expect(wrapper.text()).toContain('改其中一条不会影响其它条')
  })
})
