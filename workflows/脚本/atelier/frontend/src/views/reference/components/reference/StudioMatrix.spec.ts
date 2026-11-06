/**
 * 合成台「生成清单」组件单测（方案 §5 M3）。
 *
 * 三条验收：
 * 1. 3 × 2 × 3 槽位、1 工作流 × 1 尺寸 → 18 行，计数文本 `18 / 上限 100`；
 * 2. total = 103 且 overLimit → 根节点 `is-over`、超限区含「减少」、进度条不超过 100%；
 * 3. groups = [] → 显示空态且没有任何行。
 *
 * 数据全部用真实的 `buildBatchGroups()` 结果构造，不 mock 组件、不请求后端。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { CostumeItem, PortraitItem, PoseItem } from '../../../../api/reference'
import type { StudioWorkflowOption } from '../../../../composables/useReferenceRecipe'
import { buildBatchGroups } from '../../../../composables/useReferenceRecipe'

import StudioMatrix from './StudioMatrix.vue'

/** 直接复用组件声明的 props 类型，避免测试契约与实现漂移。 */
type StudioMatrixProps = InstanceType<typeof StudioMatrix>['$props']

// ---------------------------------------------------------------------------
// 真实数据工厂（字段口径与 slotView.spec.ts 一致）
// ---------------------------------------------------------------------------

function portrait(id: string, name: string): PortraitItem {
  return {
    id,
    分区: '',
    发长: '',
    发型名称: name,
    标题: name,
    宽: 0,
    高: 0,
    字节数: 0,
    精选: false,
    热门: false,
    缩略图: `/api/reference/items/portrait/${id}/image?kind=thumb`,
    原图: '',
    检索: '',
  }
}

function costume(id: string, name: string): CostumeItem {
  return {
    id,
    分类: '',
    服装名称: name,
    标签: [],
    关键词: '',
    缩略图: `/api/reference/items/costume/${id}/image?kind=thumb`,
    预览图: '',
    原图: '',
    检索: '',
  }
}

function pose(id: string, name: string): PoseItem {
  return {
    id,
    体系: '',
    姿势编号: '',
    分类: '',
    姿势名称: name,
    角度: '',
    缩略图: `/api/reference/items/pose/${id}/image?kind=thumb`,
    原图: '',
    检索: '',
  }
}

function workflow(path: string, name: string): StudioWorkflowOption {
  return {
    path,
    name,
    source: 'library',
    relPath: path,
    imageSlots: 3,
    inputCount: 3,
    recommended: false,
  }
}

function createProps(overrides: Partial<StudioMatrixProps> = {}): StudioMatrixProps {
  return {
    groups: [],
    total: 0,
    limit: 100,
    overLimit: false,
    limitMessage: '',
    slotCounts: { portrait: 0, costume: 0, pose: 0 },
    workflowCount: 1,
    qualityCount: 1,
    ratioCount: 1,
    workflows: [],
    poseUseDepth: false,
    activeSlotCount: 0,
    ...overrides,
  }
}

function mountMatrix(overrides: Partial<StudioMatrixProps> = {}) {
  return mount(StudioMatrix, { props: createProps(overrides) })
}

function progressPercentOf(wrapper: ReturnType<typeof mount>): number {
  const style = wrapper.get('[data-testid="studio-matrix-progress-fill"]').attributes('style') ?? ''
  const matched = /width:\s*([\d.]+)%/.exec(style)
  return matched ? Number(matched[1]) : Number.NaN
}

// ---------------------------------------------------------------------------
// 用例
// ---------------------------------------------------------------------------

describe('StudioMatrix 生成清单', () => {
  it('3 × 2 × 3 槽位、1 工作流 × 1 尺寸渲染 18 行，计数为 18 / 上限 100', () => {
    const groups = buildBatchGroups({
      portrait: [portrait('p1', '人像A'), portrait('p2', '人像B'), portrait('p3', '人像C')],
      costume: [costume('c1', '服装B'), costume('c2', '服装D')],
      pose: [pose('s1', '姿势C'), pose('s2', '姿势E'), pose('s3', '姿势F')],
      workflows: ['workflows/qwen.json'],
      qualities: ['1024'],
      ratios: ['16:9'],
      qualityEnabled: true,
      orientationEnabled: true,
      baseSeed: 100000,
    })

    const wrapper = mountMatrix({
      groups,
      total: groups.length,
      workflows: [workflow('workflows/qwen.json', 'qwen.json')],
      slotCounts: { portrait: 3, costume: 2, pose: 3 },
      workflowCount: 1,
      qualityCount: 1,
      ratioCount: 1,
      activeSlotCount: 3,
    })

    expect(groups).toHaveLength(18)
    expect(wrapper.findAll('[data-testid="studio-matrix-row"]')).toHaveLength(18)
    expect(wrapper.get('[data-testid="studio-matrix-total"]').text()).toBe('18 / 上限 100')
    expect(wrapper.findAll('[data-testid="studio-matrix-group"]')).toHaveLength(18)
  })

  it('total=103 且 overLimit 时根节点转红、超限区含减量提示、进度条不超过 100%', () => {
    const groups = buildBatchGroups({
      portrait: [portrait('p1', '人像A'), portrait('p2', '人像B'), portrait('p3', '人像C')],
      costume: [costume('c1', '服装B'), costume('c2', '服装D')],
      pose: [pose('s1', '姿势C'), pose('s2', '姿势E'), pose('s3', '姿势F')],
      workflows: ['workflows/a.json', 'workflows/b.json'],
      qualities: ['1024'],
      ratios: ['16:9'],
      qualityEnabled: true,
      orientationEnabled: true,
      baseSeed: 100000,
    })

    const wrapper = mountMatrix({
      groups,
      total: 103,
      overLimit: true,
      // 刻意不含「减少」二字：确保断言命中的是组件自己算出的减量提示。
      limitMessage: '当前 103 / 上限 100，超出 3 组',
      workflows: [workflow('workflows/a.json', 'a.json'), workflow('workflows/b.json', 'b.json')],
      slotCounts: { portrait: 3, costume: 2, pose: 3 },
      workflowCount: 2,
      qualityCount: 1,
      ratioCount: 1,
      activeSlotCount: 3,
    })

    expect(wrapper.get('[data-testid="studio-matrix"]').classes()).toContain('is-over')
    const limitText = wrapper.get('[data-testid="studio-matrix-limit"]').text()
    expect(limitText).toContain('减少')
    // 服装维影响最大：人像 3 × 姿势 3 × 工作流 2 = 18 组
    expect(limitText).toContain('减少 1 张服装可减 18 组')

    const percent = progressPercentOf(wrapper)
    expect(Number.isFinite(percent)).toBe(true)
    expect(percent).toBeGreaterThan(0)
    expect(percent).toBeLessThanOrEqual(100)
  })

  it('groups=[] 时显示空态，且不渲染任何行', () => {
    const wrapper = mountMatrix({ groups: [], total: 0, activeSlotCount: 0 })

    expect(wrapper.find('[data-testid="studio-matrix-empty"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="studio-matrix-empty"]').text()).toContain('三槽都为空')
    expect(wrapper.findAll('[data-testid="studio-matrix-row"]')).toHaveLength(0)
  })

  it('P2 文本槽：组头显示「文本 · 类型」+ 前 12 字，不显示空图占位', () => {
    const build = (costumeText: string) =>
      buildBatchGroups({
        portrait: [portrait('p1', '人像A')],
        costume: [costume('c1', '服装B')],
        pose: [pose('s1', '姿势C')],
        workflows: [],
        qualities: [],
        ratios: [],
        qualityEnabled: false,
        orientationEnabled: false,
        baseSeed: 100000,
        slotModes: { portrait: 'image', costume: 'text', pose: 'image' },
        slotTexts: { portrait: '', costume: costumeText, pose: '' },
      })

    const groups = [...build('白色衬衫配黑色西裤和黑色皮鞋'), ...build('黑色外套')]
    const wrapper = mountMatrix({
      groups,
      total: groups.length,
      workflows: [],
      slotCounts: { portrait: 1, costume: 1, pose: 1 },
      activeSlotCount: 2,
    })

    // 不同文本不能碰撞成同一组（组键包含文本内容）
    expect(wrapper.findAll('[data-testid="studio-matrix-group"]')).toHaveLength(2)

    const chips = wrapper.findAll('[data-testid="studio-matrix-thumb-costume"]')
    expect(chips.length).toBeGreaterThanOrEqual(2)
    expect(chips[0]!.text()).toContain('文本 · 人物服饰')
    expect(chips[0]!.text()).toContain('白色衬衫配黑色西裤和黑色…')
    // text 槽不渲染「空」占位
    expect(chips.every((chip) => !chip.find('.matrix__thumb-empty').exists())).toBe(true)
  })

  it('删掉 1 张人像导致原首组键失效时，自动展开新的首组而不是整块收起', async () => {
    const build = (portraits: PortraitItem[]) =>
      buildBatchGroups({
        portrait: portraits,
        costume: [costume('c1', '服装B'), costume('c2', '服装D')],
        pose: [pose('s1', '姿势C'), pose('s2', '姿势E'), pose('s3', '姿势F')],
        workflows: ['workflows/qwen.json'],
        qualities: ['1024'],
        ratios: ['16:9'],
        qualityEnabled: true,
        orientationEnabled: true,
        baseSeed: 100000,
      })

    const full = build([portrait('p1', '人像A'), portrait('p2', '人像B'), portrait('p3', '人像C')])
    const reduced = build([portrait('p2', '人像B'), portrait('p3', '人像C')])

    const wrapper = mountMatrix({
      groups: full,
      total: full.length,
      workflows: [workflow('workflows/qwen.json', 'qwen.json')],
      slotCounts: { portrait: 3, costume: 2, pose: 3 },
      activeSlotCount: 3,
    })
    expect(wrapper.get('.matrix__toggle').attributes('aria-expanded')).toBe('true')

    await wrapper.setProps({
      groups: reduced,
      total: reduced.length,
      slotCounts: { portrait: 2, costume: 2, pose: 3 },
    })

    // 原首组（p1/c1/s1）已不存在；必须自动展开新的首组，否则用户看到的是一份全收起清单。
    expect(wrapper.get('.matrix__toggle').attributes('aria-expanded')).toBe('true')
    expect(wrapper.findAll('[data-testid="studio-matrix-row"]')).toHaveLength(12)
  })
})