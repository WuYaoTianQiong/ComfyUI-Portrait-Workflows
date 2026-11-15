/**
 * 姿势卡片管理条单测。
 *
 * 只测「点一下发什么事件、按钮显示什么状态」——落库由页面统一负责，
 * 组件本身不发请求、不改 props，所以这里不需要 mock 网络。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { PoseItem } from '../../../../api/reference'

import PoseManageBar from './PoseManageBar.vue'

function pose(patch: Partial<PoseItem> = {}): PoseItem {
  return {
    id: 'vnccs-miu-main-站姿-A001',
    library: 'pose',
    姿势编号: '',
    姿势名称: 'A001',
    角度: '',
    缩略图: '',
    原图: '',
    检索: '',
    source: 'vnccs',
    usable: false,
    usableNote: 'VNCCS 白模预览：尚未实测，默认不参与出图',
    ...patch,
  } as PoseItem
}

const buttons = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('button')

describe('PoseManageBar', () => {
  it('默认展示来源判定：未标 18+ 显示「安全」，不可用显示「不可用」', () => {
    const wrapper = mount(PoseManageBar, { props: { item: pose() } })
    expect(buttons(wrapper).map((btn) => btn.text())).toEqual(['安全', '不可用'])
  })

  it('点「安全」标为 18+；已是 18+ 时点回安全', async () => {
    const wrapper = mount(PoseManageBar, { props: { item: pose() } })
    await buttons(wrapper)[0].trigger('click')
    expect(wrapper.emitted('patch')?.[0]).toEqual([{ rating: 'nsfw' }])

    await wrapper.setProps({ item: pose({ rating: 'nsfw', nsfw: true }) })
    expect(buttons(wrapper)[0].text()).toBe('18+')
    await buttons(wrapper)[0].trigger('click')
    expect(wrapper.emitted('patch')?.[1]).toEqual([{ rating: 'safe' }])
  })

  it('点「不可用」恢复可用，点「可用」标为不可用', async () => {
    const wrapper = mount(PoseManageBar, { props: { item: pose() } })
    await buttons(wrapper)[1].trigger('click')
    expect(wrapper.emitted('patch')?.[0]).toEqual([{ usable: true }])

    await wrapper.setProps({ item: pose({ usable: true, usableNote: '' }) })
    await buttons(wrapper)[1].trigger('click')
    expect(wrapper.emitted('patch')?.[1]).toEqual([{ usable: false }])
  })

  it('保存中禁用按钮，避免连点打架', () => {
    const wrapper = mount(PoseManageBar, { props: { item: pose(), saving: true } })
    expect(buttons(wrapper).every((btn) => btn.attributes('disabled') !== undefined)).toBe(true)
  })

  it('空卡（分组视图没有图的角度）不渲染管理条', () => {
    const wrapper = mount(PoseManageBar, { props: { item: null } })
    expect(wrapper.find('[data-testid="pose-manage"]').exists()).toBe(false)
  })

  it('不可用原因进 title，鼠标悬停能看到实测结论', () => {
    const wrapper = mount(PoseManageBar, { props: { item: pose() } })
    expect(buttons(wrapper)[1].attributes('title')).toContain('尚未实测')
  })
})
