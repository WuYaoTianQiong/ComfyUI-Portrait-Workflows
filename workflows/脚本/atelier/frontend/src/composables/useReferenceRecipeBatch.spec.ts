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
      '/api/media/image?filename=first.png&subfolder=&type=output',
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
      '/api/media/image?filename=second.png&subfolder=&type=output',
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
      '/api/media/image?filename=batch-one.png&subfolder=&type=output',
    ])
    expect(batchTwo.results).toEqual([
      '/api/media/image?filename=batch-two-a.png&subfolder=&type=output',
      '/api/media/image?filename=batch-two-b.png&subfolder=&type=output',
    ])
    // 兼容视图 = 最近一批（第二批）的结果，绝不混入第一批
    expect(recipe.resultUrls.value).toEqual(batchTwo.results)
  })
})