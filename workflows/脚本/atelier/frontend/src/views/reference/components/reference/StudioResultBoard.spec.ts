/**
 * 合成台「批次结果区」组件单测（方案 §5 M5）。
 *
 * 三条验收：
 * 1. 2 个组各 1 张 url → 2 个 cell，caption 分别是 `#1` / `#2` 并带工作流短名与尺寸，
 *    `studio-result-image` 只出现 1 次（只标记最新批第一张）；
 * 2. 1 个成功组 + 1 个失败组 → 出现失败灰块，正文含错误原因；
 * 3. `batches=[]` → 只有 180px 空态 `studio-preview`，没有批次列表。
 *
 * 数据全部直接构造 `RecipeBatch`，不 mock 组件、不 mock 轮询、不请求后端。
 * 组号依赖 `batch.groups.indexOf(entry.group)`，因此 `groupResults` 必须复用
 * `groups` 里的同一批对象引用（与 `runBatch` 的真实行为一致）。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { CostumeItem, PortraitItem, PoseItem } from '../../../../api/reference'
import type {
  RecipeBatch,
  RecipeBatchGroup,
  RecipeGroupResult,
  StudioWorkflowOption,
} from '../../../../composables/useReferenceRecipe'

import StudioResultBoard from './StudioResultBoard.vue'

/** 直接复用组件声明的 props 类型，避免测试契约与实现漂移。 */
type StudioResultBoardProps = InstanceType<typeof StudioResultBoard>['$props']

// ---------------------------------------------------------------------------
// 真实数据工厂（字段口径与 StudioMatrix.spec.ts 一致）
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

/** 一个笛卡尔积组合（`index` 与种子按提交顺序递增）。 */
function group(index: number, overrides: Partial<RecipeBatchGroup> = {}): RecipeBatchGroup {
  return {
    index,
    slots: {
      portrait: portrait('p1', '人像A'),
      costume: costume('c1', '服装B'),
      pose: pose('s1', '姿势C'),
    },
    workflow: '',
    quality: '',
    aspectRatio: '',
    orientation: '',
    seed: 100000 + index,
    ...overrides,
  }
}

/** 一个独立批次；默认是「全部成功、已结束」。 */
function batch(overrides: Partial<RecipeBatch> = {}): RecipeBatch {
  return {
    id: 'batch-1',
    createdAt: Date.UTC(2026, 10, 6, 5, 52, 1),
    groups: [],
    jobIds: [],
    status: 'success',
    total: 0,
    done: 0,
    submitted: 0,
    failed: 0,
    results: [],
    groupResults: [],
    errorMessage: '',
    submittedAt: null,
    finishedAt: null,
    ...overrides,
  }
}

function createProps(overrides: Partial<StudioResultBoardProps> = {}): StudioResultBoardProps {
  return {
    batches: [],
    poseUseDepth: false,
    workflows: [workflow('workflows/qwen.json', 'qwen.json')],
    ...overrides,
  }
}

function mountBoard(overrides: Partial<StudioResultBoardProps> = {}) {
  return mount(StudioResultBoard, { props: createProps(overrides) })
}

// ---------------------------------------------------------------------------
// 用例
// ---------------------------------------------------------------------------

describe('StudioResultBoard 批次结果区', () => {
  it('2 个组合并结果各 1 张时渲染 2 个 cell，caption 带组号/工作流短名/尺寸，结果图 testid 只出现 1 次', () => {
    const firstGroup = group(0, {
      workflow: 'workflows/qwen.json',
      quality: '1024',
      aspectRatio: '3:4',
    })
    const secondGroup = group(1, {
      workflow: '',
      quality: '',
      aspectRatio: '16:9',
    })
    const groups: RecipeBatchGroup[] = [firstGroup, secondGroup]
    const groupResults: RecipeGroupResult[] = [
      { group: firstGroup, jobId: 11, urls: ['/api/results/a.png'], error: '' },
      { group: secondGroup, jobId: 12, urls: ['/api/results/b.png'], error: '' },
    ]

    const wrapper = mountBoard({
      batches: [
        batch({
          groups,
          groupResults,
          total: 2,
          done: 2,
          submitted: 2,
          results: ['/api/results/a.png', '/api/results/b.png'],
        }),
      ],
    })

    expect(wrapper.findAll('.result-board__cell')).toHaveLength(2)

    const captions = wrapper.findAll('[data-testid="studio-result-caption"]')
    expect(captions).toHaveLength(2)
    expect(captions[0].text()).toContain('#1')
    expect(captions[0].text()).toContain('qwen')
    expect(captions[0].text()).toContain('1024 · 3:4')
    expect(captions[1].text()).toContain('#2')
    expect(captions[1].text()).toContain('默认工作流')
    expect(captions[1].text()).toContain('16:9')

    expect(wrapper.findAll('[data-testid="studio-result-image"]')).toHaveLength(1)
  })

  it('1 个成功组 + 1 个失败组时出现失败灰块，正文含错误原因', () => {
    const okGroup = group(0, {
      workflow: 'workflows/qwen.json',
      quality: '1024',
      aspectRatio: '3:4',
    })
    const failedGroup = group(1, { workflow: 'workflows/qwen.json' })
    const failureReason = '提交出图任务失败：HTTP 500 后端繁忙'

    const wrapper = mountBoard({
      batches: [
        batch({
          id: 'batch-2',
          status: 'failed',
          groups: [okGroup, failedGroup],
          groupResults: [
            { group: okGroup, jobId: 21, urls: ['/api/results/ok.png'], error: '' },
            { group: failedGroup, jobId: 0, urls: [], error: failureReason },
          ],
          results: ['/api/results/ok.png'],
          total: 2,
          done: 1,
          submitted: 2,
          failed: 1,
        }),
      ],
    })

    const errorCells = wrapper.findAll('[data-testid="studio-result-error"]')
    expect(errorCells).toHaveLength(1)
    expect(errorCells[0].text()).toContain('HTTP 500')
    expect(errorCells[0].text()).toContain('后端繁忙')
  })

  it('batches=[] 时只显示 180px 空态，没有批次列表', () => {
    const wrapper = mountBoard({ batches: [] })

    expect(wrapper.find('[data-testid="studio-preview"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="studio-batch-list"]').exists()).toBe(false)
    expect(wrapper.findAll('.result-board__batch')).toHaveLength(0)
  })
})