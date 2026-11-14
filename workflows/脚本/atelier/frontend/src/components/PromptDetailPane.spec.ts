import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PromptDetailPane from './PromptDetailPane.vue'
import type { PromptMatrixApi } from '../composables/usePromptMatrix'
import type { WorkflowRow } from '../composables/useWorkflows'

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

/** 横评态用到完整详情分支：给一份最小可渲染的 draft。 */
const draft = {
  id: 1,
  name: '测试提示词',
  prompt: '黑色长发，白色连衣裙',
  negative_prompt: '',
  note: '',
  is_favorite: false,
  is_pinned: false,
  rating: 0,
  usage_count: 0,
  steps: null,
  cfg_scale: null,
  sampler: '',
  seed: null,
  model: '',
  categories: [],
  width: null,
  height: null,
  created_at: '',
  updated_at: '',
  last_used_at: '',
  tags: '',
  tags_detail: [],
}

function wf(path: string, name: string): WorkflowRow {
  return {
    path,
    name,
    image_slots: 0,
    caps: { prompt: true, negative: false, negative_effective: false, negative_cfg: null, quality: true, orientation: true },
    params: {
      quality_mode: 'scale',
      orientation_mode: 'swap',
      default_ratio: '2:3',
      aspect_ratios: ['2:3', '3:2'],
    },
    size_preview: {
      '0.5x': { '2:3': { width: 512, height: 768 }, '3:2': { width: 768, height: 512 } },
      '1.0x': { '2:3': { width: 1024, height: 1536 }, '3:2': { width: 1536, height: 1024 } },
    },
  }
}

const A = wf('/wf/a.json', 'A_文生图.json')
const B = wf('/wf/b.json', 'B_文生图.json')

function mountMatrix() {
  return mount(PromptDetailPane, {
    props: {
      ...baseProps,
      draft,
      workflows: [A, B],
      matrix: {
        ...matrixStub,
        enabled: true,
        paths: [A.path, B.path],
        plan: {
          rows: [],
          usable: [
            { path: A.path, ratio: '2:3' },
            { path: B.path, ratio: '2:3' },
          ],
          count: 1,
          total: 2,
          overLimit: false,
          warnings: [],
          targetSize: null,
          negativeEffective: 0,
        },
      } as unknown as PromptMatrixApi,
    },
    global: { stubs: { PromptMatrixStack: true } },
  })
}

describe('PromptDetailPane 横评逐流参数', () => {
  it('横评态按流展示参数行，且不再显示单跑的全局参数', async () => {
    const wrapper = mountMatrix()
    expect(wrapper.findAll('.flow-row')).toHaveLength(2)
    // 两行各有一个比例 + 一个分辨率；单跑那套全局控件在横评态隐藏
    expect(wrapper.findAll('.wf-param-ratio')).toHaveLength(2)
    expect(wrapper.findAll('.wf-param-quality')).toHaveLength(2)
  })

  it('改一行的比例不影响另一行', async () => {
    const wrapper = mountMatrix()

    await wrapper.findAll('.flow-row')[0].find('.wf-param-ratio').setValue('2:3')
    await flushPromises()
    await wrapper.findAll('.flow-row')[1].find('.wf-param-ratio').setValue('2:3')
    await flushPromises()

    await wrapper.findAll('.flow-row')[1].find('.wf-param-ratio').setValue('3:2')
    await flushPromises()

    const rows = wrapper.findAll('.flow-row')
    expect((rows[0].find('.wf-param-ratio').element as HTMLSelectElement).value).toBe('2:3')
    expect((rows[1].find('.wf-param-ratio').element as HTMLSelectElement).value).toBe('3:2')

    // 比例按工作流记忆（模块级缓存），还原以免污染其它用例
    await wrapper.findAll('.flow-row')[1].find('.wf-param-ratio').setValue('2:3')
  })
})
