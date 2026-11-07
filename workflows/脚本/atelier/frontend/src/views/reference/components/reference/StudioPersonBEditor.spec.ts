/**
 * 人物 B 文字设定编辑器单测（v1.5）。
 *
 * 只验证受控行为：变体切换 / 自由文字 / 碎片移除都通过 `update:variants`
 * 交回页面，不在组件内改 props；新增 / 删除变体走独立事件（由草稿单例执行）。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import {
  createEmptyPersonBVariant,
  createEmptyRecipeTextFragments,
} from '../../../../composables/recipeTextFragments'
import type { RecipePersonBVariant } from '../../../../composables/recipeTextFragments'

import StudioPersonBEditor from './StudioPersonBEditor.vue'

function variantWithFace(id: string, content: string): RecipePersonBVariant {
  const variant = createEmptyPersonBVariant(id)
  variant.fragments = {
    ...createEmptyRecipeTextFragments(),
    人物面部: [{ type: '人物面部', content, person: 'B' }],
  }
  return variant
}

function mountEditor(
  variants: RecipePersonBVariant[],
  activeIndex = 0,
  disabled = false,
  portraitCount?: number,
) {
  return mount(StudioPersonBEditor, {
    props: { variants, activeIndex, safeMode: true, disabled, portraitCount },
  })
}

describe('StudioPersonBEditor', () => {
  it('渲染三行 B 专属碎片与变体页签', () => {
    const wrapper = mountEditor([variantWithFace('b-1', '鹅蛋脸'), variantWithFace('b-2', '圆脸')])
    expect(wrapper.text()).toContain('人物 B · 文字设定')
    expect(wrapper.text()).toContain('2 组变体')
    for (const type of ['人物面部', '人物身材', '人物服饰']) {
      expect(wrapper.find(`[data-testid="studio-person-b-row-${type}"]`).exists()).toBe(true)
    }
    expect(wrapper.find('[data-testid="studio-person-b-tab-0"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="studio-person-b-tab-1"]').exists()).toBe(true)
  })

  it('自由文字输入回传整份新变体（不原地改 props）', async () => {
    const variants = [variantWithFace('b-1', '鹅蛋脸')]
    const wrapper = mountEditor(variants)
    await wrapper.find('[data-testid="studio-pair-b-text"]').setValue('年龄与人物 A 相近')

    const emitted = wrapper.emitted('update:variants')?.[0]?.[0] as RecipePersonBVariant[]
    expect(emitted).toHaveLength(1)
    expect(emitted[0].freeText).toBe('年龄与人物 A 相近')
    expect(variants[0].freeText).toBe('')
  })

  it('移除 B 碎片后该类清空，其余字段保持不变', async () => {
    const variants = [variantWithFace('b-1', '鹅蛋脸')]
    const wrapper = mountEditor(variants)
    await wrapper.find('[data-testid="studio-person-b-chip-人物面部-0"]').trigger('click')

    const emitted = wrapper.emitted('update:variants')?.[0]?.[0] as RecipePersonBVariant[]
    expect(emitted[0].fragments.人物面部).toEqual([])
    expect(emitted[0].id).toBe('b-1')
  })

  it('新增 / 删除变体只发事件，由父级草稿单例处理上限与保底', async () => {
    const wrapper = mountEditor([variantWithFace('b-1', '鹅蛋脸')])
    await wrapper.find('[data-testid="studio-person-b-add"]').trigger('click')
    expect(wrapper.emitted('add')).toHaveLength(1)
    // 只有一条时删除按钮禁用，不会发出 remove
    expect(wrapper.find('[data-testid="studio-person-b-remove"]').attributes('disabled')).toBeDefined()
  })

  it('配对数量不等时提示复核；数量相等时不提示', () => {
    const variants = [variantWithFace('b-1', '鹅蛋脸'), variantWithFace('b-2', '圆脸')]

    const uneven = mountEditor(variants, 0, false, 3)
    const notice = uneven.find('[data-testid="studio-person-b-pairing-notice"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('人像 3 张 / B 变体 2 组')
    expect(notice.text()).toContain('复用最后一组')

    const even = mountEditor(variants, 0, false, 2)
    expect(even.find('[data-testid="studio-person-b-pairing-notice"]').exists()).toBe(false)
  })

  it('手动改写提示词时禁用自由文字输入', () => {
    const wrapper = mountEditor([variantWithFace('b-1', '鹅蛋脸')], 0, true)
    expect(
      wrapper.find('[data-testid="studio-pair-b-text"]').attributes('disabled'),
    ).toBeDefined()
    expect(
      wrapper.find('[data-testid="studio-person-b-pick-人物面部"]').attributes('disabled'),
    ).toBeDefined()
  })

  it('已选人物B身份图时，面部/身材入口禁用，服饰仍可编辑', () => {
    const wrapper = mount(StudioPersonBEditor, {
      props: {
        variants: [variantWithFace('b-1', '鹅蛋脸')],
        activeIndex: 0,
        safeMode: true,
        identityImageSelected: true,
        identityImageName: '长发・标准款',
      },
    })
    // 提示说明脸/发型由身份图控制，并带上图名
    expect(wrapper.text()).toContain('由第 4 槽身份图')
    expect(wrapper.text()).toContain('长发・标准款')
    // 后端忽略这两类碎片：入口禁用
    for (const type of ['人物面部', '人物身材']) {
      expect(
        wrapper.find(`[data-testid="studio-person-b-pick-${type}"]`).attributes('disabled'),
      ).toBeDefined()
    }
    // 人物服饰仍走文字，不能被一起禁用
    expect(
      wrapper.find('[data-testid="studio-person-b-pick-人物服饰"]').attributes('disabled'),
    ).toBeUndefined()
  })
})
