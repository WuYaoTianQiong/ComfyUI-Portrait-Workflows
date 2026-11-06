/**
 * 提示词分段编辑器单测（P3，方案 §14）。
 *
 * 设计口径：不设「阅读态 / 编辑态」两套 UI，每段默认就是 textarea；
 * 只有产生非空改动时才写入 `prompt_override`。
 *
 * 覆盖：
 * - 自动生成：textareas 直接展示后端文本，状态为「自动生成」；
 * - 改任意一段：emit 完整原文，状态切「已手动修改」并出现恢复按钮；
 * - 外部清空：回到自动生成并刷新 textareas；
 * - 手动修改期间 prompt 变化不覆盖用户内容；
 * - 文本槽来源提示、空内容警告、无顶部目录 / 编辑按钮。
 */

import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import StudioPromptEditor from './StudioPromptEditor.vue'
import type { RecipeSupplementFlags } from '../../../../composables/recipeTextFragments'

const PROMPT = `请根据提供的 3 张参考图，生成一张完整的真实人物照片：
• 人物：图1中的人物，保持其脸型、五官一致。
• 服装：让人物穿上图2中展示的整套服装。
• 姿势：严格复现图3中人体模型的身体姿态。
• 拍摄视角：低角度仰拍
• 补充要求：暖色灯光
画面中没有任何文字、标志或水印。`

beforeEach(() => {
  // jsdom 没有布局，scrollIntoView / scrollHeight 需要兜底。
  Element.prototype.scrollIntoView = vi.fn()
})

function mountEditor(
  options: {
    prompt?: string
    value?: string | null
    slotModes?: Record<string, string>
    supplementFlags?: RecipeSupplementFlags
  } = {},
) {
  return mount(StudioPromptEditor, {
    props: {
      prompt: options.prompt ?? PROMPT,
      modelValue: options.value ?? null,
      slotModes: options.slotModes,
      supplementFlags: options.supplementFlags,
    },
  })
}

describe('默认即可编辑', () => {
  it('每段直接渲染 textarea（含开头 / 结尾），状态为自动生成', () => {
    const wrapper = mountEditor()

    expect(wrapper.findAll('textarea')).toHaveLength(7)
    expect(wrapper.get('[data-testid="studio-prompt-auto-badge"]').text()).toBe('自动生成')
    expect(wrapper.find('[data-testid="studio-prompt-restore"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="studio-prompt-segment-input-bullet-0"]').element).toHaveProperty(
      'value',
      '图1中的人物，保持其脸型、五官一致。',
    )
  })

  it('不再有顶部目录 chips，也没有「编辑」按钮', () => {
    const wrapper = mountEditor()

    expect(wrapper.find('[data-testid="studio-prompt-overview"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid^="studio-prompt-overview-"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-testid^="studio-prompt-edit-"]')).toHaveLength(0)
  })

  it('文本槽的来源提示写成「文本替代」；image 槽默认写「图片」', () => {
    const wrapper = mountEditor({ slotModes: { portrait: 'text' } })

    expect(wrapper.get('[data-testid="studio-prompt-segment-source-bullet-0"]').text()).toBe('文本替代')
    expect(wrapper.get('[data-testid="studio-prompt-segment-source-bullet-1"]').text()).toBe('图片')
  })

  it('image 槽打开补充后才写「图片 + 补充碎片」', () => {
    const wrapper = mountEditor({
      slotModes: { portrait: 'image', costume: 'image' },
      supplementFlags: { portrait: true, costume: false, pose: false },
    })

    expect(wrapper.get('[data-testid="studio-prompt-segment-source-bullet-0"]').text()).toBe(
      '图片 + 补充碎片',
    )
    expect(wrapper.get('[data-testid="studio-prompt-segment-source-bullet-1"]').text()).toBe('图片')
  })
})

describe('直接编辑即进入手动提交', () => {
  it('改一段后 emit 完整原文，状态切到已手动修改', async () => {
    const wrapper = mountEditor()
    const input = wrapper.get('[data-testid="studio-prompt-segment-input-bullet-0"]')

    await input.setValue('一位短发少女')

    const emitted = wrapper.emitted('update:modelValue')
    const latest = String(emitted?.[emitted.length - 1]?.[0] ?? '')
    expect(latest).toContain('• 人物：一位短发少女')
    expect(latest).toContain('• 服装：让人物穿上图2中展示的整套服装。')

    // 模拟父级 v-model 回流
    await wrapper.setProps({ modelValue: latest })
    expect(wrapper.get('[data-testid="studio-prompt-dirty-badge"]').text()).toBe('已手动修改')
    expect(wrapper.find('[data-testid="studio-prompt-restore"]').exists()).toBe(true)
  })

  it('点「恢复自动生成」emit null，随后回到自动文本', async () => {
    const wrapper = mountEditor({ value: PROMPT })

    await wrapper.get('[data-testid="studio-prompt-restore"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')?.[0]?.[0]).toBeNull()
    await wrapper.setProps({ modelValue: null })
    expect(wrapper.get('[data-testid="studio-prompt-auto-badge"]').text()).toBe('自动生成')
    expect(wrapper.get('[data-testid="studio-prompt-segment-input-bullet-0"]').element).toHaveProperty(
      'value',
      '图1中的人物，保持其脸型、五官一致。',
    )
  })

  it('未修改时跟随后端预览刷新', async () => {
    const wrapper = mountEditor()

    await wrapper.setProps({ prompt: '新开头\n• 人物：新的自动人物\n新结尾' })

    expect(wrapper.get('[data-testid="studio-prompt-segment-input-head"]').element).toHaveProperty(
      'value',
      '新开头',
    )
    expect(wrapper.get('[data-testid="studio-prompt-segment-input-bullet-0"]').element).toHaveProperty(
      'value',
      '新的自动人物',
    )
  })

  it('已手动修改时，prompt 变化不覆盖用户内容', async () => {
    const wrapper = mountEditor({ value: PROMPT })

    await wrapper.setProps({ prompt: '全新的自动提示词' })

    expect(wrapper.get('[data-testid="studio-prompt-segment-input-bullet-0"]').element).toHaveProperty(
      'value',
      '图1中的人物，保持其脸型、五官一致。',
    )
    expect(wrapper.get('[data-testid="studio-prompt-mode-hint"]').text()).toContain(
      '素材或碎片变化不会覆盖它',
    )
  })

  it('手动内容全空时显示空内容警告', () => {
    const wrapper = mountEditor({ value: '' })

    expect(wrapper.get('[data-testid="studio-prompt-manual-empty"]').text()).toContain(
      '手动改写内容为空',
    )
  })
})

describe('加载 / 错误 / 空态', () => {
  it('loading 时只显示加载文案', () => {
    const wrapper = mount(StudioPromptEditor, {
      props: { prompt: PROMPT, modelValue: null, loading: true },
    })

    expect(wrapper.find('[data-testid="studio-prompt-loading"]').exists()).toBe(true)
    expect(wrapper.findAll('textarea')).toHaveLength(0)
  })

  it('error 时显示原因与重试入口', async () => {
    const wrapper = mount(StudioPromptEditor, {
      props: { prompt: '', modelValue: null, error: '后端 500' },
    })

    expect(wrapper.get('[data-testid="studio-prompt-error"]').text()).toBe('后端 500')
    await wrapper.get('[data-testid="studio-prompt-retry"]').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('没有提示词时显示三槽占位', () => {
    const wrapper = mountEditor({ prompt: '' })

    expect(wrapper.get('[data-testid="studio-prompt-empty"]').text()).toContain('三槽均未选择')
    expect(wrapper.findAll('textarea')).toHaveLength(0)
  })
})
