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
 */

import { describe, expect, it } from 'vitest'

import type { CostumeItem, PoseItem, PortraitItem } from '@/api/reference'

import {
  MAX_BATCH_RECIPES,
  MAX_SUBMIT_CONCURRENCY,
  buildBatchGroups,
  buildRecipeRequest,
  buildSlotCombinations,
  buildWorkflowDowngradeCandidates,
  countBatchTotal,
  countSlotCombinations,
  describeBatchLimit,
  describeWorkflowDowngrade,
  exceedsBatchLimit,
  orientationForRatio,
  reconcileQualitySelection,
  reconcileRatioSelection,
  runWithConcurrency,
} from './useReferenceRecipe'
import type { StudioWorkflowOption } from './useReferenceRecipe'

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

describe('上限 100', () => {
  it('100 张允许、101 张超限', () => {
    expect(MAX_BATCH_RECIPES).toBe(100)
    expect(exceedsBatchLimit(100)).toBe(false)
    expect(exceedsBatchLimit(101)).toBe(true)
  })

  it('超限文案逐字匹配页面按钮禁用提示', () => {
    expect(describeBatchLimit(150)).toBe(
      '全组合共 150 张，超过上限 100 张；请减少素材或尺寸档位',
    )
  })
})

describe('caps 过滤：不发送用不上的尺寸参数', () => {
  it('caps 不支持时 quality / aspect_ratio / orientation 三键都不出现', () => {
    const groups = buildBatchGroups({
      portrait: [portrait('pt1')],
      costume: [],
      pose: [],
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