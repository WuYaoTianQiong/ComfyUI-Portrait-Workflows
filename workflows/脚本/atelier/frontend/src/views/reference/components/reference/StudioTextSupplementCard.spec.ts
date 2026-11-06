/**
 * 「文本补充」卡组件单测（方案 §5.5 / §4.1）。
 *
 * 覆盖任务要求的最小用例集：
 * 1. 默认折叠（不占高度）+ 卡头「已选 N 条」；
 * 2. 展开后两列 / 八类行；
 * 3. 删除 chip 回传整份新表；
 * 4. 单类上限 2 条时「选择碎片」禁用；
 * 5. 负向输入 emit；
 * 6. 画风技术碎片 → 父级锁定（显示锁定说明 / 删除与回填都通过 emit 交回）。
 *
 * 碎片弹层只做「确认回填」通路验证：fetch 用空分组 stub，不依赖真实后端。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createEmptyRecipeTextFragments,
} from '../../../../composables/recipeTextFragments'
import type {
  RecipeSlotModes,
  RecipeSupplementFlags,
  RecipeTextFragments,
} from '../../../../composables/recipeTextFragments'

import StudioFragmentPicker from './StudioFragmentPicker.vue'
import StudioTextSupplementCard from './StudioTextSupplementCard.vue'

/** 空表 + 覆盖，避免每个用例重复写八类。 */
function fragmentsWith(overrides: Partial<RecipeTextFragments> = {}): RecipeTextFragments {
  return { ...createEmptyRecipeTextFragments(), ...overrides }
}

const IMAGE_MODES: RecipeSlotModes = {
  portrait: 'image',
  costume: 'image',
  pose: 'image',
}

function mountCard(
  options: {
    fragments?: RecipeTextFragments
    negative?: string
    styleLocked?: boolean
    slotModes?: RecipeSlotModes
    supplementFlags?: RecipeSupplementFlags
    recipeSourceName?: string
  } = {},
) {
  return mount(StudioTextSupplementCard, {
    props: {
      modelValue: options.fragments ?? createEmptyRecipeTextFragments(),
      negativePrompt: options.negative ?? '',
      safeMode: true,
      styleLocked: options.styleLocked ?? false,
      slotModes: options.slotModes ?? IMAGE_MODES,
      supplementFlags: options.supplementFlags,
      recipeSourceName: options.recipeSourceName,
    },
  })
}

beforeEach(() => {
  // 弹层打开时只请求当前类型；空分组足够验证回填通路。
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ grouped: {}, fragment_count: 0 }),
      text: async () => '',
    })),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('折叠与已选计数', () => {
  it('默认折叠：卡内不渲染，卡头显示已选 0 条', () => {
    const wrapper = mountCard()

    expect(wrapper.find('[data-testid="studio-text-supplement-body"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="studio-text-supplement-count"]').text()).toBe('已选 0 条')
    expect(wrapper.get('[data-testid="studio-text-supplement-toggle"]').attributes('aria-expanded')).toBe(
      'false',
    )
  })

  it('已选 N 条按八类总条数统计', () => {
    const wrapper = mountCard({
      fragments: fragmentsWith({
        人物面部: [
          { type: '人物面部', content: '黑色短发' },
          { type: '人物面部', content: '圆脸' },
        ],
        场景环境: [{ type: '场景环境', content: '黄昏街道' }],
      }),
    })

    expect(wrapper.get('[data-testid="studio-text-supplement-count"]').text()).toBe('已选 3 条')
  })

  it('点击卡头展开：两列 + 八类行都渲染', async () => {
    const wrapper = mountCard()
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')

    expect(wrapper.get('[data-testid="studio-text-supplement-toggle"]').attributes('aria-expanded')).toBe(
      'true',
    )
    expect(wrapper.find('[data-testid="studio-supplement-column-slot"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="studio-supplement-column-modifier"]').exists()).toBe(true)

    for (const type of [
      '人物面部',
      '人物身材',
      '人物服饰',
      '姿态动作',
      '拍摄视角',
      '场景环境',
      '光影色调',
      '画风技术',
    ]) {
      expect(wrapper.find(`[data-testid="studio-supplement-row-${type}"]`).exists(), type).toBe(true)
    }
  })
})

describe('已选 chips 与单类上限', () => {
  it('删除 chip 回传整份新表（只少一条，其余类不动）', async () => {
    const wrapper = mountCard({
      fragments: fragmentsWith({
        人物面部: [
          { type: '人物面部', content: '黑色短发' },
          { type: '人物面部', content: '圆脸' },
        ],
        人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
      }),
    })
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')
    await wrapper.get('[data-testid="studio-supplement-chip-人物面部-0"]').trigger('click')

    const payloads = wrapper.emitted('update:modelValue')
    expect(payloads).toHaveLength(1)
    const next = payloads?.[0]?.[0] as RecipeTextFragments
    expect(next.人物面部).toEqual([{ type: '人物面部', content: '圆脸' }])
    expect(next.人物服饰).toEqual([{ type: '人物服饰', content: '白色衬衫' }])
  })

  it('单类已满 2 条：「选择碎片」禁用并显示 n/2 条 · x 字', async () => {
    const wrapper = mountCard({
      fragments: fragmentsWith({
        人物面部: [
          { type: '人物面部', content: 'abcdef' },
          { type: '人物面部', content: 'ghij' },
        ],
      }),
    })
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')

    const pick = wrapper.get('[data-testid="studio-supplement-pick-人物面部"]')
    expect(pick.attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="studio-supplement-row-人物面部"]').text()).toContain(
      '2/2 条 · 10 字',
    )
  })
})

describe('负向提示词', () => {
  it('输入即 emit 原文（不做 trim，交给提交体统一处理）', async () => {
    const wrapper = mountCard()
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')

    const textarea = wrapper.get('[data-testid="studio-negative-prompt"]')
    // 组件是受控的：value 由 prop 决定，这里验证事件载荷即可。
    await textarea.setValue('低质量，多余手指')

    expect(wrapper.emitted('update:negativePrompt')?.at(-1)).toEqual(['低质量，多余手指'])
  })

  it('常显说明「最终负向 = 后端自动抽取 + 你填写的内容」', async () => {
    const wrapper = mountCard()
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')

    expect(wrapper.get('[data-testid="studio-negative-hint"]').text()).toBe(
      '最终负向 = 后端自动抽取 + 你填写的内容',
    )
  })
})

describe('画风技术碎片与画风锁定', () => {
  it('styleLocked=true 时画风技术行显示「已用碎片描述画风」', async () => {
    const wrapper = mountCard({
      fragments: fragmentsWith({
        画风技术: [{ type: '画风技术', content: '胶片质感' }],
      }),
      styleLocked: true,
    })
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')

    expect(wrapper.get('[data-testid="studio-supplement-style-lock"]').text()).toBe(
      '已用碎片描述画风',
    )
  })

  it('删除画风技术 chip 回传空数组（父级据此解除锁定）', async () => {
    const wrapper = mountCard({
      fragments: fragmentsWith({
        画风技术: [{ type: '画风技术', content: '胶片质感' }],
      }),
      styleLocked: true,
    })
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')
    await wrapper.get('[data-testid="studio-supplement-chip-画风技术-0"]').trigger('click')

    const next = wrapper.emitted('update:modelValue')?.[0]?.[0] as RecipeTextFragments
    expect(next.画风技术).toEqual([])
  })

  it('弹层确认回填画风技术碎片 → emit 带 type/content（父级据此锁定画风）', async () => {
    const wrapper = mountCard({
      fragments: fragmentsWith({
        人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
      }),
    })
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')
    await wrapper.get('[data-testid="studio-supplement-pick-画风技术"]').trigger('click')
    await flushPromises()

    wrapper
      .findComponent(StudioFragmentPicker)
      .vm.$emit('confirm', [{ type: '画风技术', content: '胶片质感' }])

    const next = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as RecipeTextFragments
    expect(next.画风技术).toEqual([{ type: '画风技术', content: '胶片质感' }])
    expect(next.人物服饰).toEqual([{ type: '人物服饰', content: '白色衬衫' }])
  })
})
describe('P2 / P4 槽位「补充 / 替代」开关', () => {
  it('image 模式默认关闭：显示「未生效」，可打开补充', async () => {
    const wrapper = mountCard({
      slotModes: IMAGE_MODES,
      fragments: fragmentsWith({
        人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
      }),
    })
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')

    expect(wrapper.get('[data-testid="studio-supplement-mode-人物服饰"]').text()).toBe('未生效')
    expect(wrapper.get('[data-testid="studio-supplement-toggle-人物服饰"]').text()).toBe(
      '用文本替代',
    )

    const flag = wrapper.get('[data-testid="studio-supplement-flag-toggle-人物服饰"]')
    expect(flag.text()).toBe('作为补充')
    await flag.trigger('click')
    expect(wrapper.emitted('update:supplement')).toEqual([['costume', true]])
  })

  it('image 模式 + 补充开启：显示「补充」与跨源警告', async () => {
    const wrapper = mountCard({
      slotModes: IMAGE_MODES,
      fragments: fragmentsWith({
        人物服饰: [{ type: '人物服饰', content: '白色衬衫' }],
      }),
      supplementFlags: { portrait: false, costume: true, pose: false },
    })
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')

    expect(wrapper.get('[data-testid="studio-supplement-mode-人物服饰"]').text()).toBe('补充')
    expect(
      wrapper.get('[data-testid="studio-supplement-flag-toggle-人物服饰"]').text(),
    ).toBe('补充已开')
    expect(
      wrapper.find('[data-testid="studio-supplement-warning-人物服饰"]').exists(),
    ).toBe(true)
  })

  it('text 模式：显示「替代」与「改回图片」，点击只 emit 交回父级', async () => {
    const wrapper = mountCard({
      slotModes: { portrait: 'image', costume: 'text', pose: 'image' },
    })
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')

    expect(wrapper.get('[data-testid="studio-supplement-mode-人物服饰"]').text()).toBe('替代')

    const toggle = wrapper.get('[data-testid="studio-supplement-toggle-人物服饰"]')
    expect(toggle.text()).toBe('改回图片')
    await toggle.trigger('click')

    // 组件不自行改 mode / 不删碎片：父级校验通过后才更新真源。
    expect(wrapper.emitted('update:slotMode')).toEqual([['costume', 'image']])
  })

  it('切到文本时 emit update:slotMode(costume, text)', async () => {
    const wrapper = mountCard({ slotModes: IMAGE_MODES })
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')
    await wrapper.get('[data-testid="studio-supplement-toggle-人物服饰"]').trigger('click')

    expect(wrapper.emitted('update:slotMode')).toEqual([['costume', 'text']])
  })

  it('人像槽只在主类型行（人物面部）出现一个开关', async () => {
    const wrapper = mountCard({ slotModes: IMAGE_MODES })
    await wrapper.get('[data-testid="studio-text-supplement-toggle"]').trigger('click')

    expect(wrapper.find('[data-testid="studio-supplement-toggle-人物面部"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="studio-supplement-toggle-人物身材"]').exists()).toBe(false)
  })
})

describe('跨源实验来源', () => {
  it('recipeSourceName 以「跨源实验」开头时显示实验徽标', () => {
    const wrapper = mountCard({ recipeSourceName: '跨源实验 · scene·outfit' })

    expect(wrapper.get('[data-testid="studio-atomic-experiment"]').text()).toContain('跨源实验')
  })

  it('普通同源来源不显示实验徽标', () => {
    const wrapper = mountCard({ recipeSourceName: '纯白背景·正装衬衫' })

    expect(wrapper.find('[data-testid="studio-atomic-experiment"]').exists()).toBe(false)
  })
})