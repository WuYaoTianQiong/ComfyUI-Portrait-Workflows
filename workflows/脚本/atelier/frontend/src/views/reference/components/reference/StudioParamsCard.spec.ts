/**
 * 合成台参数卡：画质 chip 的像素标注只在单选比例时可见。
 *
 * 背景：档位文案（`2.0× · 6.3MP · 1648×3824`）是按第一个比例预演的，而提交是
 * 「比例 × 档位」全组合；多比例时把这串数字摆在 chip 上必然和其中几组不符，
 * 所以多选要降级成只显示倍率，并给出"尺寸见生成清单"的提示。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import StudioParamsCard from './StudioParamsCard.vue'

const QUALITY_OPTIONS = [
  { value: '1.0x', label: '原生 1.0× · 1.57MP · 1024×1536' },
  { value: '2.0x', label: '2.0× · 6.3MP · 1648×3824' },
]

function mountCard(ratioSelection: string[]) {
  return mount(StudioParamsCard, {
    props: {
      workflowSelection: [],
      workflows: [],
      selectedRoles: [],
      workflowDefaultPath: '',
      workflowsLoading: false,
      workflowsError: '',
      style: 'none',
      styleOptions: [{ value: 'none', label: '不指定' }],
      qualityEnabled: true,
      qualityOptions: QUALITY_OPTIONS,
      qualitySelection: [],
      orientationEnabled: true,
      aspectRatios: ['2:3', '9:21'],
      ratioSelection,
      followsReferenceSize: false,
      bodyMode: 'costume',
      safeMode: false,
      baseSeed: 100000,
    },
  })
}

function chipTexts(wrapper: ReturnType<typeof mountCard>): string[] {
  return wrapper
    .get('[data-testid="studio-quality-options"]')
    .findAll('button')
    .map((btn) => btn.text())
}

describe('StudioParamsCard 画质 chip 与比例联动', () => {
  it('未选比例：chip 显示完整标注（倍率 · MP · 宽高）', () => {
    const wrapper = mountCard([])

    expect(chipTexts(wrapper)).toEqual([
      '原生 1.0× · 1.57MP · 1024×1536',
      '2.0× · 6.3MP · 1648×3824',
    ])
    expect(wrapper.find('[data-testid="studio-quality-multi-ratio-hint"]').exists()).toBe(false)
  })

  it('单选比例：仍显示完整标注（标注就按这个比例算的）', () => {
    const wrapper = mountCard(['9:21'])

    expect(chipTexts(wrapper)[1]).toBe('2.0× · 6.3MP · 1648×3824')
    expect(wrapper.find('[data-testid="studio-quality-multi-ratio-hint"]').exists()).toBe(false)
  })

  it('多选比例：摘掉像素只留倍率，并提示尺寸见生成清单', () => {
    const wrapper = mountCard(['2:3', '9:21'])

    expect(chipTexts(wrapper)).toEqual(['原生 1.0×', '2.0×'])
    const hint = wrapper.get('[data-testid="studio-quality-multi-ratio-hint"]')
    expect(hint.text()).toContain('2 个比例')
    expect(hint.text()).toContain('生成清单')
  })
})
