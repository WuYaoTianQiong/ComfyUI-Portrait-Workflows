import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PromptDetailPane from './PromptDetailPane.vue'
import type { PromptMatrixApi } from '../composables/usePromptMatrix'

/** 三态测试只渲染未选中分支，横评 API 用最小桩件即可。 */
const matrixStub = {
  enabled: false,
  count: 1,
  paths: [],
  align: 'native',
  lockSeed: true,
  plan: { usable: [], rows: [], count: 1, total: 0, overLimit: false, warnings: [], targetSize: null, negativeEffective: 0 },
  cells: [],
  running: false,
  submitting: false,
  bestPath: '',
  unavailable: {},
  setCount: () => {},
  setEnabled: () => {},
  setPaths: () => {},
  setAlign: () => {},
  submit: () => {},
} as unknown as PromptMatrixApi

/**
 * 详情面板的三态。
 *
 * 回归点：选中一条提示词后，详情还在路上或请求失败时，右侧曾经一律渲染
 * 「选择左侧任意一条提示词」——用户以为提示词丢了，且没有重试入口。
 */
const baseProps = {
  draft: null,
  loading: false,
  error: null,
  dirty: false,
  saving: false,
  classifying: false,
  generating: false,
  workflowPath: '',
  workflows: [],
  quality: '1.0x',
  orientation: 'portrait' as const,
  aspectRatio: '2:3',
  aspectRatios: ['2:3'],
  defaultRatio: '2:3',
  qualityOptions: [],
  caps: { prompt: true, negative: false, negative_effective: false, negative_cfg: null, quality: true, orientation: true },
  wfValidation: undefined,
  generateError: '',
  activeJob: null,
  flatCats: [],
  tags: [],
  linkedCategoryIds: [],
  draftTagList: [],
  shotItems: [],
  matrix: matrixStub,
}

function mountPane(props: Record<string, unknown> = {}) {
  return mount(PromptDetailPane, { props: { ...baseProps, ...props } })
}

describe('PromptDetailPane 详情三态', () => {
  it('未选中任何条目时才提示去左侧选择', () => {
    const wrapper = mountPane()
    expect(wrapper.text()).toContain('选择左侧任意一条提示词')
  })

  it('已选中但详情未到达时显示加载态，不显示未选择空态', () => {
    const wrapper = mountPane({ loading: true })
    expect(wrapper.text()).toContain('正在加载提示词')
    expect(wrapper.text()).not.toContain('选择左侧任意一条提示词')
    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(true)
  })

  it('详情请求失败时显示错误与重试，而不是空态', () => {
    const wrapper = mountPane({ error: new Error('500 数据库暂时不可用') })
    const text = wrapper.text()
    expect(text).toContain('加载失败')
    expect(text).toContain('500 数据库暂时不可用')
    expect(text).not.toContain('选择左侧任意一条提示词')
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })

  it('点击重试向上抛出 retry', async () => {
    const wrapper = mountPane({ error: new Error('500 boom') })
    await wrapper.find('[role="alert"] button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('错误优先于加载：失败后不再停在加载态', () => {
    const wrapper = mountPane({ loading: true, error: new Error('500 boom') })
    expect(wrapper.text()).toContain('加载失败')
    expect(wrapper.text()).not.toContain('正在加载提示词')
  })
})
