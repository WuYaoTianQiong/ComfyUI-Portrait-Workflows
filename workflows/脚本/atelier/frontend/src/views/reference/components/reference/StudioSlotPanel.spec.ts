/**
 * 合成台槽位卡「图片 / 文本」分段控件单测（P2 替代态，方案 §8 P2）。
 *
 * 覆盖：
 * - image 模式：图墙 + 头部「图片 / 文本」分段，点「文本」emit update:mode；
 * - text 模式：隐藏图墙与图片入口，显示「文本模式…」与「去填写」；
 * - 空态：保留原选图入口，并增加「改用文本」；
 * - 纯受控：组件只 emit，不自行改 mode。
 */

import { mount } from '@vue/test-utils'
import { h } from 'vue'
import { describe, expect, it } from 'vitest'

import type { RecipeSlotMode } from '../../../../composables/recipeTextFragments'

import StudioSlotPanel from './StudioSlotPanel.vue'
import type { SlotSelectedItem } from './slotView'

function item(key: string, name = '条目'): SlotSelectedItem {
  return {
    key,
    name,
    thumb: `/api/reference/items/${key}/image?kind=thumb`,
    image: `/api/reference/items/${key}/image`,
  }
}

function mountPanel(
  mode: RecipeSlotMode,
  items: SlotSelectedItem[] = [],
  label = '服装',
) {
  return mount(StudioSlotPanel, {
    props: {
      label,
      slotKey: 'costume',
      items,
      hint: `＋ 选${label}（可多选）`,
      mode,
    },
  })
}

describe('StudioSlotPanel 图片 / 文本模式', () => {
  it('image 模式 + 已选图：渲染图墙与分段控件', () => {
    const wrapper = mountPanel('image', [item('c1', '白衬衫')])

    expect(wrapper.find('[data-testid="studio-slot-media-costume"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="studio-slot-thumb-costume"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="studio-slot-mode-costume-image"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="studio-slot-mode-costume-text"]').exists()).toBe(true)
    expect(
      wrapper.get('[data-testid="studio-slot-mode-costume-image"]').attributes('aria-pressed'),
    ).toBe('true')
  })

  it('点「文本」只 emit update:mode（不自行切换）', async () => {
    const wrapper = mountPanel('image', [item('c1', '白衬衫')])

    await wrapper.get('[data-testid="studio-slot-mode-costume-text"]').trigger('click')

    expect(wrapper.emitted('update:mode')).toEqual([['text']])
  })

  it('text 模式：隐藏图墙 / 图片入口，显示说明与「去填写」', () => {
    const wrapper = mountPanel('text', [item('c1', '白衬衫')])

    expect(wrapper.find('[data-testid="studio-slot-media-costume"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="studio-slot-thumb-costume"]').exists()).toBe(false)
    // text 模式不提供「更换 / 继续选」这类图片入口
    expect(wrapper.find('[data-testid="studio-slot-change-costume"]').exists()).toBe(false)

    const textBlock = wrapper.get('[data-testid="studio-slot-text-costume"]')
    expect(textBlock.text()).toContain('文本模式：请在下方「文本补充」卡填写 人物服饰 类')
    expect(textBlock.find('[data-testid="studio-slot-fill-text-costume"]').exists()).toBe(true)
  })

  it('点「去填写」emit fillText', async () => {
    const wrapper = mountPanel('text', [])

    await wrapper.get('[data-testid="studio-slot-fill-text-costume"]').trigger('click')

    expect(wrapper.emitted('fillText')).toHaveLength(1)
  })

  it('空态：保留选图入口，并增加「改用文本」', async () => {
    const wrapper = mountPanel('empty', [])

    expect(wrapper.find('[data-testid="studio-slot-select-costume"]').exists()).toBe(true)
    const switchButton = wrapper.get('[data-testid="studio-slot-use-text-costume"]')
    expect(switchButton.text()).toBe('改用文本')

    await switchButton.trigger('click')
    expect(wrapper.emitted('update:mode')).toEqual([['text']])
  })
})

describe('StudioSlotPanel 底部按钮同排', () => {
  const footerSlot = () => h('button', { class: 'slot-upload' }, '＋ 上传本地图')

  function mountWithFooter(mode: RecipeSlotMode, items: SlotSelectedItem[] = []) {
    return mount(StudioSlotPanel, {
      props: {
        label: '服装',
        slotKey: 'costume',
        items,
        hint: '＋ 选服装（可多选）',
        mode,
      },
      slots: { footer: footerSlot },
    })
  }

  it('已选态：「继续选」与「上传本地图」在同一个 footer 容器内', () => {
    const wrapper = mountWithFooter('image', [item('c1', '白衬衫')])
    const footer = wrapper.get('.slot-panel__footer')

    expect(footer.text()).toContain('＋ 继续选服装')
    expect(footer.text()).toContain('＋ 上传本地图')
  })

  it('空态：「改用文本」与「上传本地图」在同一个 footer 容器内', () => {
    const wrapper = mountWithFooter('empty')
    const footer = wrapper.get('.slot-panel__footer--empty')

    expect(footer.text()).toContain('改用文本')
    expect(footer.text()).toContain('＋ 上传本地图')
  })
})