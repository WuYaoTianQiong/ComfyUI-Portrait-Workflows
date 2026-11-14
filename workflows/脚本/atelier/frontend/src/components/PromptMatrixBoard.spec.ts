import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import PromptMatrixBoard from './PromptMatrixBoard.vue'
import type { HistoryItem } from '../api/types'
import { buildCells, buildMatrixPlan, type MatrixCell } from '../composables/useWorkflowMatrix'
import type { WorkflowRow } from '../api/workflows'

vi.mock('../composables/useImageLocation', () => ({
  useImageLocation: () => ({ revealImage: vi.fn() }),
}))

function wf(path: string, w: number, h: number): WorkflowRow {
  return {
    path,
    name: `${path}_文生图.json`,
    size_preview: { '1.0x': { '2:3': { width: w, height: h } } },
    caps: { prompt: true, negative: false, negative_effective: false, negative_cfg: null, quality: true, orientation: true },
    params: { quality_mode: 'scale', orientation_mode: 'swap' },
  }
}

const WORKFLOWS = [wf('MOSS', 1024, 1536), wf('Krea2', 1232, 1840)]
const plan = buildMatrixPlan({
  workflows: WORKFLOWS,
  paths: ['MOSS', 'Krea2'],
  ratio: '2:3',
  tier: '1.0x',
  align: 'native',
  count: 2,
})

function image(id: number): HistoryItem {
  return { id, filename: `out_${id}.png`, is_favorite: false, job_id: id } as unknown as HistoryItem
}

function mountBoard(cells: MatrixCell[], extra: Record<string, unknown> = {}) {
  return mount(PromptMatrixBoard, {
    props: { plan, cells, running: false, bestPath: '', lockSeed: true, seedResolved: true, ...extra },
  })
}

describe('PromptMatrixBoard 渲染', () => {
  it('按工作流分列、按张数分行', () => {
    const wrapper = mountBoard(buildCells(plan, 20261112, true))
    expect(wrapper.findAll('.col-head')).toHaveLength(2)
    expect(wrapper.findAll('.cell')).toHaveLength(4)
    expect(wrapper.text()).toContain('MOSS 文生图')
    expect(wrapper.text()).toContain('1024×1536')
    expect(wrapper.text()).toContain('1232×1840')
  })

  it('行头标出同种子', () => {
    const wrapper = mountBoard(buildCells(plan, 20261112, true))
    const heads = wrapper.findAll('.shot-head')
    expect(heads[0].text()).toContain('20261112')
    expect(heads[1].text()).toContain('20261113')
  })

  it('未提交时格子是待提交态', () => {
    const wrapper = mountBoard(buildCells(plan, 1, true))
    expect(wrapper.findAll('.cell.idle')).toHaveLength(4)
    expect(wrapper.text()).toContain('待提交 4 张')
  })

  it('没有可用工作流时给空态而不是空矩阵', () => {
    const empty = buildMatrixPlan({ workflows: WORKFLOWS, paths: [], ratio: '2:3', tier: '1.0x', align: 'native', count: 2 })
    const wrapper = mount(PromptMatrixBoard, {
      props: { plan: empty, cells: [], running: false, bestPath: '', lockSeed: true, seedResolved: true },
    })
    expect(wrapper.text()).toContain('还没有可横评的工作流')
  })

  it('失败格显示原因与重试', async () => {
    const cells = buildCells(plan, 1, true)
    cells[0].status = 'error'
    cells[0].error = 'CUDA out of memory'
    const wrapper = mountBoard(cells)
    expect(wrapper.text()).toContain('CUDA out of memory')
    await wrapper.find('.cell.error button').trigger('click')
    expect(wrapper.emitted('retry')?.[0]).toEqual([cells[0].key])
  })

  it('运行中显示任务号与进度态', () => {
    const cells = buildCells(plan, 1, true)
    cells[0].status = 'running'
    cells[0].jobId = 321
    const wrapper = mountBoard(cells, { running: true })
    expect(wrapper.text()).toContain('生成中')
    expect(wrapper.text()).toContain('任务 #321')
    expect(wrapper.text()).toContain('进行中')
  })
})

describe('PromptMatrixBoard 选择与动作', () => {
  function doneCells() {
    const cells = buildCells(plan, 1, true)
    cells.forEach((c, i) => {
      c.status = 'done'
      c.jobId = 10 + i
      c.image = image(10 + i)
    })
    return cells
  }

  it('勾选后出现批量条，选满 2 张才能对比', async () => {
    const cells = doneCells()
    const wrapper = mountBoard(cells)
    const boxes = wrapper.findAll('.cell-pick')
    await boxes[0].setValue(true)
    expect(wrapper.find('.matrix-bar').exists()).toBe(true)
    const compare = wrapper.findAll('.matrix-bar button')[0]
    expect(compare.attributes('disabled')).toBeDefined()
    await boxes[1].setValue(true)
    expect(wrapper.findAll('.matrix-bar button')[0].attributes('disabled')).toBeUndefined()
    await wrapper.findAll('.matrix-bar button')[0].trigger('click')
    const items = wrapper.emitted('compare')?.[0][0] as HistoryItem[]
    expect(items.map((i) => i.id)).toEqual([10, 12])
  })

  it('最多选 4 张', async () => {
    const wide = buildMatrixPlan({ workflows: WORKFLOWS, paths: ['MOSS', 'Krea2'], ratio: '2:3', tier: '1.0x', align: 'native', count: 4 })
    const cells = buildCells(wide, 1, true)
    cells.forEach((c, i) => {
      c.status = 'done'
      c.image = image(i + 1)
    })
    const wrapper = mount(PromptMatrixBoard, {
      props: { plan: wide, cells, running: false, bestPath: '', lockSeed: true, seedResolved: true },
    })
    const boxes = wrapper.findAll('.cell-pick')
    for (const box of boxes) await box.setValue(true)
    expect(wrapper.find('.bar-count').text()).toContain('已选 4 张')
  })

  it('列内「选为最佳」抛出工作流路径', async () => {
    const wrapper = mountBoard(doneCells())
    await wrapper.findAll('.col-actions button')[0].trigger('click')
    expect(wrapper.emitted('best')?.[0]).toEqual(['MOSS'])
  })

  it('「用它单跑」抛出工作流路径', async () => {
    const wrapper = mountBoard(doneCells())
    await wrapper.findAll('.col-actions button')[1].trigger('click')
    expect(wrapper.emitted('use-workflow')?.[0]).toEqual(['MOSS'])
  })

  it('最佳列带 ★ 标记', () => {
    const wrapper = mountBoard(doneCells(), { bestPath: 'Krea2' })
    const cols = wrapper.findAll('.col-head')
    expect(cols[0].text()).not.toContain('★ 最佳')
    expect(cols[1].text()).toContain('★ 最佳')
  })

  it('点图抛出灯箱打开事件与索引', async () => {
    const wrapper = mountBoard(doneCells())
    await wrapper.findAll('.cell-shot')[2].trigger('click')
    const payload = wrapper.emitted('open-image')?.[0][0] as { items: HistoryItem[]; index: number }
    expect(payload.index).toBe(1)
    expect(payload.items).toHaveLength(4)
  })

  it('清除抛出 clear 并清空选择', async () => {
    const wrapper = mountBoard(doneCells())
    await wrapper.findAll('.cell-pick')[0].setValue(true)
    const clear = wrapper.findAll('.matrix-head button')[1]
    await clear.trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
    expect(wrapper.find('.matrix-bar').exists()).toBe(false)
  })
})
