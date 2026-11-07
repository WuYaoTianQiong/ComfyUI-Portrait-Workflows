/**
 * 合成台批量提交纯函数单测（阶段 3 多选升级）。
 *
 * 覆盖验收要求的五类核心逻辑：
 * 1. 笛卡尔积组合数（空槽维度计 1、尺寸档多选）；
 * 2. 上限 100 的判定与文案；
 * 3. caps 不支持时提交体不带 quality / aspect_ratio / orientation；
 * 4. 第 i 组 seed = base_seed + i；
 * 5. 切换工作流后清空新工作流不支持的档位 / 比例；
 * 另补：逐组提交的并发上限 2、降级确认候选过滤。
 *
 * 2026-11-06 收紧（任务 13）：
 * - `slots` 三态：undefined=未知不判定 / []=角色不可识别（对所有非空槽位禁用）/
 *   非空=按角色匹配；
 * - 槽位角色集合变化时只取消「已不适用」的工作流，仍适用的保持选中；
 *   同一槽位换另一张图（角色集合不变）不取消任何工作流。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import type { EffectScope } from 'vue'

import type { CostumeItem, PoseItem, PortraitItem } from '@/api/reference'

import {
  MAX_BATCH_RECIPES,
  MAX_SUBMIT_CONCURRENCY,
  RECIPE_POLL_INTERVAL_MS,
  buildBatchGroups,
  buildRecipeRequest,
  buildSlotCombinations,
  buildWorkflowDowngradeCandidates,
  countBatchTotal,
  countSlotCombinations,
  describeBatchLimit,
  describePreviewWorkflowSkip,
  describeWorkflowDowngrade,
  describeWorkflowInapplicable,
  describeWorkflowUnavailable,
  describeWorkflowUnavailableFor,
  evaluateWorkflowApplicability,
  exceedsBatchLimit,
  orientationForRatio,
  parseWorkflowSlots,
  pruneInapplicableWorkflowSelection,
  reconcileQualitySelection,
  reconcileRatioSelection,
  runWithConcurrency,
  useReferenceRecipe,
  workflowInapplicableRole,
} from './useReferenceRecipe'
import type {
  RecipeSubmitRequest,
  StudioWorkflowOption,
  StudioWorkflowSlot,
} from './useReferenceRecipe'
import { useReferenceRecipeDraft } from './useReferenceRecipeDraft'
import { createEmptyPersonBVariant } from './recipeTextFragments'

function portrait(id: string): PortraitItem {
  return {
    id,
    分区: '分区',
    发长: '',
    发型名称: '发型',
    标题: '人像',
    宽: 0,
    高: 0,
    字节数: 0,
    精选: false,
    热门: false,
    缩略图: '',
    原图: '',
    检索: '',
  }
}

function costume(id: string): CostumeItem {
  return {
    id,
    分类: '分类',
    服装名称: '服装',
    标签: [],
    关键词: '',
    缩略图: '',
    预览图: '',
    原图: '',
    检索: '',
    library: 'costume',
  }
}

function pose(id: string): PoseItem {
  return {
    id,
    体系: '体系',
    姿势编号: id,
    分类: '分类',
    姿势名称: '姿势',
    角度: '正面',
    缩略图: '',
    原图: '',
    检索: '',
    nsfw: false,
  }
}

function workflow(
  path: string,
  inputCount: number,
  overrides: Partial<StudioWorkflowOption> = {},
): StudioWorkflowOption {
  return {
    path,
    name: `${path}.json`,
    source: '图库专用',
    relPath: path,
    imageSlots: inputCount,
    inputCount,
    recommended: false,
    // 字段缺失 = 旧后端，能力未知（不判定）；需要判定时用 withSlots 显式给值。
    ...overrides,
  }
}

describe('组合数计算（含空槽 / 尺寸多选）', () => {
  it('空槽维度计 1；三槽全空返回 0', () => {
    expect(countSlotCombinations({ portrait: 0, costume: 0, pose: 0 })).toBe(0)
    expect(countSlotCombinations({ portrait: 2, costume: 0, pose: 0 })).toBe(2)
    expect(countSlotCombinations({ portrait: 2, costume: 1, pose: 0 })).toBe(2)
    expect(countSlotCombinations({ portrait: 2, costume: 3, pose: 4 })).toBe(24)
  })

  it('全组合 = 槽位组合 × 画质档数 × 比例数；尺寸维度 0 按 1', () => {
    expect(countBatchTotal({ portrait: 2, costume: 1, pose: 0 }, 3, 2)).toBe(12)
    // caps 不支持尺寸：维度按 1，不应把 0 乘成 0
    expect(countBatchTotal({ portrait: 2, costume: 0, pose: 0 }, 0, 0)).toBe(2)
    // 没有参考图时任何尺寸都不能凑出任务
    expect(countBatchTotal({ portrait: 0, costume: 0, pose: 0 }, 3, 2)).toBe(0)
  })

  it('buildSlotCombinations 保留空槽为 null，不丢维度', () => {
    const combos = buildSlotCombinations(
      [portrait('pt1'), portrait('pt2')],
      [],
      [pose('p1')],
    )
    expect(combos).toHaveLength(2)
    expect(combos[0]).toEqual({ portrait: expect.objectContaining({ id: 'pt1' }), costume: null, pose: expect.objectContaining({ id: 'p1' }) })
    expect(combos[1].portrait?.id).toBe('pt2')
  })
})

// ---------------------------------------------------------------------------
// P2 替代态：text / empty 槽在组合阶段折叠为 1 维
// ---------------------------------------------------------------------------

describe('P2 替代态的组合折叠', () => {
  const mixedModes = {
    portrait: 'text',
    costume: 'image',
    pose: 'text',
  } as const

  it('text 槽即使有残留条目也折叠为 null，不参与笛卡尔积', () => {
    const combos = buildSlotCombinations(
      [portrait('pt1'), portrait('pt2')],
      [costume('c1'), costume('c2')],
      [pose('s1')],
      mixedModes,
    )

    expect(combos).toHaveLength(2)
    expect(combos.every((combo) => combo.portrait === null)).toBe(true)
    expect(combos.every((combo) => combo.pose === null)).toBe(true)
    expect(combos.map((combo) => combo.costume?.id)).toEqual(['c1', 'c2'])
  })

  it('组合数：text 槽按 1 维；三槽全空仍为 0；单独 text 槽算有内容', () => {
    expect(countSlotCombinations({ portrait: 2, costume: 2, pose: 5 }, mixedModes)).toBe(2)
    expect(
      countSlotCombinations(
        { portrait: 0, costume: 0, pose: 0 },
        { portrait: 'empty', costume: 'empty', pose: 'empty' },
      ),
    ).toBe(0)
    expect(
      countSlotCombinations(
        { portrait: 0, costume: 0, pose: 0 },
        { portrait: 'text', costume: 'empty', pose: 'empty' },
      ),
    ).toBe(1)
  })

  it('buildBatchGroups 把 slotModes / slotTexts 透传到每组', () => {
    const slotTexts = { portrait: '长脸，窄下颌', costume: '', pose: '自然站立' }
    const groups = buildBatchGroups({
      portrait: [portrait('pt1')],
      costume: [costume('c1'), costume('c2')],
      pose: [pose('s1')],
      workflows: [],
      qualities: [],
      ratios: [],
      qualityEnabled: false,
      orientationEnabled: false,
      baseSeed: 100,
      slotModes: mixedModes,
      slotTexts,
    })

    expect(groups).toHaveLength(2)
    for (const group of groups) {
      expect(group.slotModes).toEqual(mixedModes)
      expect(group.slotTexts).toEqual(slotTexts)
      expect(group.slots.portrait).toBeNull()
      expect(group.slots.pose).toBeNull()
    }
  })
})

describe('v1.5：A 人像 × B 变体按序号 1:1 配对', () => {
  function variant(id: string) {
    return { ...createEmptyPersonBVariant(id), freeText: `B ${id}` }
  }
  const base = {
    costume: [],
    pose: [],
    workflows: [],
    qualities: [],
    ratios: [],
    qualityEnabled: false,
    orientationEnabled: false,
    baseSeed: 100,
  }

  it('2 人像 + 2 变体 → 2 组（不是 4 组笛卡尔积）', () => {
    const groups = buildBatchGroups({
      ...base,
      portrait: [portrait('p1'), portrait('p2')],
      personBVariants: [variant('b1'), variant('b2')],
    })
    expect(groups).toHaveLength(2)
    expect(groups.map((group) => group.slots.portrait?.id)).toEqual(['p1', 'p2'])
    expect(groups.map((group) => group.personBVariant?.id)).toEqual(['b1', 'b2'])
  })

  it('人像更多时复用最后一组变体，不丢人像也不做乘积', () => {
    const groups = buildBatchGroups({
      ...base,
      portrait: [portrait('p1'), portrait('p2'), portrait('p3')],
      personBVariants: [variant('b1'), variant('b2')],
    })
    expect(groups).toHaveLength(3)
    expect(groups[2].slots.portrait?.id).toBe('p3')
    expect(groups[2].personBVariant?.id).toBe('b2')
  })

  it('变体更多时复用最后一张人像，不丢变体', () => {
    const groups = buildBatchGroups({
      ...base,
      portrait: [portrait('p1'), portrait('p2')],
      personBVariants: [variant('b1'), variant('b2'), variant('b3')],
    })
    expect(groups).toHaveLength(3)
    expect(groups[2].slots.portrait?.id).toBe('p2')
    expect(groups[2].personBVariant?.id).toBe('b3')
  })

  it('没有变体时保持旧口径：人像 × 服装仍为笛卡尔积', () => {
    const groups = buildBatchGroups({
      ...base,
      costume: [costume('c1'), costume('c2')],
      portrait: [portrait('p1'), portrait('p2')],
    })
    expect(groups).toHaveLength(4)
    expect(groups.every((group) => group.personBVariant === null)).toBe(true)
  })

  it('countSlotCombinations / countBatchTotal 与配对口径一致', () => {
    expect(countSlotCombinations({ portrait: 2, costume: 0, pose: 0 }, undefined, 3)).toBe(3)
    expect(countBatchTotal({ portrait: 2, costume: 0, pose: 0 }, 1, 1, 1, undefined, 3)).toBe(3)
  })
})

describe('上限 100', () => {
  it('100 张允许、101 张超限', () => {
    expect(MAX_BATCH_RECIPES).toBe(100)
    expect(exceedsBatchLimit(100)).toBe(false)
    expect(exceedsBatchLimit(101)).toBe(true)
  })

  it('超限文案逐字匹配页面按钮禁用提示（含当前 / 上限与四项缩减建议）', () => {
    expect(describeBatchLimit(150)).toBe(
      '当前 150 / 上限 100，请减少工作流、槽位或尺寸档数',
    )
    expect(describeBatchLimit(162)).toBe(
      '当前 162 / 上限 100，请减少工作流、槽位或尺寸档数',
    )
  })
})

describe('caps 过滤：不发送用不上的尺寸参数', () => {
  it('caps 不支持时 quality / aspect_ratio / orientation 三键都不出现', () => {
    const groups = buildBatchGroups({
      portrait: [portrait('pt1')],
      costume: [],
      pose: [],
      workflows: [],
      // 即使选了尺寸，caps 不支持也会折叠为「不发参数」
      qualities: ['2K', '4K'],
      ratios: ['1:1', '2:3'],
      qualityEnabled: false,
      orientationEnabled: false,
      baseSeed: 7,
    })
    expect(groups).toHaveLength(1)
    expect(groups[0].quality).toBe('')
    expect(groups[0].aspectRatio).toBe('')

    const request = buildRecipeRequest(groups[0].slots, {
      style: 'realistic',
      promptSuffix: '',
      extraPath: '',
      workflow: 'Qwen21+VNCCS.api.json',
      quality: groups[0].quality,
      aspectRatio: groups[0].aspectRatio,
      orientation: groups[0].orientation,
      seed: groups[0].seed,
    })

    expect(request.workflow).toBe('Qwen21+VNCCS.api.json')
    expect('quality' in request).toBe(false)
    expect('aspect_ratio' in request).toBe(false)
    expect('orientation' in request).toBe(false)
  })

  it('caps 支持时尺寸参数原样进入提交体', () => {
    const groups = buildBatchGroups({
      portrait: [],
      costume: [costume('c1')],
      pose: [],
      workflows: [],
      qualities: ['4K'],
      ratios: ['2:3'],
      qualityEnabled: true,
      orientationEnabled: true,
      baseSeed: 100000,
    })
    expect(groups).toHaveLength(1)

    const request = buildRecipeRequest(groups[0].slots, {
      style: 'none',
      promptSuffix: '',
      extraPath: '',
      workflow: 'PornMaster.json',
      quality: groups[0].quality,
      aspectRatio: groups[0].aspectRatio,
      orientation: groups[0].orientation,
      seed: groups[0].seed,
    })
    expect(request.quality).toBe('4K')
    expect(request.aspect_ratio).toBe('2:3')
    expect(request.orientation).toBe('portrait')
  })

  it('比例为横版时 orientation = landscape', () => {
    expect(orientationForRatio('16:9')).toBe('landscape')
    expect(orientationForRatio('9:16')).toBe('portrait')
    expect(orientationForRatio('1:1')).toBe('portrait')
  })
})

describe('base_seed + i 派生', () => {
  it('笛卡尔积按「槽位 → 画质 → 比例」顺序编号，seed 连续递增', () => {
    const groups = buildBatchGroups({
      portrait: [portrait('pt1'), portrait('pt2')],
      costume: [],
      pose: [],
      workflows: [],
      qualities: ['2K', '4K'],
      ratios: ['1:1', '2:3'],
      qualityEnabled: true,
      orientationEnabled: true,
      baseSeed: 100000,
    })

    // 2 张人像 × 2 画质 × 2 比例 = 8 组
    expect(groups).toHaveLength(8)
    expect(groups.map((group) => group.index)).toEqual([0, 1, 2, 3, 4, 5, 6, 7])
    expect(groups.map((group) => group.seed)).toEqual([
      100000, 100001, 100002, 100003, 100004, 100005, 100006, 100007,
    ])
    // 第 2 组：第二张人像 · 2K · 2:3
    expect(groups[1].slots.portrait?.id).toBe('pt1')
    expect(groups[1].quality).toBe('2K')
    expect(groups[1].aspectRatio).toBe('2:3')
  })

  it('基础种子为负数 / 非法值时回落到默认种子', () => {
    const groups = buildBatchGroups({
      portrait: [portrait('pt1')],
      costume: [],
      pose: [],
      workflows: [],
      qualities: [],
      ratios: [],
      qualityEnabled: false,
      orientationEnabled: false,
      baseSeed: Number.NaN,
    })
    expect(groups[0].seed).toBe(100000)
  })
})

describe('切换工作流后清空不支持的尺寸选项', () => {
  const qualityOptions = [
    { value: '2K', label: '2K' },
    { value: '4K', label: '4K' },
  ]

  it('画质：保留可用项，全部失效时回落 4K；新工作流不支持则清空', () => {
    expect(reconcileQualitySelection(['8K', '2K'], qualityOptions)).toEqual(['2K'])
    expect(reconcileQualitySelection(['8K', '12K'], qualityOptions)).toEqual(['4K'])
    expect(reconcileQualitySelection(['2K'], [])).toEqual([])
  })

  it('比例：保留可用项，全部失效时回落工作流默认比例；不支持则清空', () => {
    const ratios = ['1:1', '2:3']
    expect(reconcileRatioSelection(['1:1', '9:21'], ratios, '2:3')).toEqual(['1:1'])
    expect(reconcileRatioSelection(['9:21'], ratios, '2:3')).toEqual(['2:3'])
    expect(reconcileRatioSelection(['1:1'], [], '')).toEqual([])
  })
})

describe('工作流降级确认', () => {
  const workflows = [
    workflow('/current', 4),
    workflow('/three', 3),
    workflow('/two', 2),
    workflow('/empty', 0),
  ]

  it('候选只保留 input_count <= M 且不含当前项', () => {
    const candidates = buildWorkflowDowngradeCandidates(workflows, '/current', 2)
    expect(candidates.map((item) => item.path)).toEqual(['/two'])
  })

  it('文案必须写明语义可能变为换衣/编辑', () => {
    const message = describeWorkflowDowngrade(4, 2)
    expect(message).toContain('需要 4 个输入')
    expect(message).toContain('2 个非空槽位')
    expect(message).toContain('切换后任务语义可能变为换衣/编辑')
    expect(message).toContain('下一步：')
  })
})

describe('逐组提交并发上限', () => {
  it(`最多 ${MAX_SUBMIT_CONCURRENCY} 个 worker 同时执行，结果顺序不变`, async () => {
    let active = 0
    let peak = 0
    const items = [1, 2, 3, 4, 5]

    const results = await runWithConcurrency(items, MAX_SUBMIT_CONCURRENCY, async (item) => {
      active += 1
      peak = Math.max(peak, active)
      await new Promise((resolve) => setTimeout(resolve, 1))
      active -= 1
      return item * 2
    })

    expect(peak).toBeLessThanOrEqual(MAX_SUBMIT_CONCURRENCY)
    expect(peak).toBe(2)
    expect(results).toEqual([2, 4, 6, 8, 10])
  })
})
// ---------------------------------------------------------------------------
// C-REF-TOTAL@2：工作流作为笛卡尔积第四维
// ---------------------------------------------------------------------------

describe('四维笛卡尔积（槽位 × 工作流 × 画质 × 比例）', () => {
  it('2 人像 × 2 工作流 × 2 画质 × 2 比例 = 16 组，index / seed 连续', () => {
    const groups = buildBatchGroups({
      portrait: [portrait('pt1'), portrait('pt2')],
      costume: [],
      pose: [],
      workflows: ['/A.api.json', '/B.api.json'],
      qualities: ['2K', '4K'],
      ratios: ['1:1', '2:3'],
      qualityEnabled: true,
      orientationEnabled: true,
      baseSeed: 900,
    })

    expect(groups).toHaveLength(16)
    expect(groups.map((group) => group.index)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    ])
    expect(groups.map((group) => group.seed)).toEqual([
      900, 901, 902, 903, 904, 905, 906, 907, 908, 909, 910, 911, 912, 913, 914, 915,
    ])
    // 每个槽位组合内先轮完「工作流 → 画质 → 比例」
    expect(groups[0]).toMatchObject({
      workflow: '/A.api.json',
      quality: '2K',
      aspectRatio: '1:1',
    })
    expect(groups[0].slots.portrait?.id).toBe('pt1')
    expect(groups[3].workflow).toBe('/A.api.json')
    expect(groups[4].workflow).toBe('/B.api.json')
    expect(groups[8].slots.portrait?.id).toBe('pt2')
    expect(groups.map((group) => group.workflow).slice(0, 8)).toEqual([
      '/A.api.json',
      '/A.api.json',
      '/A.api.json',
      '/A.api.json',
      '/B.api.json',
      '/B.api.json',
      '/B.api.json',
      '/B.api.json',
    ])
  })

  it('未选工作流时按 1 条默认工作流计，不把维度乘成 0', () => {
    const groups = buildBatchGroups({
      portrait: [portrait('pt1'), portrait('pt2')],
      costume: [],
      pose: [],
      workflows: [],
      qualities: ['4K'],
      ratios: ['2:3'],
      qualityEnabled: true,
      orientationEnabled: true,
      baseSeed: 100000,
    })
    expect(groups).toHaveLength(2)
    expect(groups.every((group) => group.workflow === '')).toBe(true)
    // 工作流维度传 0 也按 1 计（空选择回落默认项）
    expect(countBatchTotal({ portrait: 2, costume: 0, pose: 0 }, 2, 2, 0)).toBe(8)
  })

  it('四维合计超限：100 允许、150 超限并给出可断言文案', () => {
    const counts = { portrait: 5, costume: 0, pose: 0 }
    expect(countBatchTotal(counts, 2, 2, 5)).toBe(100)
    expect(exceedsBatchLimit(100)).toBe(false)
    expect(countBatchTotal(counts, 2, 3, 5)).toBe(150)
    expect(exceedsBatchLimit(150)).toBe(true)
    expect(describeBatchLimit(150)).toBe('当前 150 / 上限 100，请减少工作流、槽位或尺寸档数')
  })
})

// ---------------------------------------------------------------------------
// C-REF-WF-SLOTS@1：槽位角色适用性
// ---------------------------------------------------------------------------

describe('工作流角色适用性（slots 三态）', () => {
  const withSlots = (path: string, slots: StudioWorkflowSlot[]): StudioWorkflowOption =>
    workflow(path, 3, { slots })

  it('parseWorkflowSlots 三态：undefined 宽松 / [] 不可识别 / 非数组脏数据按不可识别', () => {
    // undefined = 字段缺失（旧后端）：保持 unknown，不做判定
    expect(parseWorkflowSlots(undefined)).toBeUndefined()
    // 空数组 = 角色不可识别（UI 格式工作流）
    expect(parseWorkflowSlots([])).toEqual([])
    // 非数组脏数据同样按不可识别（只有 undefined 宽松）
    expect(parseWorkflowSlots(null)).toEqual([])
    expect(parseWorkflowSlots('portrait')).toEqual([])
    // 合法角色去重，非法项忽略
    expect(parseWorkflowSlots(['portrait', 'bogus', 'portrait', 'extra'])).toEqual([
      'portrait',
      'extra',
    ])
    expect(parseWorkflowSlots([1, 'costume'])).toEqual(['costume'])
    // 数组里全是非法值 → 不可识别
    expect(parseWorkflowSlots(['bogus'])).toEqual([])
  })

  it('evaluate：undefined 不判定、[] 全部不适用、非空按角色匹配', () => {
    const unknown = workflow('/unknown', 3)
    expect(evaluateWorkflowApplicability(unknown, ['portrait', 'costume'])).toEqual({
      kind: null,
      role: null,
    })

    const unrecognized = withSlots('/ui-format', [])
    expect(evaluateWorkflowApplicability(unrecognized, ['portrait', 'costume'])).toEqual({
      kind: 'unrecognized',
      role: 'portrait',
    })
    // 空槽位不参与判定：没有任何已选槽位时，不可识别工作流也不拦
    expect(evaluateWorkflowApplicability(unrecognized, [])).toEqual({ kind: null, role: null })

    const portraitAndPose = withSlots('/pp', ['portrait', 'pose'])
    expect(evaluateWorkflowApplicability(portraitAndPose, ['portrait', 'pose'])).toEqual({
      kind: null,
      role: null,
    })
    expect(evaluateWorkflowApplicability(portraitAndPose, ['portrait', 'costume'])).toEqual({
      kind: 'missing',
      role: 'costume',
    })
    // 兼容入口与结构化结果一致
    expect(workflowInapplicableRole(portraitAndPose, ['portrait', 'pose'])).toBeNull()
    expect(workflowInapplicableRole(portraitAndPose, ['portrait', 'costume'])).toBe('costume')
    expect(workflowInapplicableRole(portraitAndPose, [])).toBeNull()
  })

  it('不可识别与缺角色的原因文案逐字可断言（下拉 / 提交 / 预览共用）', () => {
    expect(describeWorkflowInapplicable('portrait', '四输入.api.json')).toBe(
      '工作流「四输入」缺少人像输入，不适用于当前已选人像',
    )
    expect(describeWorkflowUnavailable('unrecognized', 'portrait')).toBe(
      '该工作流的参考图节点无法识别角色（可能是 UI 格式工作流），不适用于当前已选人像',
    )
    expect(describeWorkflowUnavailableFor(withSlots('/ui', []), ['costume'])).toBe(
      '该工作流的参考图节点无法识别角色（可能是 UI 格式工作流），不适用于当前已选服装',
    )
    // undefined 不产生原因（旧后端不受影响）
    expect(describeWorkflowUnavailableFor(workflow('/old', 3), ['costume'])).toBe('')

    const missingSkip = describePreviewWorkflowSkip('costume', '无服装.api.json')
    expect(missingSkip).toContain('提示词预览已跳过')
    expect(missingSkip).toContain('缺少服装输入，不适用于当前已选服装')
    expect(missingSkip).toContain('下一步：')

    const unrecognizedSkip = describePreviewWorkflowSkip('portrait', '/ui', 'unrecognized')
    expect(unrecognizedSkip).toContain('提示词预览已跳过')
    expect(unrecognizedSkip).toContain('无法识别角色')
    expect(unrecognizedSkip).toContain('下一步：')
  })
})

describe('槽位变化只取消已不适用工作流（收紧点 2）', () => {
  const onlyPortrait = workflow('/portrait-only', 3, { slots: ['portrait'] })
  const portraitAndCostume = workflow('/portrait-costume', 3, {
    slots: ['portrait', 'costume'],
  })

  it('选 2 个 → 换同槽位的另一张图：角色集合不变，2 个仍选中', () => {
    const selection = ['/portrait-only', '/portrait-costume']
    const before = pruneInapplicableWorkflowSelection(
      selection,
      [onlyPortrait, portraitAndCostume],
      ['portrait'],
    )
    expect(before.kept).toEqual(selection)
    expect(before.removed).toEqual([])

    // 「人像槽换另一张图」不改变角色集合（仍只有 portrait），裁剪结果不变
    const afterSwap = pruneInapplicableWorkflowSelection(
      selection,
      [onlyPortrait, portraitAndCostume],
      ['portrait'],
    )
    expect(afterSwap.kept).toEqual(selection)
    expect(afterSwap.removed).toEqual([])
  })

  it('选 2 个 → 新增服装槽：只取消不支持服装的那 1 个，另一个保持选中', () => {
    const selection = ['/portrait-only', '/portrait-costume']
    const result = pruneInapplicableWorkflowSelection(
      selection,
      [onlyPortrait, portraitAndCostume],
      ['portrait', 'costume'],
    )
    expect(result.kept).toEqual(['/portrait-costume'])
    expect(result.removed).toHaveLength(1)
    expect(result.removed[0].path).toBe('/portrait-only')
    expect(result.removed[0].reason).toContain('缺少服装输入')
  })

  it('目录中已消失的路径静默剔除（不产生误导性原因）', () => {
    const result = pruneInapplicableWorkflowSelection(
      ['/gone', '/portrait-only'],
      [onlyPortrait],
      ['portrait'],
    )
    expect(result.kept).toEqual(['/portrait-only'])
    expect(result.removed).toEqual([{ path: '/gone', reason: '' }])
  })
})
// ---------------------------------------------------------------------------
// 多批次并发：轮询期间可继续提交、各批状态 / 结果互不覆盖
// ---------------------------------------------------------------------------

interface MockJobState {
  status: string
  total: number
  done_count: number
  items: Array<{
    images: Array<{ filename: string; subfolder?: string; type?: string }>
    error?: string
  }>
}

/**
 * 用最小 fetch mock 驱动真实 composable：
 * - `/api/workflows?scope=studio` 返回 1 条支持 portrait 的工作流；
 * - `POST /api/reference/recipes` 每次分配新的递增 job_id（dry_run 直接返回预览）；
 * - `GET /api/jobs/{id}` 读测试可改写的 `jobState`。
 */
describe('多批次并发（轮询期间可继续提交）', () => {
  const draft = useReferenceRecipeDraft()
  let scopes: EffectScope[] = []
  let submittedBodies: RecipeSubmitRequest[] = []
  let jobState: Map<number, MockJobState>
  let jobSequence = 0

  function jsonResponse(data: unknown): { ok: boolean; status: number; json: () => Promise<unknown> } {
    return { ok: true, status: 200, json: async () => data }
  }

  function installFetchMock(): void {
    jobSequence = 0
    submittedBodies = []
    jobState = new Map()

    const fetchMock = vi.fn(
      async (input: unknown, init?: { method?: string; body?: unknown }) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : String((input as { url?: string } | null)?.url ?? '')

        if (url.startsWith('/api/workflows')) {
          return jsonResponse({
            workflows: [
              {
                path: '/wf.api.json',
                name: 'wf.api.json',
                source: '图库专用',
                rel_path: '/wf.api.json',
                image_slots: 1,
                input_count: 1,
                recommended: false,
                slots: ['portrait'],
              },
            ],
            default: '/wf.api.json',
          })
        }

        if (url === '/api/reference/recipes' && (init?.method ?? 'GET') === 'POST') {
          const body = JSON.parse(String(init?.body ?? '{}')) as RecipeSubmitRequest & {
            dry_run?: boolean
          }
          if (body.dry_run) {
            return jsonResponse({ success: true, dry_run: true, prompt: '预览提示词' })
          }
          submittedBodies.push(body)
          const id = ++jobSequence
          jobState.set(id, { status: 'running', total: 1, done_count: 0, items: [] })
          return jsonResponse({
            success: true,
            job_id: id,
            total: 1,
            submitted: 1,
            queued: 1,
            errors: [],
          })
        }

        const match = /^\/api\/jobs\/(\d+)$/.exec(url)
        if (match) {
          const id = Number(match[1])
          const state = jobState.get(id) ?? {
            status: 'running',
            total: 1,
            done_count: 0,
            items: [],
          }
          return jsonResponse({ id, ...state })
        }

        throw new Error(`未预期的请求：${url}`)
      },
    )
    vi.stubGlobal('fetch', fetchMock)
  }

  function completeJob(id: number, filenames: string[]): void {
    jobState.set(id, {
      status: 'done',
      total: 1,
      done_count: 1,
      items: [
        {
          images: filenames.map((filename) => ({ filename, subfolder: '', type: 'output' })),
        },
      ],
    })
  }

  function failJob(id: number, detail = '模型缺失'): void {
    jobState.set(id, {
      status: 'failed',
      total: 1,
      done_count: 0,
      items: [{ images: [], error: detail }],
    })
  }

  async function flushMicrotasks(rounds = 20): Promise<void> {
    for (let round = 0; round < rounds; round += 1) await Promise.resolve()
  }

  /** 推进一轮轮询（默认 1500ms），并让所有挂起的 promise 结算。 */
  async function advancePoll(ms = RECIPE_POLL_INTERVAL_MS): Promise<void> {
    await vi.advanceTimersByTimeAsync(ms)
    await flushMicrotasks()
  }

  function createRecipe() {
    const scope = effectScope()
    const recipe = scope.run(() => useReferenceRecipe())
    if (!recipe) throw new Error('无法创建 useReferenceRecipe')
    scopes.push(scope)
    return recipe
  }

  /** 载入工作流目录 + 选中 1 张人像，保证 canSubmit 的前置校验全部通过。 */
  async function prepareRecipe() {
    const recipe = createRecipe()
    await recipe.loadStudioWorkflows()
    draft.addPortrait(portrait('pt1'))
    recipe.setWorkflowSelection(['/wf.api.json'])
    await flushMicrotasks()
    return recipe
  }

  beforeEach(() => {
    vi.useFakeTimers()
    draft.clearDraft()
    installFetchMock()
  })

  afterEach(() => {
    for (const scope of scopes) scope.stop()
    scopes = []
    draft.clearDraft()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('轮询期间 canSubmit 仍为 true，第二批立即提交且各自拥有独立 job', async () => {
    const recipe = await prepareRecipe()

    const first = recipe.submit()
    // 提交阶段的短暂窗口：按钮禁用、submit 拦截重复点击
    expect(recipe.submitting.value).toBe(true)
    expect(recipe.canSubmit.value).toBe(false)
    expect(await recipe.submit()).toBeNull()
    await flushMicrotasks()

    expect(recipe.batches.value).toHaveLength(1)
    expect(recipe.batches.value[0].status).toBe('polling')
    expect(recipe.submitting.value).toBe(false)
    expect(recipe.polling.value).toBe(true)
    // 关键：轮询期间不再禁用提交
    expect(recipe.canSubmit.value).toBe(true)

    const second = recipe.submit()
    await flushMicrotasks()

    expect(recipe.batches.value).toHaveLength(2)
    expect(recipe.batches.value[1].status).toBe('polling')
    // 两次 POST 都真实发出，分别拿到 job 1 / job 2
    expect(submittedBodies).toHaveLength(2)
    expect(recipe.batches.value[0].jobIds).toEqual([1])
    expect(recipe.batches.value[1].jobIds).toEqual([2])

    completeJob(1, ['first.png'])
    completeJob(2, ['second.png'])
    await advancePoll()
    await Promise.all([first, second])
  })

  it('两批同时存在时状态独立：第一批完成只更新第一批，第二批继续轮询', async () => {
    const recipe = await prepareRecipe()

    const first = recipe.submit()
    await flushMicrotasks()
    const second = recipe.submit()
    await flushMicrotasks()

    // 只完成 job 1（第一批）
    completeJob(1, ['first.png'])
    await advancePoll()

    expect(recipe.batches.value[0].status).toBe('success')
    expect(recipe.batches.value[0].results).toEqual([
      '/api/media/image?filename=first.png&type=output',
    ])
    expect(recipe.batches.value[1].status).toBe('polling')
    expect(recipe.batches.value[1].results).toEqual([])
    // 兼容视图跟随“最新一批”，不应被旧批次完成覆盖
    expect(recipe.resultUrls.value).toEqual([])

    completeJob(2, ['second.png'])
    await advancePoll()
    await Promise.all([first, second])

    expect(recipe.batches.value[1].status).toBe('success')
  })

  it('一批失败不影响另一批：失败批次只写自己的错误，成功批次照常完成', async () => {
    const recipe = await prepareRecipe()

    const first = recipe.submit()
    await flushMicrotasks()
    const second = recipe.submit()
    await flushMicrotasks()

    failJob(1, 'GPU 显存不足')
    completeJob(2, ['second.png'])
    await advancePoll()

    await Promise.all([first, second])

    expect(recipe.batches.value[0].status).toBe('failed')
    expect(recipe.batches.value[0].errorMessage).toContain('GPU 显存不足')
    expect(recipe.batches.value[0].results).toEqual([])

    expect(recipe.batches.value[1].status).toBe('success')
    expect(recipe.batches.value[1].errorMessage).toBe('')
    expect(recipe.batches.value[1].results).toEqual([
      '/api/media/image?filename=second.png&type=output',
    ])
  })

  it('批次结果不串：每批只包含自己 job 的结果图', async () => {
    const recipe = await prepareRecipe()

    const first = recipe.submit()
    await flushMicrotasks()
    const second = recipe.submit()
    await flushMicrotasks()

    completeJob(1, ['batch-one.png'])
    completeJob(2, ['batch-two-a.png', 'batch-two-b.png'])
    await advancePoll()
    await Promise.all([first, second])

    const [batchOne, batchTwo] = recipe.batches.value
    expect(batchOne.results).toEqual([
      '/api/media/image?filename=batch-one.png&type=output',
    ])
    expect(batchTwo.results).toEqual([
      '/api/media/image?filename=batch-two-a.png&type=output',
      '/api/media/image?filename=batch-two-b.png&type=output',
    ])
    // 兼容视图 = 最近一批（第二批）的结果，绝不混入第一批
    expect(recipe.resultUrls.value).toEqual(batchTwo.results)
  })
})

// ---------------------------------------------------------------------------
// 提交前可裁剪探测（2026-11-06）
//
// M（非空槽数）< N（input_count）时先问后端「空槽能不能裁」：
// - 能裁 → 直接提交 + toast（不再拦一次确认框）；
// - 裁不掉 → 弹原确认框，且带后端给出的 exact 原因（不再给「仍用当前工作流提交」）；
// - 探测本身失败 → 退回确认框，绝不因探测失败放行。
// ---------------------------------------------------------------------------

describe('提交前可裁剪探测（trim-check）', () => {
  const draft = useReferenceRecipeDraft()
  let scopes: EffectScope[] = []
  let submittedBodies: RecipeSubmitRequest[] = []
  let trimRequests: Array<{ workflows?: string[]; roles?: string[] }> = []
  let trimReply: unknown = null
  let trimStatus = 200
  let jobState: Map<number, { status: string; total: number; done_count: number; items: unknown[] }>
  let jobSequence = 0

  const WORKFLOW = '/wf3.api.json'
  /** 声明支持第 4 张（extra）的工作流；用来验证上传入口的显隐条件。 */
  const EXTRA_WORKFLOW = '/wf4.api.json'

  function jsonResponse(data: unknown, status = 200): {
    ok: boolean
    status: number
    json: () => Promise<unknown>
  } {
    return { ok: status >= 200 && status < 300, status, json: async () => data }
  }

  function installFetchMock(): void {
    jobSequence = 0
    submittedBodies = []
    trimRequests = []
    jobState = new Map()

    const fetchMock = vi.fn(
      async (input: unknown, init?: { method?: string; body?: unknown }) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : String((input as { url?: string } | null)?.url ?? '')

        if (url.startsWith('/api/workflows')) {
          return jsonResponse({
            workflows: [
              {
                path: WORKFLOW,
                name: 'wf3.api.json',
                source: '图库专用',
                rel_path: WORKFLOW,
                image_slots: 3,
                input_count: 3,
                recommended: true,
                slots: ['portrait', 'costume', 'pose'],
              },
              {
                path: EXTRA_WORKFLOW,
                name: 'wf4.api.json',
                source: '图库专用',
                rel_path: EXTRA_WORKFLOW,
                image_slots: 4,
                input_count: 4,
                recommended: false,
                slots: ['portrait', 'costume', 'pose', 'extra'],
              },
            ],
            default: WORKFLOW,
          })
        }

        if (url === '/api/reference/trim-check' && (init?.method ?? 'GET') === 'POST') {
          trimRequests.push(
            JSON.parse(String(init?.body ?? '{}')) as { workflows?: string[]; roles?: string[] },
          )
          return jsonResponse(trimReply, trimStatus)
        }

        if (url === '/api/reference/recipes' && (init?.method ?? 'GET') === 'POST') {
          const body = JSON.parse(String(init?.body ?? '{}')) as RecipeSubmitRequest & {
            dry_run?: boolean
          }
          if (body.dry_run) return jsonResponse({ success: true, dry_run: true, prompt: '预览' })
          submittedBodies.push(body)
          const id = ++jobSequence
          jobState.set(id, { status: 'running', total: 1, done_count: 0, items: [] })
          return jsonResponse({ success: true, job_id: id, total: 1, submitted: 1, queued: 1, errors: [] })
        }

        const match = /^\/api\/jobs\/(\d+)$/.exec(url)
        if (match) {
          const id = Number(match[1])
          const state = jobState.get(id) ?? {
            status: 'running',
            total: 1,
            done_count: 0,
            items: [],
          }
          return jsonResponse({ id, ...state })
        }

        throw new Error(`未预期的请求：${url}`)
      },
    )
    vi.stubGlobal('fetch', fetchMock)
  }

  async function flushMicrotasks(rounds = 20): Promise<void> {
    for (let round = 0; round < rounds; round += 1) await Promise.resolve()
  }

  async function prepareRecipe(): Promise<ReturnType<typeof useReferenceRecipe>> {
    const scope = effectScope()
    const recipe = scope.run(() => useReferenceRecipe())
    if (!recipe) throw new Error('无法创建 useReferenceRecipe')
    scopes.push(scope)
    await recipe.loadStudioWorkflows()
    // 只放 1 张人像：M=1 < N=3，必然触发探测
    draft.addPortrait(portrait('pt1'))
    recipe.setWorkflowSelection([WORKFLOW])
    await flushMicrotasks()
    return recipe
  }

  beforeEach(() => {
    vi.useFakeTimers()
    draft.clearDraft()
    trimStatus = 200
    trimReply = { workflows: [], all_trimmable: true }
    installFetchMock()
  })

  afterEach(() => {
    for (const scope of scopes) scope.stop()
    scopes = []
    draft.clearDraft()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('可裁剪时直接提交并给出裁剪提示，不弹确认框', async () => {
    trimReply = {
      workflows: [
        { name: 'wf3.api.json', path: WORKFLOW, input_count: 3, slot_count: 1, trimmable: true, reason: '' },
      ],
      all_trimmable: true,
    }
    const recipe = await prepareRecipe()

    const pending = recipe.submit()
    await flushMicrotasks()

    // 探测请求带的是「工作流 + 已填角色」，不是具体素材
    expect(trimRequests).toEqual([{ workflows: [WORKFLOW], roles: ['portrait'] }])
    expect(recipe.workflowDowngrade.value).toBeNull()
    expect(recipe.workflowTrimNotice.value).toContain('需要 3 个输入')
    expect(recipe.workflowTrimNotice.value).toContain('已按 1 图自动裁剪空槽后提交')
    // 真的提交了（不是只提示不提交）
    expect(submittedBodies).toHaveLength(1)
    expect(submittedBodies[0].workflow).toBe(WORKFLOW)

    jobState.set(1, { status: 'done', total: 1, done_count: 1, items: [{ images: [{ filename: 'a.png' }] }] })
    await vi.advanceTimersByTimeAsync(RECIPE_POLL_INTERVAL_MS)
    await flushMicrotasks()
    await pending
  })

  it('后端确认裁不掉时弹确认框，并带上 exact 原因', async () => {
    const reason = '该工作流有 3 个输入且无法裁剪到 1 个；请至少提供 3 张参考图'
    trimReply = {
      workflows: [
        { name: 'wf3.api.json', path: WORKFLOW, input_count: 3, slot_count: 1, trimmable: false, reason },
      ],
      all_trimmable: false,
    }
    const recipe = await prepareRecipe()

    expect(await recipe.submit()).toBeNull()

    expect(submittedBodies).toHaveLength(0)
    const prompt = recipe.workflowDowngrade.value
    expect(prompt).not.toBeNull()
    expect(prompt?.blockedReason).toBe(reason)
    expect(prompt?.slotCount).toBe(1)
    expect(prompt?.inputCount).toBe(3)
  })

  it('探测失败（旧后端 / 网络）退回确认框，不静默放行', async () => {
    trimStatus = 500
    trimReply = { detail: 'Not Found' }
    const recipe = await prepareRecipe()

    expect(await recipe.submit()).toBeNull()

    expect(submittedBodies).toHaveLength(0)
    expect(recipe.workflowDowngrade.value).not.toBeNull()
    // 没有结论：仍保留「仍用当前工作流提交」的兜底路径
    expect(recipe.workflowDowngrade.value?.blockedReason).toBe('')
  })

  it('缺服装时按素体展示提交并 toast 说明（可与裁剪提示叠加）', async () => {
    trimReply = {
      workflows: [
        { name: 'wf3.api.json', path: WORKFLOW, input_count: 3, slot_count: 1, trimmable: true, reason: '' },
      ],
      all_trimmable: true,
    }
    // prepareRecipe 只放了人像：服装槽为空 → 必须自动切素体展示，否则模型自由发挥出裸体
    const recipe = await prepareRecipe()

    const pending = recipe.submit()
    await flushMicrotasks()

    expect(submittedBodies[0].body_mode).toBe('bare')
    expect(recipe.bodyModeNotice.value).toContain('素体展示')
    expect(recipe.workflowTrimNotice.value).toContain('自动裁剪空槽后提交')

    jobState.set(1, { status: 'done', total: 1, done_count: 1, items: [{ images: [{ filename: 'a.png' }] }] })
    await vi.advanceTimersByTimeAsync(RECIPE_POLL_INTERVAL_MS)
    await flushMicrotasks()
    await pending
  })

  it('有服装时保持 costume 模式，不触发素体提示', async () => {
    trimReply = {
      workflows: [
        { name: 'wf3.api.json', path: WORKFLOW, input_count: 3, slot_count: 2, trimmable: true, reason: '' },
      ],
      all_trimmable: true,
    }
    const recipe = await prepareRecipe()
    draft.addCostume(costume('c1'))
    await flushMicrotasks()

    const pending = recipe.submit()
    await flushMicrotasks()

    expect(submittedBodies[0].body_mode).toBe('costume')
    expect(recipe.bodyModeNotice.value).toBe('')

    jobState.set(1, { status: 'done', total: 1, done_count: 1, items: [{ images: [{ filename: 'b.png' }] }] })
    await vi.advanceTimersByTimeAsync(RECIPE_POLL_INTERVAL_MS)
    await flushMicrotasks()
    await pending
  })

  it('工作流都不支持 extra 时隐藏第 4 张入口，声明支持时恢复', async () => {
    const recipe = await prepareRecipe()

    // 现行 3 槽工作流：`supportsExtraSlot` 必须为 false（页面据此不渲染上传块）
    expect(recipe.supportsExtraSlot.value).toBe(false)

    recipe.setWorkflowSelection([EXTRA_WORKFLOW])
    await flushMicrotasks()
    expect(recipe.supportsExtraSlot.value).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 三槽本地上传图（2026-11-06）：上传图发 `*_path`，库条目发 `*_id`
// ---------------------------------------------------------------------------

describe('本地上传图的提交体', () => {
  const baseOptions = {
    style: 'realistic' as const,
    promptSuffix: '',
    extraPath: '',
    seed: 1,
    seedMode: 'fixed' as const,
  }

  it('人像上传图走 portrait_path，不再发 portrait_id', () => {
    const uploaded = {
      ...portrait('upload:/up/a.png'),
      id: 'upload:/up/a.png',
      uploadPath: '/up/a.png',
    }

    const request = buildRecipeRequest(
      { portrait: uploaded, costume: null, pose: null },
      { ...baseOptions, bodyMode: 'bare' },
    )

    expect(request.portrait_path).toBe('/up/a.png')
    expect(request.portrait_id).toBeUndefined()
  })

  it('服装上传图走 costume_path，素体模式下不发', () => {
    const uploaded = {
      ...costume('upload:/up/c.png'),
      id: 'upload:/up/c.png',
      uploadPath: '/up/c.png',
    }

    const withCostume = buildRecipeRequest(
      { portrait: null, costume: uploaded, pose: null },
      { ...baseOptions, bodyMode: 'costume' },
    )
    expect(withCostume.costume_path).toBe('/up/c.png')
    expect(withCostume.costume_id).toBeUndefined()

    const bare = buildRecipeRequest(
      { portrait: null, costume: uploaded, pose: null },
      { ...baseOptions, bodyMode: 'bare' },
    )
    expect(bare.costume_path).toBeUndefined()
    expect(bare.costume_id).toBeUndefined()
  })

  it('姿势上传图走 pose_path', () => {
    const uploaded = {
      ...pose('upload:/up/p.png'),
      id: 'upload:/up/p.png',
      uploadPath: '/up/p.png',
    }

    const request = buildRecipeRequest(
      { portrait: null, costume: null, pose: uploaded },
      { ...baseOptions, bodyMode: 'bare' },
    )

    expect(request.pose_path).toBe('/up/p.png')
    expect(request.pose_id).toBeUndefined()
  })
})